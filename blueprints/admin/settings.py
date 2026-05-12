from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from extensions import db
from models import SystemConfig, User, Teacher, Course, UserRole, ContactInquiry
from blueprints.admin import admin_bp, require_admin


@admin_bp.route('/settings')
@login_required
@require_admin
def settings():
    configs = {c.key: c.value for c in SystemConfig.query.all()}
    return render_template('admin/settings.html', configs=configs)


@admin_bp.route('/settings/save', methods=['POST'])
@login_required
@require_admin
def settings_save():
    keys = ['center_name', 'center_address', 'center_phone',
            'zalo_link', 'messenger_link', 'bank_account',
            'hall_of_fame_min_score',
            'hero_bg', 'hero_badge', 'hero_headline1', 'hero_headline2',
            'hero_sub', 'hero_note']
    for key in keys:
        val = request.form.get(key, '').strip()
        SystemConfig.set(key, val)
    flash('Đã lưu cài đặt.', 'success')
    return redirect(url_for('admin.settings'))


@admin_bp.route('/inquiries')
@login_required
@require_admin
def inquiries():
    items = ContactInquiry.query.order_by(ContactInquiry.created_at.desc()).all()
    # Mark all as read when admin opens the page
    ContactInquiry.query.filter_by(is_read=False).update({'is_read': True})
    db.session.commit()
    return render_template('admin/inquiries.html', inquiries=items)


@admin_bp.route('/inquiries/<int:inquiry_id>/delete', methods=['POST'])
@login_required
@require_admin
def inquiry_delete(inquiry_id):
    inquiry = ContactInquiry.query.get_or_404(inquiry_id)
    db.session.delete(inquiry)
    db.session.commit()
    flash('Đã xóa yêu cầu liên hệ.', 'success')
    return redirect(url_for('admin.inquiries'))


@admin_bp.route('/accounts')
@login_required
@require_admin
def users():
    users = User.query.order_by(User.role, User.full_name).all()
    return render_template('admin/users.html', users=users)


@admin_bp.route('/accounts/add', methods=['POST'])
@login_required
@require_admin
def user_add():
    full_name = request.form.get('full_name', '').strip()
    phone = request.form.get('phone', '').strip()
    username = request.form.get('username', '').strip()
    role = request.form.get('role', 'parent')
    password = request.form.get('password', '').strip()
    is_staff = request.form.get('is_staff') == '1'
    base_salary = request.form.get('base_salary', 0, type=float)
    note = request.form.get('specialty', '').strip()

    if not all([full_name, phone, username, password]):
        flash('Vui lòng điền đầy đủ thông tin.', 'danger')
        return redirect(url_for('admin.users'))

    if User.query.filter((User.phone == phone) | (User.username == username)).first():
        flash('Số điện thoại hoặc tên đăng nhập đã tồn tại.', 'danger')
        return redirect(url_for('admin.users'))

    user = User(full_name=full_name, username=username, phone=phone, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()

    if role == UserRole.TEACHER:
        teacher = Teacher(user_id=user.id, note=note,
                          is_staff=is_staff, base_salary=base_salary)
        db.session.add(teacher)

    db.session.commit()
    flash(f'Đã tạo tài khoản {username}.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/accounts/<int:user_id>/change-password', methods=['POST'])
@login_required
@require_admin
def user_reset_password(user_id):
    user = User.query.get_or_404(user_id)
    new_pw = request.form.get('password', '').strip()
    if len(new_pw) < 6:
        flash('Mật khẩu tối thiểu 6 ký tự.', 'danger')
    else:
        user.set_password(new_pw)
        db.session.commit()
        flash(f'Đã đổi mật khẩu cho {user.full_name}.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/accounts/<int:user_id>/lock', methods=['POST'])
@login_required
@require_admin
def user_toggle_active(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('Không thể khóa tài khoản của chính mình.', 'danger')
    else:
        user.is_active = not user.is_active
        db.session.commit()
        status = 'mở' if user.is_active else 'khóa'
        flash(f'Đã {status} tài khoản {user.full_name}.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/courses')
@login_required
@require_admin
def courses():
    # Auto-deduplicate: keep oldest course per name, reassign classes, delete duplicates
    from models import Class
    all_items = Course.query.order_by(Course.name, Course.id).all()
    seen = {}
    to_delete = []
    for c in all_items:
        if c.name not in seen:
            seen[c.name] = c
        else:
            # Reassign any classes referencing the duplicate to the kept course
            Class.query.filter_by(course_id=c.id).update({'course_id': seen[c.name].id})
            to_delete.append(c)
    if to_delete:
        for c in to_delete:
            db.session.delete(c)
        db.session.commit()
    items = sorted(seen.values(), key=lambda c: c.name)
    return render_template('admin/courses.html', courses=items)


@admin_bp.route('/courses/add', methods=['POST'])
@login_required
@require_admin
def course_add():
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    if not name:
        flash('Vui lòng nhập tên môn học.', 'danger')
    elif Course.query.filter_by(name=name).first():
        flash(f'Môn "{name}" đã tồn tại.', 'warning')
    else:
        db.session.add(Course(name=name, description=description))
        db.session.commit()
        flash(f'Đã thêm môn {name}.', 'success')
    return redirect(url_for('admin.courses'))


@admin_bp.route('/courses/<int:course_id>/edit', methods=['POST'])
@login_required
@require_admin
def course_edit(course_id):
    c = Course.query.get_or_404(course_id)
    c.name = request.form.get('name', c.name).strip()
    c.description = request.form.get('description', '').strip()
    c.is_active = request.form.get('is_active') == '1'
    db.session.commit()
    flash('Đã cập nhật môn học.', 'success')
    return redirect(url_for('admin.courses'))
