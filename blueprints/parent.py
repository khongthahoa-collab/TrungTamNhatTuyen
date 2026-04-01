import os
from flask import Blueprint, render_template, redirect, url_for, flash, abort, send_from_directory, current_app
from flask_login import login_required, current_user
from datetime import date, timedelta
from models import Student, Attendance, Score, Reward, TuitionPayment, Schedule, Enrollment, ClassDocument

parent_bp = Blueprint('parent', __name__)


def _get_student_or_403(student_id):
    """Lấy học sinh và kiểm tra phụ huynh có quyền xem không."""
    student = Student.query.get_or_404(student_id)
    kids = list(current_user.children.all())
    if student not in kids:
        abort(403)
    return student


@parent_bp.route('/')
@login_required
def dashboard():
    if not current_user.is_parent:
        abort(403)
    children = current_user.children.filter_by(is_active=True).all()
    if not children:
        return render_template('parent/no_children.html')

    # Default: first child
    student = children[0]
    today = date.today()

    # Upcoming schedules (this week)
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    upcoming = []
    for cl in student.active_classes:
        scheds = cl.schedules.filter(
            Schedule.date >= today,
            Schedule.date <= sunday,
            Schedule.is_cancelled == False,
        ).order_by(Schedule.date, Schedule.start_time).all()
        upcoming.extend(scheds)
    upcoming.sort(key=lambda s: (s.date, s.start_time))

    # Unpaid tuition
    current_month = today.month
    current_year = today.year
    unpaid = student.tuition_payments.filter_by(
        month=current_month, year=current_year, is_paid=False
    ).all()

    # Recent attendance (last 10)
    recent_att = (
        Attendance.query
        .filter_by(student_id=student.id)
        .order_by(Attendance.recorded_at.desc())
        .limit(5).all()
    )

    # Pending rewards
    pending_rewards = student.rewards.filter_by(is_confirmed=True).order_by(
        Reward.reward_date.desc()).limit(3).all()

    return render_template(
        'parent/dashboard.html',
        children=children,
        student=student,
        upcoming=upcoming,
        unpaid=unpaid,
        recent_att=recent_att,
        pending_rewards=pending_rewards,
        today=today,
    )


@parent_bp.route('/hoc-sinh/<int:student_id>')
@login_required
def student_detail(student_id):
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)
    children = current_user.children.filter_by(is_active=True).all()
    today = date.today()

    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    upcoming = []
    for cl in student.active_classes:
        scheds = cl.schedules.filter(
            Schedule.date >= today,
            Schedule.date <= sunday,
            Schedule.is_cancelled == False,
        ).order_by(Schedule.date, Schedule.start_time).all()
        upcoming.extend(scheds)
    upcoming.sort(key=lambda s: (s.date, s.start_time))

    unpaid = student.tuition_payments.filter_by(is_paid=False).all()
    recent_att = student.attendances.order_by(Attendance.recorded_at.desc()).limit(5).all()
    pending_rewards = student.rewards.filter_by(is_confirmed=True).order_by(
        Reward.reward_date.desc()).limit(3).all()

    return render_template(
        'parent/dashboard.html',
        children=children,
        student=student,
        upcoming=upcoming,
        unpaid=unpaid,
        recent_att=recent_att,
        pending_rewards=pending_rewards,
        today=today,
    )


@parent_bp.route('/hoc-sinh/<int:student_id>/diem-danh')
@login_required
def attendance(student_id):
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)
    children = current_user.children.filter_by(is_active=True).all()

    page = 1
    records = (
        Attendance.query
        .filter_by(student_id=student.id)
        .order_by(Attendance.recorded_at.desc())
        .all()
    )
    return render_template('parent/attendance.html',
                           student=student, children=children, records=records)


@parent_bp.route('/hoc-sinh/<int:student_id>/diem-so')
@login_required
def scores(student_id):
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)
    children = current_user.children.filter_by(is_active=True).all()

    all_scores = student.scores.order_by(Score.exam_date.desc()).all()

    # Group by class
    by_class = {}
    for sc in all_scores:
        key = sc.class_.name
        by_class.setdefault(key, []).append(sc)

    return render_template('parent/scores.html',
                           student=student, children=children, by_class=by_class)


@parent_bp.route('/hoc-sinh/<int:student_id>/lich-hoc')
@login_required
def schedule(student_id):
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)
    children = current_user.children.filter_by(is_active=True).all()
    
    today = date.today()
    tomorrow = today + timedelta(days=1)
    # Get all schedules for this student's classes (next 30 days)
    end_date = today + timedelta(days=30)
    
    schedules = []
    for cl in student.active_classes:
        scheds = cl.schedules.filter(
            Schedule.date >= today,
            Schedule.date <= end_date,
            Schedule.is_cancelled == False,
        ).order_by(Schedule.date, Schedule.start_time).all()
        schedules.extend(scheds)
    
    # Sort by date and time
    schedules.sort(key=lambda s: (s.date, s.start_time))
    
    # Group by date
    by_date = {}
    for s in schedules:
        if s.date not in by_date:
            by_date[s.date] = []
        by_date[s.date].append(s)
    
    return render_template('parent/schedule.html',
                           student=student, children=children, 
                           schedules=schedules, by_date=by_date, today=today, tomorrow=tomorrow)


@parent_bp.route('/hoc-sinh/<int:student_id>/khen-thuong')
@login_required
def rewards(student_id):
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)
    children = current_user.children.filter_by(is_active=True).all()

    records = student.rewards.filter_by(is_confirmed=True).order_by(
        Reward.reward_date.desc()).all()
    total = sum(r.amount for r in records)
    return render_template('parent/rewards.html',
                           student=student, children=children, records=records, total=total)


@parent_bp.route('/hoc-sinh/<int:student_id>/hoc-phi')
@login_required
def tuition(student_id):
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)
    children = current_user.children.filter_by(is_active=True).all()

    records = student.tuition_payments.order_by(
        TuitionPayment.year.desc(), TuitionPayment.month.desc()
    ).all()
    return render_template('parent/tuition.html',
                           student=student, children=children, records=records)


@parent_bp.route('/hoc-sinh/<int:student_id>/tai-lieu')
@login_required
def documents(student_id):
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)
    children = current_user.children.filter_by(is_active=True).all()

    docs_by_class = {}
    for cl in student.active_classes:
        docs = cl.documents.filter_by(is_active=True).order_by(
            ClassDocument.uploaded_at.desc()
        ).all()
        if docs:
            docs_by_class[cl] = docs

    return render_template('parent/documents.html',
                           student=student, children=children, docs_by_class=docs_by_class)


@parent_bp.route('/tai-lieu/<int:doc_id>/tai')
@login_required
def download_document(doc_id):
    """Download file — chỉ học sinh thuộc lớp mới được tải."""
    doc = ClassDocument.query.get_or_404(doc_id)
    if not doc.is_active:
        abort(404)

    # Check authorization
    if current_user.is_admin or current_user.is_teacher:
        pass  # OK
    elif current_user.is_parent:
        # Check if any child is enrolled
        enrolled = False
        for child in current_user.children.all():
            if doc.class_.is_student_enrolled(child.id):
                enrolled = True
                break
        if not enrolled:
            abort(403)
    else:
        abort(403)

    upload_dir = current_app.config['UPLOAD_FOLDER']
    return send_from_directory(upload_dir, doc.stored_filename,
                               as_attachment=True,
                               download_name=doc.original_filename)
