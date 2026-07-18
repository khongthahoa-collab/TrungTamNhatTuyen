from flask import render_template, request, jsonify, redirect, url_for
from flask_login import login_required, current_user
from extensions import db
from models import Notification
from blueprints.admin import admin_bp, require_admin


@admin_bp.route('/notifications')
@login_required
@require_admin
def notifications():
    """Admin notifications page — mirrors teacher/notifications.html's layout.
    Đánh dấu đã đọc là hành động chủ động ("Đánh dấu đã đọc" / "Đã đọc tất
    cả") — không còn tự động đánh dấu hết khi chỉ mở trang xem qua."""
    page = request.args.get('page', 1, type=int)
    pagination = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .paginate(page=page, per_page=50, error_out=False)
    )
    return render_template('admin/notifications.html', notifs=pagination.items, pagination=pagination)


@admin_bp.route('/notifications/<int:notif_id>/read', methods=['POST'])
@login_required
@require_admin
def notification_mark_read(notif_id):
    n = Notification.query.filter_by(id=notif_id, user_id=current_user.id).first_or_404()
    n.is_read = True
    db.session.commit()
    return jsonify({'success': True})


@admin_bp.route('/notifications/read-all', methods=['POST'])
@login_required
@require_admin
def notifications_read_all():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return redirect(url_for('admin.notifications'))
