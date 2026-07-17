from flask import render_template, request
from flask_login import login_required, current_user
from extensions import db
from models import Notification
from blueprints.admin import admin_bp, require_admin


@admin_bp.route('/notifications')
@login_required
@require_admin
def notifications():
    """Admin notifications page — mirrors teacher/notifications.html's
    layout and "opening the page marks everything read" behavior."""
    page = request.args.get('page', 1, type=int)
    pagination = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .paginate(page=page, per_page=50, error_out=False)
    )
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return render_template('admin/notifications.html', notifs=pagination.items, pagination=pagination)
