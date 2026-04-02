from flask import Blueprint, render_template, abort
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


# Import sub-modules to register routes
from blueprints.admin import students, classes, academic, finance, rewards, documents, reports, settings, teachers, rooms, schools  # noqa


@admin_bp.route('/')
@login_required
@require_admin
def dashboard():
    from datetime import date
    from models import Student, Teacher, Class, TuitionPayment, Schedule, Reward, ZaloLog

    today = date.today()
    stats = {
        'students': Student.query.filter_by(is_active=True).count(),
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
