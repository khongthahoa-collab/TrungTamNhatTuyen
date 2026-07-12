from flask import render_template
from flask_login import login_required
from models import Teacher, User, Schedule
from blueprints.admin import admin_bp, require_admin


@admin_bp.route('/teachers')
@login_required
@require_admin
def teachers():
    teachers = (
        Teacher.query
        .join(Teacher.user)
        .filter(User.is_deleted == False)
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
