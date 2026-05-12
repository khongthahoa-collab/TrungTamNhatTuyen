import os
from flask import Blueprint, render_template, redirect, url_for, flash, abort, send_from_directory, current_app, request
from flask_login import login_required, current_user
from datetime import date, timedelta
from extensions import db
from models import (Student, Attendance, Score, Reward, TuitionPayment, Schedule, Enrollment,
                    ClassDocument, ScoreType, ScoreSource, ContactInquiry)

parent_bp = Blueprint('parent', __name__)


def _get_student_or_403(student_id):
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

    student = children[0]
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

    current_month = today.month
    current_year = today.year
    unpaid = student.tuition_payments.filter_by(
        month=current_month, year=current_year, is_paid=False
    ).all()

    recent_att = (
        Attendance.query
        .filter_by(student_id=student.id)
        .order_by(Attendance.recorded_at.desc())
        .limit(5).all()
    )

    recent_scores = student.scores.order_by(Score.exam_date.desc(), Score.id.desc()).limit(5).all()

    pending_rewards = student.rewards.filter_by(is_confirmed=True).order_by(
        Reward.reward_date.desc()).limit(3).all()

    return render_template(
        'parent/dashboard.html',
        children=children,
        student=student,
        upcoming=upcoming,
        unpaid=unpaid,
        recent_att=recent_att,
        recent_scores=recent_scores,
        pending_rewards=pending_rewards,
        score_types=ScoreType.LABELS,
        today=today,
    )


@parent_bp.route('/students/<int:student_id>')
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
    recent_scores = student.scores.order_by(Score.exam_date.desc(), Score.id.desc()).limit(5).all()
    pending_rewards = student.rewards.filter_by(is_confirmed=True).order_by(
        Reward.reward_date.desc()).limit(3).all()

    return render_template(
        'parent/dashboard.html',
        children=children,
        student=student,
        upcoming=upcoming,
        unpaid=unpaid,
        recent_att=recent_att,
        recent_scores=recent_scores,
        pending_rewards=pending_rewards,
        score_types=ScoreType.LABELS,
        today=today,
    )


@parent_bp.route('/students/<int:student_id>/switch')
@login_required
def switch_student(student_id):
    if not current_user.is_parent:
        abort(403)
    _get_student_or_403(student_id)
    return redirect(url_for('parent.student_detail', student_id=student_id))


@parent_bp.route('/students/<int:student_id>/attendance')
@login_required
def attendance(student_id):
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)
    children = current_user.children.filter_by(is_active=True).all()

    records = (
        Attendance.query
        .filter_by(student_id=student.id)
        .order_by(Attendance.recorded_at.desc())
        .all()
    )
    return render_template('parent/attendance.html',
                           student=student, children=children, records=records)


@parent_bp.route('/students/<int:student_id>/scores')
@login_required
def scores(student_id):
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)
    children = current_user.children.filter_by(is_active=True).all()

    score_type_filter = request.args.get('score_type', '')

    q = student.scores
    if score_type_filter:
        q = q.filter_by(score_type=score_type_filter)
    all_scores = q.order_by(Score.exam_date.desc(), Score.id.desc()).all()

    by_class = {}
    for sc in all_scores:
        key = sc.class_.name
        by_class.setdefault(key, []).append(sc)

    active_classes = student.active_classes

    return render_template('parent/scores.html',
                           student=student, children=children,
                           by_class=by_class, all_scores=all_scores,
                           score_type_filter=score_type_filter,
                           score_types=ScoreType.LABELS,
                           active_classes=active_classes)


@parent_bp.route('/students/<int:student_id>/scores/report', methods=['POST'])
@login_required
def score_report(student_id):
    """Parent reports an external/school score for their child."""
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)

    class_id      = request.form.get('class_id', type=int)
    score_type    = request.form.get('score_type', '').strip()
    score_val_str = request.form.get('score_value', '').strip()
    max_score_str = request.form.get('max_score', '10').strip()
    exam_date_str = request.form.get('exam_date', '').strip()
    school_name   = request.form.get('school_name', '').strip()
    note          = request.form.get('note', '').strip()

    if not class_id or not score_type or not score_val_str:
        flash('Vui lòng điền đầy đủ thông tin bắt buộc.', 'danger')
        return redirect(url_for('parent.scores', student_id=student_id))

    enrolled_ids = {e.class_id for e in student.enrollments.filter_by(is_active=True).all()}
    if class_id not in enrolled_ids:
        abort(403)

    try:
        score_value = float(score_val_str)
        max_score   = float(max_score_str) if max_score_str else 10.0
    except ValueError:
        flash('Điểm số không hợp lệ.', 'danger')
        return redirect(url_for('parent.scores', student_id=student_id))

    exam_date = None
    if exam_date_str:
        try:
            exam_date = date.fromisoformat(exam_date_str)
        except ValueError:
            pass

    score = Score(
        student_id=student.id,
        class_id=class_id,
        score_source=ScoreSource.SCHOOL,
        score_type=score_type,
        score_value=score_value,
        max_score=max_score,
        exam_date=exam_date,
        school_name=school_name or student.current_school or '',
        note=note,
    )
    db.session.add(score)
    db.session.commit()
    flash('Đã báo cáo điểm số. Cảm ơn phụ huynh!', 'success')
    return redirect(url_for('parent.scores', student_id=student_id))


@parent_bp.route('/students/<int:student_id>/enroll', methods=['POST'])
@login_required
def enroll_request(student_id):
    """Parent submits a new class enrollment request."""
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)

    subject  = request.form.get('subject', '').strip()
    grade_lv = request.form.get('grade_level', '').strip()
    note_val = request.form.get('note', '').strip()

    if not subject:
        flash('Vui lòng nhập môn học muốn đăng ký.', 'danger')
        return redirect(url_for('parent.dashboard'))

    full_note = f'Phụ huynh đăng ký qua portal.'
    if grade_lv:
        full_note += f' Khối/Lớp: {grade_lv}.'
    if note_val:
        full_note += f' {note_val}'

    inquiry = ContactInquiry(
        student_name=student.full_name,
        grade=student.current_grade or grade_lv,
        subject=subject,
        school=student.current_school or '',
        parent_phone=current_user.phone,
        note=full_note,
        confirm_tuition=request.form.get('confirm_tuition') == '1',
    )
    db.session.add(inquiry)
    db.session.commit()
    flash('Đã gửi yêu cầu đăng ký lớp học! Cô Tuyền sẽ liên hệ lại sớm.', 'success')
    return redirect(url_for('parent.student_detail', student_id=student_id))


@parent_bp.route('/students/<int:student_id>/schedule')
@login_required
def schedule(student_id):
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)
    children = current_user.children.filter_by(is_active=True).all()

    today = date.today()
    end_date = today + timedelta(days=30)

    schedules = []
    for cl in student.active_classes:
        scheds = cl.schedules.filter(
            Schedule.date >= today,
            Schedule.date <= end_date,
            Schedule.is_cancelled == False,
        ).order_by(Schedule.date, Schedule.start_time).all()
        schedules.extend(scheds)
    schedules.sort(key=lambda s: (s.date, s.start_time))

    by_date = {}
    for s in schedules:
        by_date.setdefault(s.date, []).append(s)

    return render_template('parent/schedule.html',
                           student=student, children=children,
                           schedules=schedules, by_date=by_date,
                           today=today, tomorrow=today + timedelta(days=1))


@parent_bp.route('/students/<int:student_id>/rewards')
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


@parent_bp.route('/students/<int:student_id>/tuition')
@login_required
def tuition(student_id):
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)
    children = current_user.children.filter_by(is_active=True).all()

    today = date.today()
    records = student.tuition_payments.order_by(
        TuitionPayment.year.desc(), TuitionPayment.month.desc()
    ).all()

    # Nhóm theo tháng/năm để hiển thị tổng
    from collections import defaultdict
    by_month = defaultdict(list)
    for r in records:
        by_month[(r.year, r.month)].append(r)

    # Học phí tháng hiện tại
    current_records = by_month.get((today.year, today.month), [])
    current_total = sum(r.amount for r in current_records)
    current_unpaid = sum(r.amount for r in current_records if not r.is_paid)

    return render_template('parent/tuition.html',
                           student=student, children=children,
                           records=records, by_month=by_month,
                           current_records=current_records,
                           current_total=current_total,
                           current_unpaid=current_unpaid,
                           today=today)


@parent_bp.route('/students/<int:student_id>/documents')
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


@parent_bp.route('/documents/<int:doc_id>/download')
@login_required
def download_document(doc_id):
    doc = ClassDocument.query.get_or_404(doc_id)
    if not doc.is_active:
        abort(404)

    if current_user.is_admin or current_user.is_teacher:
        pass
    elif current_user.is_parent:
        enrolled = any(
            doc.class_.is_student_enrolled(child.id)
            for child in current_user.children.all()
        )
        if not enrolled:
            abort(403)
    else:
        abort(403)

    return send_from_directory(current_app.config['UPLOAD_FOLDER'],
                               doc.stored_filename,
                               as_attachment=True,
                               download_name=doc.original_filename)
