from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from extensions import db
from models import Teacher, User, UserRole, Schedule
from blueprints.admin import admin_bp, require_admin
from datetime import date


@admin_bp.route('/giao-vien')
@login_required
@require_admin
def teachers():
    teachers = (
        Teacher.query
        .join(Teacher.user)
        .order_by(User.full_name)
        .all()
    )
    class_counts = {}
    session_counts = {}
    for t in teachers:
        class_counts[t.id] = t.schedules.with_entities(
            Schedule.class_id
        ).distinct().count()
        session_counts[t.id] = t.schedules.filter(
            Schedule.is_cancelled == False
        ).count()

    return render_template('admin/teachers/list.html',
                           teachers=teachers,
                           class_counts=class_counts,
                           session_counts=session_counts)


@admin_bp.route('/giao-vien/them', methods=['GET', 'POST'])
@login_required
@require_admin
def teacher_add():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        username = request.form.get('username', '').strip()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '').strip()
        is_staff = request.form.get('is_staff') == '1'
        base_salary = request.form.get('base_salary', 0, type=float)
        note = request.form.get('note', '').strip()

        if not full_name or not username or not phone or not password:
            flash('Vui lòng điền đầy đủ thông tin bắt buộc.', 'danger')
            return render_template('admin/teachers/form.html', action='add', form=request.form)

        if User.query.filter_by(username=username).first():
            flash('Tên đăng nhập đã tồn tại.', 'danger')
            return render_template('admin/teachers/form.html', action='add', form=request.form)

        if User.query.filter_by(phone=phone).first():
            flash('Số điện thoại đã được sử dụng.', 'danger')
            return render_template('admin/teachers/form.html', action='add', form=request.form)

        user = User(
            full_name=full_name,
            username=username,
            phone=phone,
            role=UserRole.TEACHER,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        teacher = Teacher(
            user_id=user.id,
            is_staff=is_staff,
            base_salary=base_salary,
            note=note,
        )
        db.session.add(teacher)
        db.session.commit()
        flash(f'Đã thêm giáo viên {full_name}.', 'success')
        return redirect(url_for('admin.teachers'))

    return render_template('admin/teachers/form.html', action='add', form={})


@admin_bp.route('/giao-vien/<int:teacher_id>/sua', methods=['GET', 'POST'])
@login_required
@require_admin
def teacher_edit(teacher_id):
    teacher = Teacher.query.get_or_404(teacher_id)
    user = teacher.user

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '').strip()
        is_staff = request.form.get('is_staff') == '1'
        base_salary = request.form.get('base_salary', 0, type=float)
        note = request.form.get('note', '').strip()
        is_active = request.form.get('is_active') == '1'

        if not full_name or not phone:
            flash('Vui lòng điền đầy đủ thông tin bắt buộc.', 'danger')
        else:
            # Check phone uniqueness (exclude current user)
            existing_phone = User.query.filter(
                User.phone == phone, User.id != user.id
            ).first()
            if existing_phone:
                flash('Số điện thoại đã được sử dụng.', 'danger')
            else:
                user.full_name = full_name
                user.phone = phone
                user.is_active = is_active
                if password:
                    user.set_password(password)
                teacher.is_staff = is_staff
                teacher.base_salary = base_salary
                teacher.note = note
                db.session.commit()
                flash('Đã cập nhật thông tin giáo viên.', 'success')
                return redirect(url_for('admin.teachers'))

    return render_template('admin/teachers/form.html',
                           action='edit', teacher=teacher, form=teacher)


@admin_bp.route('/giao-vien/<int:teacher_id>/xoa', methods=['POST'])
@login_required
@require_admin
def teacher_delete(teacher_id):
    teacher = Teacher.query.get_or_404(teacher_id)
    teacher.user.is_active = False
    db.session.commit()
    flash(f'Đã vô hiệu hóa tài khoản giáo viên {teacher.full_name}.', 'success')
    return redirect(url_for('admin.teachers'))


@admin_bp.route('/giao-vien/<int:teacher_id>/kich-hoat', methods=['POST'])
@login_required
@require_admin
def teacher_activate(teacher_id):
    teacher = Teacher.query.get_or_404(teacher_id)
    teacher.user.is_active = True
    db.session.commit()
    flash(f'Đã kích hoạt tài khoản giáo viên {teacher.full_name}.', 'success')
    return redirect(url_for('admin.teachers'))
