from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required
from sqlalchemy import extract, func
from datetime import date
from extensions import db
from models import Teacher, User, UserRole, Schedule
from blueprints.admin import admin_bp, require_master
from blueprints.admin.account_utils import next_username, DEFAULT_TEMP_PASSWORD


@admin_bp.route('/teachers')
@login_required
@require_master
def teachers():
    today = date.today()
    teachers = (
        Teacher.query
        .join(Teacher.user)
        .filter(User.is_deleted == False, User.is_active == True)
        .order_by(User.full_name)
        .all()
    )
    teacher_ids = [t.id for t in teachers]

    # Two grouped queries instead of two per teacher.
    class_counts = {}
    session_counts = {}
    if teacher_ids:
        class_counts = dict(
            db.session.query(Schedule.teacher_id, func.count(func.distinct(Schedule.class_id)))
            .filter(Schedule.teacher_id.in_(teacher_ids))
            .group_by(Schedule.teacher_id).all()
        )
        session_counts = dict(
            db.session.query(Schedule.teacher_id, func.count(Schedule.id))
            .filter(
                Schedule.teacher_id.in_(teacher_ids),
                Schedule.is_cancelled == False,
                extract('month', Schedule.date) == today.month,
                extract('year', Schedule.date) == today.year,
            )
            .group_by(Schedule.teacher_id).all()
        )

    return render_template('admin/teachers/list.html',
                           teachers=teachers,
                           class_counts=class_counts,
                           session_counts=session_counts)


@admin_bp.route('/teachers/add', methods=['GET', 'POST'])
@login_required
@require_master
def teacher_add():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        username = request.form.get('username', '').strip()
        phone = request.form.get('phone', '').strip() or None
        gender = request.form.get('gender', '').strip() or None
        is_staff = request.form.get('is_staff') == '1'
        base_salary_raw = request.form.get('base_salary', '').replace(',', '').strip()
        base_salary = float(base_salary_raw) if base_salary_raw else 0

        if not full_name or not gender:
            flash('Vui lòng nhập tên giáo viên và giới tính.', 'danger')
            return render_template('admin/teachers/form.html', action='add', form=request.form)

        if not username:
            username = next_username(UserRole.TEACHER)

        dup_filters = [User.username == username]
        if phone:
            dup_filters.append(User.phone == phone)
        if User.query.filter(db.or_(*dup_filters)).first():
            flash('Tên đăng nhập hoặc số điện thoại đã tồn tại.', 'danger')
            return render_template('admin/teachers/form.html', action='add', form=request.form)

        user = User(full_name=full_name, username=username, phone=phone,
                    role=UserRole.TEACHER, gender=gender, must_change_password=True)
        user.set_password(DEFAULT_TEMP_PASSWORD)
        db.session.add(user)
        db.session.flush()

        teacher = Teacher(user_id=user.id, is_staff=is_staff, base_salary=base_salary)
        db.session.add(teacher)
        db.session.commit()

        flash(f'Đã thêm giáo viên {full_name} — tài khoản {username}, mật khẩu tạm: {DEFAULT_TEMP_PASSWORD} '
              f'— bắt buộc đổi ở lần đăng nhập đầu tiên.', 'success')
        return redirect(url_for('admin.teachers'))

    return render_template('admin/teachers/form.html', action='add', form={})


@admin_bp.route('/teachers/<int:teacher_id>/detail', methods=['GET', 'POST'])
@login_required
@require_master
def teacher_detail(teacher_id):
    teacher = Teacher.query.get_or_404(teacher_id)
    user = teacher.user

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        username = request.form.get('username', '').strip()
        phone = request.form.get('phone', '').strip() or None
        gender = request.form.get('gender', '').strip() or None
        is_staff = request.form.get('is_staff') == '1'
        base_salary_raw = request.form.get('base_salary', '').replace(',', '').strip()
        base_salary = float(base_salary_raw) if base_salary_raw else 0

        if not full_name or not username or not gender:
            flash('Vui lòng nhập tên giáo viên, tên đăng nhập và giới tính.', 'danger')
            return render_template('admin/teachers/form.html', action='edit', teacher=teacher, form=request.form)

        dup_filters = [User.username == username]
        if phone:
            dup_filters.append(User.phone == phone)
        if User.query.filter(db.or_(*dup_filters), User.id != user.id).first():
            flash('Tên đăng nhập hoặc số điện thoại đã được sử dụng.', 'danger')
            return render_template('admin/teachers/form.html', action='edit', teacher=teacher, form=request.form)

        user.full_name = full_name
        user.username = username
        user.phone = phone
        user.gender = gender
        teacher.is_staff = is_staff
        teacher.base_salary = base_salary
        db.session.commit()
        flash(f'Đã cập nhật thông tin {user.full_name}.', 'success')
        return redirect(url_for('admin.teachers'))

    return render_template('admin/teachers/form.html', action='edit', teacher=teacher, form=None)


@admin_bp.route('/teachers/<int:teacher_id>/reset-password', methods=['POST'])
@login_required
@require_master
def teacher_reset_password(teacher_id):
    teacher = Teacher.query.get_or_404(teacher_id)
    teacher.user.set_password(DEFAULT_TEMP_PASSWORD)
    teacher.user.must_change_password = True
    db.session.commit()
    flash(f'Đã đặt lại mật khẩu cho {teacher.full_name} về: {DEFAULT_TEMP_PASSWORD} '
          f'— bắt buộc đổi ở lần đăng nhập đầu tiên.', 'success')
    return redirect(url_for('admin.teachers'))


@admin_bp.route('/teachers/<int:teacher_id>/delete', methods=['POST'])
@login_required
@require_master
def teacher_delete(teacher_id):
    teacher = Teacher.query.get_or_404(teacher_id)
    user = teacher.user
    user.is_deleted = True
    user.is_active = False
    db.session.commit()
    flash(f'Đã xoá tài khoản giáo viên {user.full_name}.', 'success')
    return redirect(url_for('admin.teachers'))
