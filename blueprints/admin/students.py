import io
import csv
import os
import re
import unicodedata
from flask import render_template, redirect, url_for, flash, request, abort, Response, current_app
from flask_login import login_required, current_user
from datetime import date, datetime
from sqlalchemy import func
from extensions import db
from models import (Student, User, Enrollment, Class, TuitionPayment, Score, Reward,
                    StudentLevel, UserRole, Attendance, AttendanceStatus, Teacher, Schedule, School)
from blueprints.admin import admin_bp, require_admin

PHOTO_EXTS = {'jpg', 'jpeg', 'png', 'webp', 'gif'}


def _strip_diacritics(text):
    text = unicodedata.normalize('NFD', text or '')
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return text.replace('Đ', 'D').replace('đ', 'd')


def default_parent_password(full_name, birth_year=None):
    """Default parent account password: @ + tên học sinh không dấu, không khoảng trắng + năm sinh."""
    name_part = re.sub(r'[^a-z0-9]', '', _strip_diacritics(full_name).lower())
    return f'@{name_part}{birth_year or ""}'


@admin_bp.route('/students')
@login_required
@require_admin
def students():
    q            = request.args.get('q', '').strip()
    level        = request.args.get('level', '')
    active_only  = request.args.get('active', '1')
    class_id     = request.args.get('class_id', type=int)
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
        query = query.filter(Student.current_school.ilike(f'%{school_q}%'))
    if class_id:
        query = query.join(Student.enrollments).filter(
            Enrollment.class_id == class_id,
            Enrollment.is_active == True
        ).distinct()
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

    all_classes  = Class.query.filter_by(is_active=True).order_by(Class.name).all()
    all_teachers = Teacher.query.join(Teacher.user).order_by(User.full_name).all()

    return render_template('admin/students/list.html',
                           students=students,
                           pagination=pagination,
                           absent_counts=absent_counts,
                           q=q, level=level, active_only=active_only,
                           class_id=class_id, school_q=school_q, teacher_id=teacher_id,
                           per_page=per_page_raw,
                           levels=StudentLevel.LABELS,
                           all_classes=all_classes,
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


@admin_bp.route('/students/import', methods=['POST'])
@login_required
@require_admin
def import_students():
    file = request.files.get('csv_file')
    if not file or not file.filename.endswith('.csv'):
        flash('Vui lòng chọn file CSV hợp lệ.', 'danger')
        return redirect(url_for('admin.students'))

    try:
        content = file.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(content))
        added = duplicates = missing_info = 0
        for row in reader:
            full_name = (row.get('Họ tên') or row.get('full_name') or '').strip()
            level_raw = (row.get('Cấp học') or row.get('level') or '').strip()
            # Map Vietnamese level labels back to keys
            level_map = {v: k for k, v in StudentLevel.LABELS.items()}
            level = level_map.get(level_raw, level_raw if level_raw in StudentLevel.LABELS else StudentLevel.SECONDARY)

            if not full_name:
                missing_info += 1
                continue

            parent_phone = (row.get('SĐT phụ huynh') or row.get('parent_phone') or '').strip()
            # Skip duplicate by name + parent_phone
            if parent_phone and Student.query.filter_by(full_name=full_name, parent_phone=parent_phone).first():
                duplicates += 1
                continue

            student = Student(
                full_name=full_name,
                level=level,
                current_school=(row.get('Trường') or row.get('current_school') or '').strip(),
                current_grade=(row.get('Lớp tại trường') or row.get('current_grade') or '').strip(),
                parent_name=(row.get('Tên phụ huynh') or row.get('parent_name') or '').strip(),
                parent_phone=parent_phone,
            )
            db.session.add(student)
            added += 1

        db.session.commit()
        if missing_info:
            flash(f'Thiếu thông tin học sinh, vui lòng nhập đầy đủ thông tin cần thiết ({missing_info} dòng bị bỏ qua).', 'danger')
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
        grade = request.form.get('grade', '').strip()
        level = request.form.get('level', StudentLevel.SECONDARY)
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

        if not full_name or not level:
            flash('Vui lòng nhập họ tên và cấp học.', 'danger')
            return render_template('admin/students/form.html',
                                   action='add', levels=StudentLevel.LABELS,
                                   schools=schools, form=request.form)

        try:
            dob = date.fromisoformat(dob_str) if dob_str else None
        except ValueError:
            dob = None

        parent_user_id = None
        if create_parent_account and parent_phone:
            existing_user = User.query.filter_by(phone=parent_phone).first()
            if existing_user:
                if existing_user.role == UserRole.PARENT:
                    parent_user_id = existing_user.id
                    flash(f'Tài khoản phụ huynh SĐT {parent_phone} đã tồn tại, đã liên kết.', 'info')
                else:
                    flash(f'SĐT {parent_phone} đã được dùng cho tài khoản khác.', 'warning')
            else:
                username = f'ph_{parent_phone[-4:]}'
                base_username = username
                counter = 1
                while User.query.filter_by(username=username).first():
                    username = f'{base_username}_{counter}'
                    counter += 1

                new_user = User(
                    full_name=parent_name or f'Phụ huynh của {full_name}',
                    username=username,
                    phone=parent_phone,
                    role=UserRole.PARENT,
                )
                default_pw = default_parent_password(full_name, dob.year if dob else None)
                new_user.set_password(default_pw)
                db.session.add(new_user)
                db.session.flush()
                parent_user_id = new_user.id
                flash(f'Đã tạo tài khoản phụ huynh: {username} / mật khẩu: {default_pw}', 'info')

        student = Student(
            full_name=full_name,
            date_of_birth=dob,
            gender=gender,
            current_school=school,
            school_id=school_id,
            current_grade=grade,
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
                           parent_account=parent_account)


@admin_bp.route('/students/<int:student_id>/reset-parent-password', methods=['POST'])
@login_required
@require_admin
def student_reset_parent_password(student_id):
    student = Student.query.get_or_404(student_id)
    if not student.parent_user_id:
        flash('Học sinh này chưa có tài khoản phụ huynh để đặt lại mật khẩu.', 'warning')
        return redirect(url_for('admin.student_detail', student_id=student_id))

    user = User.query.get_or_404(student.parent_user_id)
    new_pw = default_parent_password(student.full_name, student.date_of_birth.year if student.date_of_birth else None)
    user.set_password(new_pw)
    db.session.commit()
    flash(f'Đã đặt lại mật khẩu phụ huynh về: {new_pw}', 'success')
    return redirect(url_for('admin.student_detail', student_id=student_id))


@admin_bp.route('/students/<int:student_id>/edit', methods=['GET', 'POST'])
@login_required
@require_admin
def student_edit(student_id):
    student = Student.query.get_or_404(student_id)

    schools = School.query.filter_by(is_active=True).order_by(School.name).all()

    if request.method == 'POST':
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
        student.current_grade = request.form.get('grade', '').strip()
        student.level = request.form.get('level', student.level)
        student.parent_name = request.form.get('parent_name', '').strip()
        student.parent_phone = request.form.get('parent_phone', '').strip()
        student.note = request.form.get('note', '').strip()
        student.is_active = request.form.get('is_active') == '1'
        db.session.commit()
        flash('Đã cập nhật thông tin học sinh.', 'success')
        return redirect(url_for('admin.student_detail', student_id=student.id))

    return render_template('admin/students/form.html',
                           action='edit', student=student,
                           levels=StudentLevel.LABELS, schools=schools, form=student)


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

    existing = Enrollment.query.filter_by(student_id=student_id, class_id=class_id).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            existing.discount_pct = discount_pct
            existing.note = note
            db.session.commit()
            flash('Đã kích hoạt lại ghi danh.', 'success')
        else:
            flash('Học sinh đã ghi danh lớp này rồi.', 'warning')
    else:
        e = Enrollment(student_id=student_id, class_id=class_id,
                       discount_pct=discount_pct, note=note)
        db.session.add(e)
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
