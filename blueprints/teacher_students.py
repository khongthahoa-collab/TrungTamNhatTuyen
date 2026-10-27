"""Read-only learning overview; never pass student/profile ORM objects to views."""
from datetime import date
from types import SimpleNamespace

from flask import abort, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from blueprints.teacher import teacher_bp, require_teacher
from blueprints.exams_shared import exam_is_assigned_to_student
from extensions import db
from models import Attendance, AttendanceStatus, Class, Enrollment, Exam, ExamAttempt, Homework, HomeworkRecord, Schedule, Score, ScoreType, Student
from services.attendance_warnings import get_absence_warnings


def _classes():
    teacher = current_user.teacher_profile
    if not teacher:
        abort(403)
    return db.session.query(Class.id, Class.name).filter(
        Class.is_active.is_(True),
        db.or_(Class.primary_teacher_id == teacher.id, Class.assistant_teachers.any(id=teacher.id)),
    ).order_by(Class.name, Class.id).all()


def _roster(class_ids):
    return db.session.query(
        Student.id, Student.full_name, Student.current_grade,
        Enrollment.class_id, Class.name.label('class_name'),
    ).join(Enrollment, Enrollment.student_id == Student.id).join(
        Class, Enrollment.class_id == Class.id,
    ).filter(
        Enrollment.class_id.in_(class_ids), Enrollment.is_active.is_(True),
        Student.is_active.is_(True), Student.is_deleted.is_(False),
    )


def _require_access():
    if not current_user.can_access('students'):
        abort(403)


@teacher_bp.route('/students')
@login_required
@require_teacher
def students_list():
    _require_access()
    classes = _classes()
    class_id = request.args.get('class_id', type=int)
    if class_id is not None:
        if class_id not in {row.id for row in classes}:
            abort(404)
        return redirect(url_for('teacher.class_students', class_id=class_id,
                                q=request.args.get('q', ''), page=request.args.get('page', 1, type=int)))
    counts = dict(_roster([row.id for row in classes]).with_entities(
        Enrollment.class_id, db.func.count(db.distinct(Student.id)),
    ).group_by(Enrollment.class_id).all())
    return render_template('teacher/student_classes.html', classes=classes, counts=counts)


@teacher_bp.route('/students/class/<int:class_id>')
@login_required
@require_teacher
def class_students(class_id):
    _require_access()
    classes = _classes()
    selected_class = next((row for row in classes if row.id == class_id), None)
    if selected_class is None:
        abort(404)
    selected = {class_id}
    q = request.args.get('q', '').strip()
    query = _roster(selected)
    if q:
        query = query.filter(Student.full_name.icontains(q, autoescape=True))
    # Distinct students are paginated before loading their class memberships.
    pagination = query.with_entities(
        Student.id, Student.full_name, Student.current_grade,
    ).distinct().order_by(Student.full_name, Student.id).paginate(
        page=request.args.get('page', 1, type=int), per_page=20, error_out=False,
    )
    ids = [row.id for row in pagination.items]
    memberships = _roster(selected).filter(Student.id.in_(ids)).order_by(Class.name).all()
    students = []
    for row in pagination.items:
        students.append({
            'id': row.id, 'name': row.full_name, 'grade': row.current_grade,
            'classes': [member.class_name for member in memberships if member.id == row.id],
        })
    return render_template('teacher/students_list.html', students=students, selected_class=selected_class,
                           pagination=pagination, q=q, class_id=class_id)


@teacher_bp.route('/students/<int:student_id>')
@login_required
@require_teacher
def student_learning(student_id):
    _require_access()
    classes = _classes()
    memberships = _roster([row.id for row in classes]).filter(Student.id == student_id).order_by(Class.name).all()
    if not memberships:
        abort(404)
    back_class_id = request.args.get('class_id', type=int)
    if back_class_id not in {member.class_id for member in memberships}:
        back_class_id = memberships[0].class_id
    student = {'id': student_id, 'name': memberships[0].full_name, 'grade': memberships[0].current_grade}
    class_ids = [member.class_id for member in memberships]
    can_attendance = current_user.can_access('attendance')
    can_scores = current_user.can_access('scores')
    attendance = []
    scores = []
    homework = []
    exams = []
    if can_attendance:
        attendance = db.session.query(
            Schedule.date, Schedule.start_time, Class.name.label('class_name'), Attendance.status,
        ).join(Schedule, Attendance.schedule_id == Schedule.id).join(Class, Schedule.class_id == Class.id).filter(
            Attendance.student_id == student_id, Schedule.class_id.in_(class_ids),
            Attendance.status == AttendanceStatus.ABSENT,
            Schedule.is_cancelled.is_(False), Schedule.date <= date.today(),
        ).order_by(Schedule.date.desc(), Schedule.start_time.desc(), Schedule.id.desc()).limit(50).all()
    if can_scores:
        scores = db.session.query(
            Score.exam_date, Score.score_type, Score.score_value, Score.max_score,
            Class.name.label('class_name'),
        ).join(Class, Score.class_id == Class.id).filter(
            Score.student_id == student_id, Score.class_id.in_(class_ids), Score.score_source == 'center',
        ).order_by(Score.exam_date.desc().nullslast(), Score.id.desc()).limit(50).all()
        homework = db.session.query(
            Homework.assigned_date, Homework.title, Homework.assignment_round,
            Class.name.label('class_name'), HomeworkRecord.status,
        ).join(Class, Homework.class_id == Class.id).join(
            Enrollment, db.and_(Enrollment.class_id == Homework.class_id, Enrollment.student_id == student_id),
        ).outerjoin(HomeworkRecord, db.and_(
            HomeworkRecord.homework_id == Homework.id, HomeworkRecord.student_id == student_id,
        )).filter(
            Homework.class_id.in_(class_ids), Homework.assigned_date <= date.today(),
            Homework.assigned_date >= db.func.date(Enrollment.enrolled_at),
        ).order_by(Homework.assigned_date.desc(), Homework.id.desc()).limit(50).all()
    if current_user.can_access('exams'):
        # School is used only to resolve assignments; it is not exposed to the view.
        school_id = db.session.query(Student.school_id).filter(Student.id == student_id).scalar()
        target = SimpleNamespace(id=student_id, school_id=school_id)
        assigned = [
            exam for exam in Exam.query.filter(
                Exam.created_by == current_user.id, Exam.is_draft.is_(False),
            ).order_by(Exam.created_at.desc(), Exam.id.desc()).all()
            if exam_is_assigned_to_student(exam, target, active_class_ids=class_ids, teacher_class_ids=class_ids)
        ][:50]
        attempts = ExamAttempt.query.filter(
            ExamAttempt.student_id == student_id, ExamAttempt.exam_id.in_([exam.id for exam in assigned]),
        ).order_by(ExamAttempt.started_at.desc(), ExamAttempt.id.desc()).all()
        latest = {}
        for attempt in attempts:
            latest.setdefault(attempt.exam_id, attempt)
        for exam in assigned:
            attempt = latest.get(exam.id)
            status = 'Chưa làm'
            if attempt:
                status = 'Đang làm' if attempt.status == 'in_progress' else 'Đã nộp'
                if attempt.status != 'in_progress' and attempt.result.get('pending_essay_count', 0):
                    status = 'Chờ chấm'
            exams.append({'id': exam.id, 'title': exam.title, 'status': status})
    return render_template(
        'teacher/student_learning.html', student=student, memberships=memberships,
        attendance=attendance, scores=scores, homework=homework,
        can_attendance=can_attendance, can_scores=can_scores,
        score_labels=ScoreType.LABELS, exams=exams, can_exams=current_user.can_access('exams'),
        back_class_id=back_class_id,
        absence_warnings=get_absence_warnings(class_ids, as_of=date.today()) if can_attendance else [],
    )
