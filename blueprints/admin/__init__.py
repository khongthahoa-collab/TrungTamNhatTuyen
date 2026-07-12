from flask import Blueprint, render_template, abort, request
from flask_login import login_required, current_user
from functools import wraps

admin_bp = Blueprint('admin', __name__)


def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def require_admin_or_teacher(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not (current_user.is_admin or current_user.is_teacher):
            abort(403)
        return f(*args, **kwargs)
    return decorated


@admin_bp.before_request
def check_module_permission():
    """Per-account feature restriction, on top of the role-based decorators above."""
    if not current_user.is_authenticated or not (current_user.is_admin or current_user.is_teacher):
        return
    from blueprints.permissions import ADMIN_ENDPOINT_MODULES
    endpoint = (request.endpoint or '').split('.')[-1]
    module = ADMIN_ENDPOINT_MODULES.get(endpoint)
    if module and not current_user.can_access(module):
        abort(403)


# Import sub-modules to register routes
from blueprints.admin import students, classes, academic, finance, rewards, documents, reports, settings, teachers, rooms, schools, attendance, exams  # noqa


@admin_bp.route('/')
@login_required
@require_admin
def dashboard():
    from datetime import date
    from models import Student, Teacher, Class, TuitionPayment, Schedule, Reward, ZaloLog

    today = date.today()
    stats = {
        'students': Student.query.filter_by(is_active=True, is_deleted=False).count(),
        'teachers': Teacher.query.count(),
        'classes': Class.query.filter_by(is_active=True).count(),
        'unpaid_tuition': TuitionPayment.query.filter_by(
            is_paid=False, month=today.month, year=today.year
        ).count(),
        'pending_rewards': Reward.query.filter_by(is_suggested=True, is_confirmed=False).count(),
        'today_schedules': Schedule.query.filter_by(
            date=today, is_cancelled=False
        ).count(),
        'zalo_failed': ZaloLog.query.filter_by(status='failed').count(),
    }

    # Today's schedule detail
    today_classes = Schedule.query.filter_by(
        date=today, is_cancelled=False
    ).order_by(Schedule.start_time).all()

    # Recent Zalo logs
    recent_zalo = ZaloLog.query.order_by(ZaloLog.sent_at.desc()).limit(5).all()

    return render_template('admin/dashboard.html',
                           stats=stats,
                           today_classes=today_classes,
                           recent_zalo=recent_zalo,
                           today=today)
