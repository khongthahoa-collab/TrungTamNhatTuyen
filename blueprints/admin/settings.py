from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from extensions import db
from models import SystemConfig, User, Course, UserRole, ContactInquiry, Teacher, PermissionGroup
from blueprints.admin import admin_bp, require_admin
from blueprints.admin.account_utils import next_username, DEFAULT_TEMP_PASSWORD
from blueprints.permissions import ADMIN_PERMISSION_MODULES
from blueprints.pagination_utils import paginate_list

PERMISSION_LEVELS = ('read', 'write', 'deny')


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
            'vietqr_bank_id', 'vietqr_bank_name', 'vietqr_account_number', 'vietqr_account_name',
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
    page = request.args.get('page', 1, type=int)
    pagination = ContactInquiry.query.order_by(ContactInquiry.created_at.desc()) \
        .paginate(page=page, per_page=50, error_out=False)
    # Mark all as read when admin opens the page
    ContactInquiry.query.filter_by(is_read=False).update({'is_read': True})
    db.session.commit()
    return render_template('admin/inquiries.html', inquiries=pagination.items, pagination=pagination)


@admin_bp.route('/inquiries/<int:inquiry_id>/delete', methods=['POST'])
@login_required
@require_admin
def inquiry_delete(inquiry_id):
    inquiry = ContactInquiry.query.get_or_404(inquiry_id)
    db.session.delete(inquiry)
    db.session.commit()
    flash('Đã xóa yêu cầu liên hệ.', 'success')
    return redirect(url_for('admin.inquiries'))


def _parse_permission_matrix(form):
    """Read one 'read'/'write'/'deny' select per ADMIN_PERMISSION_MODULES entry."""
    perms = {}
    for key, _, _ in ADMIN_PERMISSION_MODULES:
        level = form.get(f'perm_{key}', 'deny')
        perms[key] = level if level in PERMISSION_LEVELS else 'deny'
    return perms


@admin_bp.route('/accounts')
@login_required
@require_admin
def users():
    """Admin-only account management — teacher accounts live on /admin/teachers,
    parent accounts are created from the student pages."""
    page = request.args.get('page', 1, type=int)
    pagination = (User.query.filter_by(is_deleted=False, role=UserRole.ADMIN)
                 .order_by(User.full_name).paginate(page=page, per_page=50, error_out=False))
    groups = PermissionGroup.query.order_by(PermissionGroup.name).all()
    return render_template('admin/users.html', users=pagination.items, pagination=pagination,
                           admin_modules=ADMIN_PERMISSION_MODULES, permission_groups=groups)


@admin_bp.route('/permission')
@login_required
@require_admin
def admin_permission():
    """Permission Group management — a named, reusable set of module
    permissions that admin accounts are assigned to (see
    models.PermissionGroup), instead of each account carrying its own
    ad-hoc matrix. With no group_id given, shows the group list; with
    group_id, shows that group's editable matrix."""
    if not current_user.is_master:
        abort(403)

    group_id = request.args.get('group_id', type=int)
    if not group_id:
        groups = PermissionGroup.query.order_by(PermissionGroup.name).all()
        return render_template('admin/permission.html', target_group=None, groups=groups,
                               admin_modules=ADMIN_PERMISSION_MODULES)

    target_group = PermissionGroup.query.get_or_404(group_id)
    return render_template('admin/permission.html', target_group=target_group, groups=None,
                           admin_modules=ADMIN_PERMISSION_MODULES)


@admin_bp.route('/permission-groups/add', methods=['POST'])
@login_required
@require_admin
def permission_group_add():
    if not current_user.is_master:
        abort(403)
    name = request.form.get('name', '').strip()
    if not name:
        flash('Vui lòng nhập tên nhóm quyền.', 'danger')
        return redirect(url_for('admin.admin_permission'))
    if PermissionGroup.query.filter_by(name=name).first():
        flash('Tên nhóm quyền đã tồn tại.', 'danger')
        return redirect(url_for('admin.admin_permission'))
    group = PermissionGroup(name=name)
    group.set_permissions({key: 'deny' for key, _, _ in ADMIN_PERMISSION_MODULES})
    db.session.add(group)
    db.session.commit()
    flash(f'Đã tạo nhóm quyền "{name}".', 'success')
    return redirect(url_for('admin.admin_permission', group_id=group.id))


@admin_bp.route('/permission-groups/<int:group_id>/rename', methods=['POST'])
@login_required
@require_admin
def permission_group_rename(group_id):
    if not current_user.is_master:
        abort(403)
    group = PermissionGroup.query.get_or_404(group_id)
    name = request.form.get('name', '').strip()
    if not name:
        flash('Tên nhóm quyền không được để trống.', 'danger')
    elif PermissionGroup.query.filter(PermissionGroup.name == name, PermissionGroup.id != group.id).first():
        flash('Tên nhóm quyền đã tồn tại.', 'danger')
    else:
        group.name = name
        db.session.commit()
        flash('Đã đổi tên nhóm quyền.', 'success')
    return redirect(url_for('admin.admin_permission'))


@admin_bp.route('/permission-groups/<int:group_id>/delete', methods=['POST'])
@login_required
@require_admin
def permission_group_delete(group_id):
    if not current_user.is_master:
        abort(403)
    group = PermissionGroup.query.get_or_404(group_id)
    member_count = group.members.count()
    if member_count > 0:
        flash(f'Không thể xoá — vẫn còn {member_count} tài khoản thuộc nhóm "{group.name}". '
              f'Hãy chuyển các tài khoản đó sang nhóm khác trước.', 'danger')
        return redirect(url_for('admin.admin_permission'))
    db.session.delete(group)
    db.session.commit()
    flash(f'Đã xoá nhóm quyền "{group.name}".', 'success')
    return redirect(url_for('admin.admin_permission'))


@admin_bp.route('/permission-groups/<int:group_id>/update', methods=['POST'])
@login_required
@require_admin
def permission_group_update(group_id):
    if not current_user.is_master:
        abort(403)
    group = PermissionGroup.query.get_or_404(group_id)
    full_access = request.form.get('full_access') == 'on'
    group.set_permissions(None if full_access else _parse_permission_matrix(request.form))
    db.session.commit()
    flash(f'Đã cập nhật quyền cho nhóm "{group.name}".', 'success')
    return redirect(url_for('admin.admin_permission', group_id=group.id))


@admin_bp.route('/accounts/add', methods=['POST'])
@login_required
@require_admin
def user_add():
    if not current_user.is_master:
        abort(403)

    full_name = request.form.get('full_name', '').strip()
    phone = request.form.get('phone', '').strip() or None
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    password_confirm = request.form.get('password_confirm', '').strip()
    gender = request.form.get('gender', '').strip() or None

    if not username:
        username = next_username(UserRole.ADMIN)

    dup_filters = [User.username == username]
    if phone:
        dup_filters.append(User.phone == phone)
    if User.query.filter(db.or_(*dup_filters)).first():
        flash('Số điện thoại hoặc tên đăng nhập đã tồn tại.', 'danger')
        return redirect(url_for('admin.users'))

    used_default_password = not (password or password_confirm)
    if used_default_password:
        password = DEFAULT_TEMP_PASSWORD
    else:
        if password != password_confirm:
            flash('Mật khẩu nhập lại không khớp.', 'danger')
            return redirect(url_for('admin.users'))
        if len(password) < 6:
            flash('Mật khẩu tối thiểu 6 ký tự.', 'danger')
            return redirect(url_for('admin.users'))

    user = User(full_name=full_name or username, username=username, phone=phone,
                role=UserRole.ADMIN, gender=gender, must_change_password=True)
    user.set_password(password)

    permission_group_id = request.form.get('permission_group_id', type=int)
    if permission_group_id:
        user.permission_group_id = permission_group_id

    db.session.add(user)
    # Need user.id before linking a Teacher row to it — same flush-then-link
    # pattern as teacher_add(). Lets this admin also act as a teacher and
    # switch between the two (see services/auth_context.py).
    db.session.flush()
    create_teacher_profile = request.form.get('create_teacher_profile') == '1'
    if create_teacher_profile:
        db.session.add(Teacher(user_id=user.id, is_staff=True))

    db.session.commit()
    if used_default_password:
        flash(f'Đã tạo tài khoản {username} với mật khẩu tạm: {DEFAULT_TEMP_PASSWORD} '
              f'— bắt buộc đổi mật khẩu ở lần đăng nhập đầu tiên.', 'success')
    else:
        flash(f'Đã tạo tài khoản {username} — bắt buộc đổi mật khẩu ở lần đăng nhập đầu tiên.', 'success')
    if create_teacher_profile:
        flash(f'Đã tạo hồ sơ Giáo viên liên kết — tài khoản này có thể chuyển đổi vai trò Admin/Giáo viên.', 'info')
    return redirect(url_for('admin.users'))


@admin_bp.route('/accounts/<int:user_id>/edit', methods=['POST'])
@login_required
@require_admin
def user_edit(user_id):
    user = User.query.get_or_404(user_id)
    if user.role != UserRole.ADMIN:
        abort(404)

    full_name = request.form.get('full_name', '').strip()
    phone = request.form.get('phone', '').strip() or None
    gender = request.form.get('gender', '').strip() or None

    if not full_name:
        flash('Vui lòng nhập họ tên.', 'danger')
        return redirect(url_for('admin.users'))

    if phone and User.query.filter(User.phone == phone, User.id != user.id).first():
        flash('Số điện thoại đã được sử dụng.', 'danger')
        return redirect(url_for('admin.users'))

    user.full_name = full_name
    user.phone = phone
    user.gender = gender
    db.session.commit()
    flash(f'Đã cập nhật thông tin {user.full_name}.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/accounts/<int:user_id>/delete', methods=['POST'])
@login_required
@require_admin
def user_delete(user_id):
    if not current_user.is_master:
        abort(403)
    user = User.query.get_or_404(user_id)
    if user.role != UserRole.ADMIN:
        abort(404)
    if user.id == current_user.id:
        flash('Không thể tự xoá tài khoản của chính mình.', 'danger')
        return redirect(url_for('admin.users'))
    user.is_deleted = True
    user.is_active = False
    db.session.commit()
    flash(f'Đã xoá tài khoản {user.full_name}.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/accounts/<int:user_id>/group', methods=['POST'])
@login_required
@require_admin
def user_group_update(user_id):
    if not current_user.is_master:
        abort(403)
    user = User.query.get_or_404(user_id)
    if user.role != UserRole.ADMIN:
        abort(404)
    if user.id == current_user.id:
        flash('Không thể tự sửa nhóm quyền của chính mình.', 'danger')
        return redirect(url_for('admin.users'))

    group_id = request.form.get('permission_group_id', type=int)
    group = PermissionGroup.query.get_or_404(group_id) if group_id else None
    user.permission_group = group
    db.session.commit()
    flash(f'Đã gán {user.full_name} vào nhóm quyền "{group.name if group else "—"}".', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/accounts/<int:user_id>/change-password', methods=['POST'])
@login_required
@require_admin
def user_reset_password(user_id):
    user = User.query.get_or_404(user_id)
    if user.role != UserRole.ADMIN:
        abort(404)
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
    if user.role != UserRole.ADMIN:
        abort(404)
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
    page = request.args.get('page', 1, type=int)
    pagination = paginate_list(items, page, per_page=50)
    return render_template('admin/courses.html', courses=pagination.items, pagination=pagination)


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
