import os
import json
import random
import re
from flask import Blueprint, render_template, redirect, url_for, flash, abort, send_from_directory, current_app, request
from flask_login import login_required, current_user
from datetime import date, datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from extensions import db
from models import (Student, Attendance, Score, Reward, TuitionPayment, Schedule, Enrollment,
                    ClassDocument, ScoreType, ScoreSource, ContactInquiry, Exam, ExamAttempt, ExamLog,
                    Class, User, UserRole, Notification)

parent_bp = Blueprint('parent', __name__)
CHEAT_LIMIT = 3
ERROR_ID_PATTERN = re.compile(r'\[(\*?)([A-F]):([^\]]*)\]')


def _get_student_or_403(student_id):
    student = Student.query.get_or_404(student_id)
    kids = list(current_user.children.all())
    if student not in kids:
        abort(403)
    return student


def _upcoming_schedules(student, start, end):
    """Schedules across all of a student's active classes within [start, end],
    already ordered — one batched query instead of one query per class."""
    class_ids = [c.id for c in student.active_classes]
    if not class_ids:
        return []
    return (Schedule.query.options(joinedload(Schedule.class_)).filter(
                Schedule.class_id.in_(class_ids),
                Schedule.date >= start,
                Schedule.date <= end,
                Schedule.is_cancelled == False,
            ).order_by(Schedule.date, Schedule.start_time).all())


@parent_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if not current_user.is_parent:
        abort(403)

    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not current_user.check_password(current_password):
            flash('Mật khẩu hiện tại không đúng.', 'danger')
        elif len(new_password) < 6:
            flash('Mật khẩu mới phải có ít nhất 6 ký tự.', 'danger')
        elif new_password != confirm_password:
            flash('Mật khẩu xác nhận không khớp.', 'danger')
        else:
            current_user.set_password(new_password)
            db.session.commit()
            flash('Đã đổi mật khẩu thành công.', 'success')
            return redirect(url_for('parent.dashboard'))

    children = current_user.children.filter_by(is_active=True).all()
    return render_template('parent/change_password.html', children=children,
                           student=children[0] if children else None)


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
    upcoming = _upcoming_schedules(student, today, sunday)

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


@parent_bp.route('/notifications')
@login_required
def notifications():
    if not current_user.is_parent:
        abort(403)
    page = request.args.get('page', 1, type=int)
    pagination = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .paginate(page=page, per_page=50, error_out=False)
    )
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return render_template('parent/notifications.html', notifs=pagination.items, pagination=pagination)


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
    upcoming = _upcoming_schedules(student, today, sunday)

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

    page = request.args.get('page', 1, type=int)
    base_query = Attendance.query.filter_by(student_id=student.id)

    # Status counts via SQL over the full history, not just the current
    # page — the template's summary cards need true totals.
    status_counts = dict(
        db.session.query(Attendance.status, func.count(Attendance.id))
        .filter_by(student_id=student.id)
        .group_by(Attendance.status)
        .all()
    )

    pagination = base_query.order_by(Attendance.recorded_at.desc()) \
        .paginate(page=page, per_page=50, error_out=False)
    records = pagination.items
    return render_template('parent/attendance.html',
                           student=student, children=children, records=records, pagination=pagination,
                           present_count=status_counts.get('present', 0),
                           absent_count=status_counts.get('absent', 0),
                           late_count=status_counts.get('late', 0),
                           excused_count=status_counts.get('excused', 0))


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

    schedules = _upcoming_schedules(student, today, end_date)

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

    page = request.args.get('page', 1, type=int)
    base_query = student.rewards.filter_by(is_confirmed=True)
    total = base_query.with_entities(func.coalesce(func.sum(Reward.amount), 0)).scalar()
    pagination = base_query.order_by(Reward.reward_date.desc()) \
        .paginate(page=page, per_page=50, error_out=False)
    records = pagination.items
    return render_template('parent/rewards.html',
                           student=student, children=children, records=records,
                           pagination=pagination, total=total)


@parent_bp.route('/students/<int:student_id>/tuition')
@login_required
def tuition(student_id):
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)
    children = current_user.children.filter_by(is_active=True).all()

    today = date.today()
    page = request.args.get('page', 1, type=int)

    # Current month's status — fetched directly (not from the paginated
    # history below), so it's always correct regardless of which page of
    # older history the parent happens to be viewing.
    current_records = student.tuition_payments.filter_by(year=today.year, month=today.month).all()
    current_total = sum(r.amount for r in current_records)
    current_unpaid = sum(r.amount for r in current_records if not r.is_paid)

    # Full-history unpaid warning banner — true total across every month,
    # not just whatever's on the current page.
    unpaid_count, unpaid_total = student.tuition_payments.filter_by(is_paid=False).with_entities(
        func.count(TuitionPayment.id), func.coalesce(func.sum(TuitionPayment.amount), 0)
    ).first()

    pagination = student.tuition_payments.order_by(
        TuitionPayment.year.desc(), TuitionPayment.month.desc()
    ).paginate(page=page, per_page=50, error_out=False)
    records = pagination.items

    # Nhóm theo tháng/năm để hiển thị tổng (chỉ trong trang hiện tại)
    from collections import defaultdict
    by_month = defaultdict(list)
    for r in records:
        by_month[(r.year, r.month)].append(r)

    return render_template('parent/tuition.html',
                           student=student, children=children,
                           records=records, by_month=by_month, pagination=pagination,
                           current_records=current_records,
                           current_total=current_total,
                           current_unpaid=current_unpaid,
                           unpaid_count=unpaid_count,
                           unpaid_total=unpaid_total,
                           today=today)


@parent_bp.route('/students/<int:student_id>/documents')
@login_required
def documents(student_id):
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)
    children = current_user.children.filter_by(is_active=True).all()

    classes = student.active_classes
    docs_by_class = {}
    if classes:
        classes_by_id = {c.id: c for c in classes}
        all_docs = (ClassDocument.query
                   .filter(ClassDocument.class_id.in_(classes_by_id.keys()), ClassDocument.is_active == True)
                   .order_by(ClassDocument.uploaded_at.desc()).all())
        for doc in all_docs:
            docs_by_class.setdefault(classes_by_id[doc.class_id], []).append(doc)

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


# ============================================================
# Exam / online test taking
# ============================================================

def _exams_for_student(student):
    """Non-draft exams assigned to one of the student's active classes, or open to everyone."""
    class_ids = {e.class_id for e in student.enrollments.filter_by(is_active=True).all()}
    all_exams = Exam.query.filter_by(is_draft=False).order_by(Exam.created_at.desc()).all()
    return [exam for exam in all_exams if not exam.class_list or class_ids & set(exam.class_list)]


def _build_attempt_order(exam):
    """Per group: shuffle question order, and (for mcq/true_false) shuffle option/statement order.
    Groups themselves always stay in their authored order (Phần 1, Phần 2, ...)."""
    groups_order = []
    for group in exam.question_groups:
        questions = group.get('questions', [])
        q_order = list(range(len(questions)))
        if exam.shuffle_questions:
            random.shuffle(q_order)
        opt_orders = {}
        if exam.shuffle_answers and group.get('type') in ('mcq', 'true_false'):
            key = 'options' if group.get('type') == 'mcq' else 'statements'
            for qi, q in enumerate(questions):
                opt_order = list(range(len(q.get(key, []))))
                random.shuffle(opt_order)
                opt_orders[str(qi)] = opt_order
        groups_order.append({'q_order': q_order, 'opt_orders': opt_orders})
    return {'groups': groups_order}


def _ordered_questions(exam, order_data):
    """Build the grouped list of questions to display, in shuffled order, without leaking correct answers."""
    groups_order = order_data.get('groups') or []
    display_groups = []
    for gi, group in enumerate(exam.question_groups):
        go = groups_order[gi] if gi < len(groups_order) else {}
        gtype = group.get('type')
        questions = group.get('questions', [])
        q_order = go.get('q_order') or list(range(len(questions)))
        opt_orders = go.get('opt_orders') or {}
        display_questions = []
        for position, orig_qi in enumerate(q_order, start=1):
            if orig_qi >= len(questions):
                continue
            q = questions[orig_qi]
            item = {'position': position, 'text': q.get('text', '')}
            if gtype == 'mcq':
                opt_order = opt_orders.get(str(orig_qi)) or list(range(len(q.get('options', []))))
                item['options'] = [q['options'][oi] for oi in opt_order if oi < len(q.get('options', []))]
            elif gtype == 'true_false':
                opt_order = opt_orders.get(str(orig_qi)) or list(range(len(q.get('statements', []))))
                statements = q.get('statements', [])
                item['statements'] = [statements[oi]['text'] for oi in opt_order if oi < len(statements)]
            elif gtype == 'error_id':
                item['labels'] = [label for _star, label, _seg in ERROR_ID_PATTERN.findall(q.get('text', ''))]
            display_questions.append(item)
        display_groups.append({
            'index': gi, 'title': group.get('title', ''), 'type': gtype,
            'instruction': group.get('instruction', ''), 'questions': display_questions,
        })
    return display_groups


def _grade_attempt(exam, attempt, form):
    """Type-aware grading. Each question contributes equal weight to the overall score;
    a true_false question earns the fraction of its sub-statements answered correctly (partial credit)."""
    order_data = attempt.order_data
    groups_order = order_data.get('groups') or []
    breakdown = []
    normalized = {}
    total_earned = 0.0
    total_weight = 0

    for gi, group in enumerate(exam.question_groups):
        go = groups_order[gi] if gi < len(groups_order) else {}
        gtype = group.get('type')
        questions = group.get('questions', [])
        q_order = go.get('q_order') or list(range(len(questions)))
        opt_orders = go.get('opt_orders') or {}
        group_earned = 0.0
        group_total = 0

        for position, orig_qi in enumerate(q_order, start=1):
            if orig_qi >= len(questions):
                continue
            q = questions[orig_qi]
            field = f'g{gi}_q{position}'
            group_total += 1
            earned = 0.0

            if gtype == 'mcq':
                opt_order = opt_orders.get(str(orig_qi)) or list(range(len(q.get('options', []))))
                raw_choice = form.get(field, '').strip()
                normalized[field] = raw_choice
                if raw_choice:
                    try:
                        chosen_orig = opt_order[int(raw_choice) - 1]
                        earned = 1.0 if chosen_orig == q.get('correct_index') else 0.0
                    except (ValueError, IndexError):
                        pass
            elif gtype == 'true_false':
                statements = q.get('statements', [])
                opt_order = opt_orders.get(str(orig_qi)) or list(range(len(statements)))
                correct_subs = 0
                chosen = {}
                for sub_pos, orig_si in enumerate(opt_order, start=1):
                    raw_val = form.get(f'{field}_{sub_pos}', '').strip()
                    chosen[str(sub_pos)] = raw_val
                    if orig_si < len(statements) and raw_val in ('0', '1'):
                        if (raw_val == '1') == bool(statements[orig_si].get('correct')):
                            correct_subs += 1
                normalized[field] = chosen
                earned = (correct_subs / len(statements)) if statements else 0.0
            elif gtype == 'short_answer':
                raw_answer = form.get(field, '').strip()
                normalized[field] = raw_answer
                earned = 1.0 if raw_answer and raw_answer in q.get('accepted_answers', []) else 0.0
            elif gtype == 'error_id':
                raw_choice = form.get(field, '').strip().upper()
                normalized[field] = raw_choice
                earned = 1.0 if raw_choice and raw_choice == q.get('correct_label') else 0.0

            group_earned += earned
            total_earned += earned

        total_weight += group_total
        breakdown.append({'title': group.get('title', ''), 'type': gtype,
                          'earned': round(group_earned, 2), 'total': group_total})

    percent = int(round(total_earned / total_weight * 100)) if total_weight else 0
    score_10 = round(total_earned / total_weight * 10, 1) if total_weight else 0
    result = {'earned': round(total_earned, 2), 'total': total_weight, 'percent': percent,
             'score_10': score_10, 'breakdown': breakdown}
    return normalized, result


@parent_bp.route('/students/<int:student_id>/exams')
@login_required
def exams(student_id):
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)
    children = current_user.children.filter_by(is_active=True).all()

    rows = []
    for exam in _exams_for_student(student):
        attempts = ExamAttempt.query.filter_by(exam_id=exam.id, student_id=student.id).order_by(
            ExamAttempt.started_at.desc()).all()
        submitted = [a for a in attempts if a.status == 'submitted']
        in_progress = next((a for a in attempts if a.status == 'in_progress'), None)
        if exam.is_unlimited_attempts:
            can_take = True
        else:
            can_take = len(submitted) < exam.allow_attempts or in_progress is not None
        rows.append({
            'exam': exam,
            'attempts_used': len(submitted),
            'last_attempt': submitted[0] if submitted else None,
            'in_progress': in_progress is not None,
            'can_take': can_take,
            'is_open': exam.is_open_now(),
        })

    return render_template('exams/parent_list.html', rows=rows, student=student, children=children)


@parent_bp.route('/students/<int:student_id>/exams/<int:exam_id>')
@login_required
def exam_take(student_id, exam_id):
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)
    children = current_user.children.filter_by(is_active=True).all()
    exam = Exam.query.get_or_404(exam_id)

    if exam.is_draft or exam not in _exams_for_student(student):
        abort(404)

    last_attempt = ExamAttempt.query.filter_by(exam_id=exam.id, student_id=student.id).order_by(
        ExamAttempt.started_at.desc()).first()

    if last_attempt and last_attempt.status == 'in_progress':
        elapsed = (datetime.utcnow() - last_attempt.started_at).total_seconds()
        if elapsed >= exam.duration_minutes * 60:
            # Time already ran out while the student was away — finalize with whatever was given (nothing).
            normalized, result = _grade_attempt(exam, last_attempt, {})
            last_attempt.submitted_at = datetime.utcnow()
            last_attempt.status = 'submitted'
            last_attempt.score = result['percent']
            last_attempt.total_questions = result['total']
            last_attempt.answers_json = json.dumps(normalized)
            last_attempt.result_json = json.dumps(result)
            db.session.commit()
            flash('Đã hết thời gian làm bài, hệ thống tự động nộp bài.', 'warning')
            return redirect(url_for('parent.exam_result', student_id=student.id, exam_id=exam.id))
        attempt = last_attempt
    else:
        submitted_count = ExamAttempt.query.filter_by(
            exam_id=exam.id, student_id=student.id, status='submitted').count()
        if not exam.is_unlimited_attempts and submitted_count >= exam.allow_attempts:
            flash('Bạn đã hết lượt làm bài này.', 'warning')
            return redirect(url_for('parent.exam_result', student_id=student.id, exam_id=exam.id))
        if not exam.is_open_now():
            flash('Đề thi hiện chưa mở hoặc đã đóng theo thời gian quy định.', 'warning')
            return redirect(url_for('parent.exams', student_id=student.id))

        attempt = ExamAttempt(
            exam_id=exam.id,
            user_id=current_user.id,
            student_id=student.id,
            status='in_progress',
            total_questions=exam.total_question_count,
            order_json=json.dumps(_build_attempt_order(exam)),
        )
        db.session.add(attempt)
        db.session.add(ExamLog(user_id=current_user.id, action='start_exam_attempt', target_type='exam',
                               target_id=exam.id, detail=f'{student.full_name} bắt đầu làm "{exam.title}"'))
        db.session.commit()

    questions = _ordered_questions(exam, attempt.order_data)
    remaining_seconds = max(0, int(exam.duration_minutes * 60 - (datetime.utcnow() - attempt.started_at).total_seconds()))

    return render_template('exams/take.html', exam=exam, attempt=attempt, student=student, children=children,
                           questions=questions, remaining_seconds=remaining_seconds, cheat_limit=CHEAT_LIMIT)


def _notify_cheat_flag(exam, student, attempt):
    """Notify admins and the exam's creator/primary teacher of the assigned classes
    that a student was flagged for leaving the exam screen too many times."""
    recipient_ids = {u.id for u in User.query.filter_by(role=UserRole.ADMIN).all()}
    if exam.created_by:
        recipient_ids.add(exam.created_by)
    for class_id in exam.class_list:
        cls = Class.query.get(class_id)
        if cls and cls.primary_teacher and cls.primary_teacher.user_id:
            recipient_ids.add(cls.primary_teacher.user_id)

    title = f'Cảnh báo gian lận: {student.full_name}'
    body = (f'Học sinh {student.full_name} đã rời khỏi màn hình thi quá {CHEAT_LIMIT} lần '
            f'khi làm đề "{exam.title}" ({attempt.cheat_count} lần).')
    link = url_for('admin.exams_results', exam_id=exam.id)
    for uid in recipient_ids:
        db.session.add(Notification(user_id=uid, title=title, body=body, notif_type='warning', link=link))


@parent_bp.route('/students/<int:student_id>/exams/<int:exam_id>/submit', methods=['POST'])
@login_required
def exam_submit(student_id, exam_id):
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)
    exam = Exam.query.get_or_404(exam_id)

    attempt = ExamAttempt.query.filter_by(exam_id=exam.id, student_id=student.id, status='in_progress').order_by(
        ExamAttempt.started_at.desc()).first()
    if not attempt:
        return redirect(url_for('parent.exam_result', student_id=student.id, exam_id=exam.id))

    normalized, result = _grade_attempt(exam, attempt, request.form)
    try:
        cheat_count = int(request.form.get('cheat_count', 0))
    except (ValueError, TypeError):
        cheat_count = 0
    was_flagged = cheat_count > CHEAT_LIMIT

    attempt.submitted_at = datetime.utcnow()
    attempt.status = 'submitted'
    attempt.score = result['percent']
    attempt.total_questions = result['total']
    attempt.cheat_count = cheat_count
    attempt.was_flagged = was_flagged
    attempt.answers_json = json.dumps(normalized)
    attempt.result_json = json.dumps(result)

    log_detail = f'{student.full_name} nộp bài "{exam.title}" — {result["earned"]}/{result["total"]} điểm {result["score_10"]}/10'
    if was_flagged:
        log_detail += f' (cảnh báo gian lận, {cheat_count} lần)'
        _notify_cheat_flag(exam, student, attempt)
    db.session.add(ExamLog(user_id=current_user.id, action='submit_exam_attempt', target_type='exam',
                           target_id=exam.id, detail=log_detail))
    db.session.commit()

    return redirect(url_for('parent.exam_result', student_id=student.id, exam_id=exam.id))


@parent_bp.route('/students/<int:student_id>/exams/<int:exam_id>/result')
@login_required
def exam_result(student_id, exam_id):
    if not current_user.is_parent:
        abort(403)
    student = _get_student_or_403(student_id)
    children = current_user.children.filter_by(is_active=True).all()
    exam = Exam.query.get_or_404(exam_id)

    attempt = ExamAttempt.query.filter_by(exam_id=exam.id, student_id=student.id, status='submitted').order_by(
        ExamAttempt.started_at.desc()).first()
    if not attempt:
        flash('Bạn chưa hoàn thành bài thi này.', 'warning')
        return redirect(url_for('parent.exams', student_id=student.id))

    submitted_count = ExamAttempt.query.filter_by(exam_id=exam.id, student_id=student.id, status='submitted').count()
    can_retake = exam.is_unlimited_attempts or submitted_count < exam.allow_attempts

    return render_template('exams/result.html', exam=exam, attempt=attempt, student=student, children=children,
                           can_retake=can_retake)
