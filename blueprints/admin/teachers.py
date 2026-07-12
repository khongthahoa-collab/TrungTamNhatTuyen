from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required
from extensions import db
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


@admin_bp.route('/teachers/<int:teacher_id>/update', methods=['POST'])
@login_required
@require_admin
def teacher_update_fields(teacher_id):
    """Inline edit from the teachers page: salary + classification only.
    Everything else about the account is edited on /admin/accounts."""
    teacher = Teacher.query.get_or_404(teacher_id)
    teacher.is_staff = request.form.get('is_staff') == '1'
    teacher.base_salary = request.form.get('base_salary', 0, type=float)
    db.session.commit()
    flash(f'Đã cập nhật {teacher.full_name}.', 'success')
    return redirect(url_for('admin.teachers'))
