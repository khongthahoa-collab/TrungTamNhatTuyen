from flask import g
from extensions import db
from models import Notification
from blueprints.api import api_bp, api_ok, api_error, api_login_required, get_page_args, pagination_meta


@api_bp.route('/notifications', methods=['GET'])
@api_login_required
def notifications_list():
    """Always scoped to the caller's own notifications — no module gate
    needed (matches CORE_MODULES in blueprints/permissions.py, which
    every authenticated account can always reach)."""
    query = Notification.query.filter_by(user_id=g.api_user.id)
    page, per_page = get_page_args()
    pagination = query.order_by(Notification.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return api_ok([n.to_dict() for n in pagination.items], meta=pagination_meta(pagination))


@api_bp.route('/notifications/<int:notification_id>/read', methods=['POST'])
@api_login_required
def notifications_mark_read(notification_id):
    notification = Notification.query.filter_by(id=notification_id, user_id=g.api_user.id).first()
    if not notification:
        return api_error('Không tìm thấy thông báo.', 404, code='not_found')
    notification.is_read = True
    db.session.commit()
    return api_ok(notification.to_dict())
