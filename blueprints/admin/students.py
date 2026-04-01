from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from datetime import date, datetime
from extensions import db
from models import Student, User, Enrollment, Class, TuitionPayment, Score, Reward, StudentLevel, UserRole
from blueprints.admin import admin_bp, require_admin


@admin_bp.route('/hoc-sinh')
@login_required
@require_admin
def students():
    q = request.args.get('q', '').strip()
    level = request.args.get('level', '')
    active_only = request.args.get('active', '1')

    query = Student.query
    if q:
        query = query.filter(
            Student.full_name.ilike(f'%{q}%') |
            Student.parent_phone.ilike(f'%{q}%') |
            Student.school.ilike(f'%{q}%')
        )
    if level:
        query = query.filter_by(level=level)
    if active_only == '1':
        query = query.filter_by(is_active=True)

    students = query.order_by(Student.full_name).all()
    return render_template('admin/students/list.html',
                           students=students, q=q, level=level,
                           active_only=active_only,
                           levels=StudentLevel.LABELS)


@admin_bp.route('/hoc-sinh/them', methods=['GET', 'POST'])
@login_required
@require_admin
def student_add():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        dob_str = request.form.get('dob', '')
        gender = request.form.get('gender', 'male')
        school = request.form.get('school', '').strip()
        grade = request.form.get('grade', '').strip()
        level = request.form.get('level', StudentLevel.SECONDARY)
        parent_name = request.form.get('parent_name', '').strip()
        parent_phone = request.form.get('parent_phone', '').strip()
        note = request.form.get('note', '').strip()
        create_parent_account = request.form.get('create_parent_account') == '1'

        if not full_name or not level:
            flash('Vui lòng nhập họ tên và cấp học.', 'danger')
            return render_template('admin/students/form.html',
                                   action='add', levels=StudentLevel.LABELS, form=request.form)

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
                # Create parent user
                username = f'ph_{parent_phone[-4:]}'
                # Ensure unique username
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
                new_user.set_password(parent_phone[-6:])  # Default: last 6 digits of phone
                db.session.add(new_user)
                db.session.flush()
                parent_user_id = new_user.id
                flash(f'Đã tạo tài khoản phụ huynh: {username} / mật khẩu: {parent_phone[-6:]}', 'info')

        student = Student(
            full_name=full_name,
            dob=dob,
            gender=gender,
            school=school,
            grade=grade,
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
                           action='add', levels=StudentLevel.LABELS, form={})


@admin_bp.route('/hoc-sinh/<int:student_id>')
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
    return render_template('admin/students/detail.html',
                           student=student,
                           today=today,
                           available_classes=available_classes,
                           enrolled_class_ids=enrolled_class_ids,
                           recent_scores=recent_scores,
                           recent_rewards=recent_rewards,
                           tuition_records=tuition_records)


@admin_bp.route('/hoc-sinh/<int:student_id>/sua', methods=['GET', 'POST'])
@login_required
@require_admin
def student_edit(student_id):
    student = Student.query.get_or_404(student_id)

    if request.method == 'POST':
        student.full_name = request.form.get('full_name', student.full_name).strip()
        dob_str = request.form.get('dob', '')
        try:
            student.dob = date.fromisoformat(dob_str) if dob_str else student.dob
        except ValueError:
            pass
        student.gender = request.form.get('gender', student.gender)
        student.school = request.form.get('school', '').strip()
        student.grade = request.form.get('grade', '').strip()
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
                           levels=StudentLevel.LABELS, form=student)


@admin_bp.route('/hoc-sinh/<int:student_id>/ghi-danh', methods=['POST'])
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


@admin_bp.route('/hoc-sinh/<int:student_id>/huy-ghi-danh/<int:class_id>', methods=['POST'])
@login_required
@require_admin
def student_unenroll(student_id, class_id):
    e = Enrollment.query.filter_by(student_id=student_id, class_id=class_id).first_or_404()
    e.is_active = False
    db.session.commit()
    flash('Đã hủy ghi danh.', 'success')
    return redirect(url_for('admin.student_detail', student_id=student_id))
