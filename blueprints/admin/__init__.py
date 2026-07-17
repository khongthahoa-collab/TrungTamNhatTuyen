from flask import Blueprint, render_template, abort, request
from flask_login import login_required, current_user
from functools import wraps
from services.auth_context import get_active_role

admin_bp = Blueprint('admin', __name__)


def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        # A dual-role account (admin + linked Teacher profile) must have
        # actively switched into the admin context — real is_admin alone
        # isn't enough once that account can also act as a teacher.
        if get_active_role(current_user) != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated


def require_admin_or_teacher(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not (current_user.is_admin or current_user.is_teacher):
            abort(403)
        if get_active_role(current_user) not in ('admin', 'teacher'):
            abort(403)
        return f(*args, **kwargs)
    return decorated


def require_master(f):
    """Gate for functionality only the admin-master account may use at all
    (e.g. teacher accounts, salary) — stronger than the read/write/deny matrix,
    which delegated admins can never override for these modules."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin or not current_user.is_master:
            abort(403)
        if get_active_role(current_user) != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated


@admin_bp.before_request
def check_module_permission():
    """Per-account feature restriction, on top of the role-based decorators above.
    GET/HEAD only needs 'read'; a mutating request needs 'write'."""
    if not current_user.is_authenticated or not (current_user.is_admin or current_user.is_teacher):
        return
    from blueprints.permissions import ADMIN_ENDPOINT_MODULES
    endpoint = (request.endpoint or '').split('.')[-1]
    module = ADMIN_ENDPOINT_MODULES.get(endpoint)
    if not module:
        return
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        if not current_user.can_write(module):
            abort(403)
    elif not current_user.can_access(module):
        abort(403)


# Import sub-modules to register routes
from blueprints.admin import dashboard, notifications, students, classes, academic, finance, rewards, documents, reports, settings, teachers, rooms, schools, attendance, exams, leave_requests  # noqa
