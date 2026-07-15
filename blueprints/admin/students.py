import io
import csv
import os
from flask import render_template, redirect, url_for, flash, request, abort, Response, current_app
from flask_login import login_required, current_user
from datetime import date, datetime
from sqlalchemy import func
from extensions import db
from models import (Student, User, Enrollment, Class, TuitionPayment, Score, Reward,
                    StudentLevel, UserRole, Attendance, AttendanceStatus, Teacher, Schedule, School,
                    GRADE_BY_LEVEL, GRADE_SEQUENCE)
from blueprints.admin import admin_bp, require_admin
from blueprints.admin.account_utils import next_username, DEFAULT_TEMP_PASSWORD
from blueprints.admin.academic import current_academic_year_start
from services.schedule_service import (find_student_schedule_conflict, schedule_conflict_message,
                                       notify_class_teachers)

PHOTO_EXTS = {'jpg', 'jpeg', 'png', 'webp', 'gif'}


def _create_or_link_parent_account(student_name, parent_name, parent_phone=None):
    """Link an existing parent User by phone (if a phone was given), or create
    one with an auto-generated username + temp password (must change it on
    first login) — phone is optional, only admin-typed username/phone ever is.
    Flashes the outcome. Returns the User.id to use as Student.parent_user_id,
    or None if nothing could be linked."""
    if parent_phone:
        existing_user = User.query.filter_by(phone=parent_phone).first()
        if existing_user:
            if existing_user.role == UserRole.PARENT:
                flash(f'Tài khoản phụ huynh SĐT {parent_phone} đã tồn tại, đã liên kết.', 'info')
                return existing_user.id
            flash(f'SĐT {parent_phone} đã được dùng cho tài khoản khác.', 'warning')
            return None

    username = next_username(UserRole.PARENT)
    new_user = User(
        full_name=parent_name or f'Phụ huynh của {student_name}',
        username=username,
        phone=parent_phone or None,
        role=UserRole.PARENT,
        must_change_password=True,
    )
    new_user.set_password(DEFAULT_TEMP_PASSWORD)
    db.session.add(new_user)
    db.session.flush()
    flash(f'Đã tạo tài khoản phụ huynh: {username} / mật khẩu tạm: {DEFAULT_TEMP_PASSWORD} '
          f'— bắt buộc đổi ở lần đăng nhập đầu tiên.', 'info')
    return new_user.id


@admin_bp.route('/students')
@login_required
@require_admin
def students():
    q            = request.args.get('q', '').strip()
    level        = request.args.get('level', '')
    active_only  = request.args.get('active', '1')
    grade        = request.args.get('grade', '').strip()
    school_q     = request.args.get('school_q', '').strip()
    teacher_id   = request.args.get('teacher_id', type=int)

    query = Student.query.filter_by(is_deleted=False)

    if q:
        query = query.filter(
            Student.full_name.ilike(f'%{q}%') |
            Student.parent_phone.ilike(f'%{q}%') |
            Student.current_school.ilike(f'%{q}%')
        )
    if level:
        query = query.filter_by(level=level)
    if active_only == '1':
        query = query.filter_by(is_active=True)
    if school_q:
        query = query.filter(Student.current_school == school_q)
    if grade:
        # Lọc theo khối lớp của học sinh (current_grade, vd "Lớp 5") — không
        # phải lớp học/môn học cụ thể đang theo (đó là filter teacher_id/lớp
        # riêng nếu cần). Học sinh lớp 5 học Toán vẫn lọc ra khi chọn "Lớp 5".
        query = query.filter(Student.current_grade == grade)
    if teacher_id:
        teacher_class_ids = (
            db.session.query(Schedule.class_id)
            .filter(Schedule.teacher_id == teacher_id)
            .distinct()
            .subquery()
        )
        query = query.join(Student.enrollments).filter(
            Enrollment.class_id.in_(teacher_class_ids),
            Enrollment.is_active == True
        ).distinct()

    page         = request.args.get('page', 1, type=int)
    per_page_raw = request.args.get('per_page', '10')
    if per_page_raw not in ('10', '20', '40', '80', 'all'):
        per_page_raw = '10'
    per_page = max(query.count(), 1) if per_page_raw == 'all' else int(per_page_raw)
    pagination = query.order_by(Student.full_name).paginate(page=page, per_page=per_page, error_out=False)
    students   = pagination.items

    # Absent counts (single query for current page only)
    student_ids = [s.id for s in students]
    absent_counts = {}
    if student_ids:
        rows = (
            db.session.query(Attendance.student_id, func.count(Attendance.id))
            .filter(Attendance.student_id.in_(student_ids))
            .filter(Attendance.status == AttendanceStatus.ABSENT)
            .group_by(Attendance.student_id)
            .all()
        )
        absent_counts = dict(rows)

    all_teachers = Teacher.query.join(Teacher.user).order_by(User.full_name).all()
    school_rows = (db.session.query(Student.current_school)
                   .filter(Student.current_school.isnot(None), Student.current_school != '')
                   .distinct().order_by(Student.current_school).all())
    school_options = [r[0] for r in school_rows]

    is_filtered = bool(q or level or grade or school_q or teacher_id or active_only != '1')

    return render_template('admin/students/list.html',
                           students=students,
                           pagination=pagination,
                           absent_counts=absent_counts,
                           q=q, level=level, active_only=active_only,
                           grade=grade, school_q=school_q, teacher_id=teacher_id,
                           is_filtered=is_filtered,
                           per_page=per_page_raw,
                           levels=StudentLevel.LABELS,
                           grade_options=GRADE_SEQUENCE,
                           school_options=school_options,
                           all_teachers=all_teachers)


@admin_bp.route('/students/bulk-delete', methods=['POST'])
@login_required
@require_admin
def students_bulk_delete():
    student_ids = request.form.getlist('student_ids', type=int)
    if not student_ids:
        flash('Vui lòng chọn ít nhất 1 học sinh để xóa.', 'warning')
        return redirect(url_for('admin.students'))

    count = Student.query.filter(Student.id.in_(student_ids)).update(
        {'is_deleted': True}, synchronize_session=False
    )
    db.session.commit()
    flash(f'Đã xóa {count} học sinh.', 'success')
    return redirect(url_for('admin.students'))


@admin_bp.route('/students/export')
@login_required
@require_admin
def export_students():
    students = Student.query.filter_by(is_deleted=False).order_by(Student.full_name).all()

    student_ids = [s.id for s in students]
    absent_counts = {}
    if student_ids:
        rows = (
            db.session.query(Attendance.student_id, func.count(Attendance.id))
            .filter(Attendance.student_id.in_(student_ids))
            .filter(Attendance.status == AttendanceStatus.ABSENT)
            .group_by(Attendance.student_id)
            .all()
        )
        absent_counts = dict(rows)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Họ tên', 'Cấp học', 'Trường', 'Lớp tại trường',
                     'Tên phụ huynh', 'SĐT phụ huynh', 'Số lớp đang học',
                     'Ngày nghỉ', 'Trạng thái'])
    for s in students:
        enrolled = s.enrollments.filter_by(is_active=True).count()
        writer.writerow([
            s.id, s.full_name,
            StudentLevel.LABELS.get(s.level, s.level),
            s.current_school or '',
            s.current_grade or '',
            s.parent_name or '',
            s.parent_phone or '',
            enrolled,
            absent_counts.get(s.id, 0),
            'Đang học' if s.is_active else 'Nghỉ học',
        ])

    output.seek(0)
    return Response(
        '\ufeff' + output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=hoc-sinh.csv'}
    )


def _resolve_import_grade(grade_raw, level):
    """Map a CSV 'Lớp học' cell (bare number like '6', or a full label like
    'Tiền tiểu học') to a canonical GRADE_SEQUENCE value valid for `level`,
    or None if it can't be resolved / doesn't belong to that level."""
    grade_raw = (grade_raw or '').strip()
    if not grade_raw:
        return None
    candidate = f'Lớp {grade_raw}' if grade_raw.isdigit() else grade_raw
    return candidate if candidate in GRADE_BY_LEVEL.get(level, []) else None


@admin_bp.route('/students/import-template')
@login_required
@require_admin
def students_import_template():
    """Sample CSV showing the exact columns/format import_students() expects."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Họ tên', 'Giới tính', 'Cấp học', 'Lớp học', 'Trường', 'Tên phụ huynh', 'SĐT phụ huynh'])
    writer.writerow(['Châu Anh', 'Nữ', 'THCS', '6', '', '', ''])
    writer.writerow(['Nhất Phong', 'Nam', 'THPT', '10', '', '', ''])
    writer.writerow(['Khả Phi', 'Nữ', 'Tiểu học', 'Tiền tiểu học', '', '', ''])
    output.seek(0)
    return Response(
        '\ufeff' + output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=mau-import-hoc-sinh.csv'}
    )


@admin_bp.route('/students/import', methods=['POST'])
@login_required
@require_admin
def import_students():
    file = request.files.get('csv_file')
    if not file or not file.filename.endswith('.csv'):
        flash('Vui lòng chọn file CSV hợp lệ.', 'danger')
        return redirect(url_for('admin.students'))

    level_map = {v: k for k, v in StudentLevel.LABELS.items()}
    gender_map = {'nam': 'male', 'nữ': 'female'}
    grade_year = current_academic_year_start()

    try:
        content = file.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(content))
        added = duplicates = missing_info = 0
        for row in reader:
            full_name = (row.get('Họ tên') or '').strip()
            gender_raw = (row.get('Giới tính') or '').strip().lower()
            level_raw = (row.get('Cấp học') or '').strip()

            gender = gender_map.get(gender_raw)  # optional — None if blank/unrecognized
            level = level_map.get(level_raw) or (level_raw if level_raw in StudentLevel.LABELS else None)
            grade = _resolve_import_grade(row.get('Lớp học'), level) if level else None

            if not full_name or not level or not grade:
                missing_info += 1
                continue

            parent_phone = (row.get('SĐT phụ huynh') or '').strip()
            # Skip duplicate by name + grade — parent_phone is often blank on
            # these rows, so relying on it let the same student get imported
            # again (and again) under a brand-new record every time, silently
            # fragmenting their class enrollments/tuition/attendance history
            # across duplicates instead of catching the re-import.
            if Student.query.filter_by(full_name=full_name, current_grade=grade).first():
                duplicates += 1
                continue

            student = Student(
                full_name=full_name,
                gender=gender,
                level=level,
                current_grade=grade,
                grade_year=grade_year,
                current_school=(row.get('Trường') or '').strip(),
                parent_name=(row.get('Tên phụ huynh') or '').strip(),
                parent_phone=parent_phone,
            )
            db.session.add(student)
            added += 1

        db.session.commit()
        if missing_info:
            flash(f'Thiếu hoặc sai thông tin bắt buộc (Họ tên, Cấp học, Lớp học) — '
                  f'{missing_info} dòng bị bỏ qua.', 'danger')
        if added or duplicates:
            flash(f'Import thành công: {added} học sinh mới, bỏ qua {duplicates} dòng trùng thông tin.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi đọc file: {e}', 'danger')

    return redirect(url_for('admin.students'))


@admin_bp.route('/students/add', methods=['GET', 'POST'])
@login_required
@require_admin
def student_add():
    schools = School.query.filter_by(is_active=True).order_by(School.name).all()

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        dob_str = request.form.get('dob', '')
        gender = request.form.get('gender', 'male')
        school_id = request.form.get('school_id', type=int) or None
        school_custom = request.form.get('school_custom', '').strip()
        current_grade = request.form.get('current_grade', '').strip()
        level = request.form.get('level', '').strip()
        parent_name = request.form.get('parent_name', '').strip()
        parent_phone = request.form.get('parent_phone', '').strip()
        note = request.form.get('note', '').strip()
        create_parent_account = request.form.get('create_parent_account') == '1'

        # Resolve school name
        if school_id:
            school_obj = School.query.get(school_id)
            school = school_obj.name if school_obj else school_custom
        else:
            school = school_custom

        if not full_name or not level or not current_grade:
            flash('Vui lòng nhập họ tên, cấp học và lớp.', 'danger')
            return render_template('admin/students/form.html',
                                   action='add', levels=StudentLevel.LABELS,
                                   grade_by_level=GRADE_BY_LEVEL,
                                   schools=schools, form=request.form)
        if current_grade not in GRADE_BY_LEVEL.get(level, []):
            flash('Lớp học không hợp lệ với cấp học đã chọn.', 'danger')
            return render_template('admin/students/form.html',
                                   action='add', levels=StudentLevel.LABELS,
                                   grade_by_level=GRADE_BY_LEVEL,
                                   schools=schools, form=request.form)

        try:
            dob = date.fromisoformat(dob_str) if dob_str else None
        except ValueError:
            dob = None

        parent_user_id = None
        if create_parent_account:
            parent_user_id = _create_or_link_parent_account(full_name, parent_name, parent_phone)

        student = Student(
            full_name=full_name,
            date_of_birth=dob,
            gender=gender,
            current_school=school,
            school_id=school_id,
            current_grade=current_grade,
            grade_year=current_academic_year_start(),
            level=level,
            parent_name=parent_name,
            parent_phone=parent_phone,
            parent_user_id=parent_user_id,
            note=note,
        )
        db.session.add(student)
        db.session.commit()
        flash(f'Đã thêm học sinh {full_name}.', 'success')
        return redirect(url_for('admin.student_detail', student_id=student.id))

    return render_template('admin/students/form.html',
                           action='add', levels=StudentLevel.LABELS,
                           grade_by_level=GRADE_BY_LEVEL,
                           schools=schools, form={})


@admin_bp.route('/students/<int:student_id>')
@login_required
@require_admin
def student_detail(student_id):
    student = Student.query.get_or_404(student_id)
    today = date.today()
    available_classes = Class.query.filter_by(is_active=True).all()
    enrolled_class_ids = {e.class_id for e in student.enrollments.filter_by(is_active=True).all()}
    recent_scores = student.scores.order_by(Score.exam_date.desc()).limit(10).all()
    recent_rewards = student.rewards.order_by(Reward.reward_date.desc()).limit(5).all()
    tuition_records = student.tuition_payments.order_by(
        TuitionPayment.year.desc(), TuitionPayment.month.desc()
    ).limit(12).all()

    # Học phí tháng hiện tại: tổng hợp theo lớp đang học
    current_month_tuition = student.tuition_payments.filter_by(
        month=today.month, year=today.year
    ).all()
    current_total = sum(t.amount for t in current_month_tuition)
    current_unpaid = sum(t.amount for t in current_month_tuition if not t.is_paid)

    parent_account = User.query.get(student.parent_user_id) if student.parent_user_id else None

    return render_template('admin/students/detail.html',
                           student=student,
                           today=today,
                           available_classes=available_classes,
                           enrolled_class_ids=enrolled_class_ids,
                           recent_scores=recent_scores,
                           recent_rewards=recent_rewards,
                           tuition_records=tuition_records,
                           current_month_tuition=current_month_tuition,
                           current_total=current_total,
                           current_unpaid=current_unpaid,
                           parent_account=parent_account,
                           default_temp_password=DEFAULT_TEMP_PASSWORD)


@admin_bp.route('/students/<int:student_id>/reset-parent-password', methods=['POST'])
@login_required
@require_admin
def student_reset_parent_password(student_id):
    student = Student.query.get_or_404(student_id)
    if not student.parent_user_id:
        flash('Học sinh này chưa có tài khoản phụ huynh để đặt lại mật khẩu.', 'warning')
        return redirect(url_for('admin.student_detail', student_id=student_id))

    user = User.query.get_or_404(student.parent_user_id)
    user.set_password(DEFAULT_TEMP_PASSWORD)
    user.must_change_password = True
    db.session.commit()
    flash(f'Đã đặt lại mật khẩu phụ huynh về: {DEFAULT_TEMP_PASSWORD} '
          f'— bắt buộc đổi ở lần đăng nhập đầu tiên.', 'success')
    return redirect(url_for('admin.student_detail', student_id=student_id))


@admin_bp.route('/students/<int:student_id>/create-parent-account', methods=['POST'])
@login_required
@require_admin
def student_create_parent_account(student_id):
    """Create/link a parent account after the fact, for students added without
    checking "Tạo tài khoản phụ huynh" (or without a phone) at creation time."""
    student = Student.query.get_or_404(student_id)
    if student.parent_user_id:
        flash('Học sinh đã có tài khoản phụ huynh liên kết.', 'warning')
        return redirect(url_for('admin.student_detail', student_id=student_id))

    parent_phone = request.form.get('parent_phone', '').strip()
    parent_name = request.form.get('parent_name', '').strip()

    parent_user_id = _create_or_link_parent_account(student.full_name, parent_name, parent_phone)
    if parent_user_id:
        if parent_phone:
            student.parent_phone = parent_phone
        if parent_name:
            student.parent_name = parent_name
        student.parent_user_id = parent_user_id
        db.session.commit()
    return redirect(url_for('admin.student_detail', student_id=student_id))


@admin_bp.route('/students/<int:student_id>/edit', methods=['GET', 'POST'])
@login_required
@require_admin
def student_edit(student_id):
    student = Student.query.get_or_404(student_id)

    schools = School.query.filter_by(is_active=True).order_by(School.name).all()

    if request.method == 'POST':
        current_grade = request.form.get('current_grade', '').strip()
        level = request.form.get('level', '').strip()
        if not current_grade or not level or current_grade not in GRADE_BY_LEVEL.get(level, []):
            flash('Vui lòng chọn cấp học và lớp hợp lệ.', 'danger')
            return render_template('admin/students/form.html',
                                   action='edit', student=student,
                                   levels=StudentLevel.LABELS, grade_by_level=GRADE_BY_LEVEL,
                                   schools=schools, form=request.form)

        student.full_name = request.form.get('full_name', student.full_name).strip()
        dob_str = request.form.get('dob', '')
        try:
            student.date_of_birth = date.fromisoformat(dob_str) if dob_str else student.date_of_birth
        except ValueError:
            pass
        student.gender = request.form.get('gender', student.gender)
        school_id = request.form.get('school_id', type=int) or None
        school_custom = request.form.get('school_custom', '').strip()
        if school_id:
            school_obj = School.query.get(school_id)
            student.current_school = school_obj.name if school_obj else school_custom
            student.school_id = school_id
        else:
            student.current_school = school_custom
            student.school_id = None
        if current_grade != student.current_grade:
            student.grade_year = current_academic_year_start()
        student.current_grade = current_grade
        student.level = level
        student.parent_name = request.form.get('parent_name', '').strip()
        student.parent_phone = request.form.get('parent_phone', '').strip()
        student.note = request.form.get('note', '').strip()
        student.is_active = request.form.get('is_active') == '1'
        db.session.commit()
        flash('Đã cập nhật thông tin học sinh.', 'success')
        return redirect(url_for('admin.student_detail', student_id=student.id))

    return render_template('admin/students/form.html',
                           action='edit', student=student,
                           levels=StudentLevel.LABELS, grade_by_level=GRADE_BY_LEVEL,
                           schools=schools, form=student)


@admin_bp.route('/students/<int:student_id>/enroll', methods=['POST'])
@login_required
@require_admin
def student_enroll(student_id):
    student = Student.query.get_or_404(student_id)
    class_id = request.form.get('class_id', type=int)
    discount_pct = request.form.get('discount_pct', 0, type=float)
    note = request.form.get('note', '').strip()

    if not class_id:
        flash('Vui lòng chọn lớp.', 'danger')
        return redirect(url_for('admin.student_detail', student_id=student_id))

    target_class = Class.query.get_or_404(class_id)
    conflict = find_student_schedule_conflict(student, target_class)
    if conflict:
        flash(schedule_conflict_message(student, target_class, conflict), 'danger')
        return redirect(url_for('admin.student_detail', student_id=student_id))

    existing = Enrollment.query.filter_by(student_id=student_id, class_id=class_id).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            existing.discount_pct = discount_pct
            existing.note = note
            notify_class_teachers(target_class, 'Học sinh mới',
                                  f'{student.full_name} được thêm vào lớp {target_class.name}.',
                                  link=url_for('teacher.scores_list'))
            db.session.commit()
            flash('Đã kích hoạt lại ghi danh.', 'success')
        else:
            flash('Học sinh đã ghi danh lớp này rồi.', 'warning')
    else:
        e = Enrollment(student_id=student_id, class_id=class_id,
                       discount_pct=discount_pct, note=note)
        db.session.add(e)
        notify_class_teachers(target_class, 'Học sinh mới',
                              f'{student.full_name} được thêm vào lớp {target_class.name}.',
                              link=url_for('teacher.scores_list'))
        db.session.commit()
        flash('Ghi danh thành công.', 'success')

    return redirect(url_for('admin.student_detail', student_id=student_id))


@admin_bp.route('/students/<int:student_id>/unenroll/<int:class_id>', methods=['POST'])
@login_required
@require_admin
def student_unenroll(student_id, class_id):
    e = Enrollment.query.filter_by(student_id=student_id, class_id=class_id).first_or_404()
    e.is_active = False
    db.session.commit()
    flash('Đã hủy ghi danh.', 'success')
    return redirect(url_for('admin.student_detail', student_id=student_id))


@admin_bp.route('/students/<int:student_id>/photo', methods=['POST'])
@login_required
@require_admin
def student_photo_upload(student_id):
    student = Student.query.get_or_404(student_id)
    photo = request.files.get('photo')
    if not photo or photo.filename == '':
        flash('Vui lòng chọn ảnh.', 'danger')
        return redirect(url_for('admin.student_detail', student_id=student_id))
    ext = photo.filename.rsplit('.', 1)[-1].lower() if '.' in photo.filename else ''
    if ext not in PHOTO_EXTS:
        flash('Chỉ chấp nhận ảnh JPG, PNG, WEBP, GIF.', 'danger')
        return redirect(url_for('admin.student_detail', student_id=student_id))
    photo_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'students')
    os.makedirs(photo_dir, exist_ok=True)
    filename = f'student_{student_id}.{ext}'
    # Remove old photo files for this student
    for old_ext in PHOTO_EXTS:
        old = os.path.join(photo_dir, f'student_{student_id}.{old_ext}')
        if os.path.exists(old):
            os.remove(old)
    photo.save(os.path.join(photo_dir, filename))
    student.photo_path = f'uploads/students/{filename}'
    db.session.commit()
    flash('Đã cập nhật ảnh học sinh.', 'success')
    return redirect(url_for('admin.student_detail', student_id=student_id))


@admin_bp.route('/students/<int:student_id>/photo/delete', methods=['POST'])
@login_required
@require_admin
def student_photo_delete(student_id):
    student = Student.query.get_or_404(student_id)
    if student.photo_path:
        full_path = os.path.join(current_app.root_path, 'static', student.photo_path)
        if os.path.exists(full_path):
            os.remove(full_path)
        student.photo_path = None
        db.session.commit()
        flash('Đã xóa ảnh.', 'success')
    return redirect(url_for('admin.student_detail', student_id=student_id))
