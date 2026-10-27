from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta

from extensions import db
from models import Attendance, AttendanceStatus, Class, Enrollment, LeaveRequest, LeaveRequestStatus, Schedule, Student


def get_absence_warnings(class_ids, *, as_of: date):
    """Absences exceed 25% of non-cancelled class sessions in the calendar month."""
    class_ids = set(class_ids)
    if not class_ids:
        return []
    enrollments = (
        db.session.query(Enrollment, Class, Student)
        .join(Class, Enrollment.class_id == Class.id)
        .join(Student, Enrollment.student_id == Student.id)
        .filter(
            Enrollment.class_id.in_(class_ids),
            Enrollment.is_active.is_(True),
            Student.is_active.is_(True),
            Student.is_deleted.is_(False),
            Enrollment.enrolled_at < as_of + timedelta(days=1),
        ).all()
    )
    if not enrollments:
        return []
    month_start = as_of.replace(day=1)
    month_end = as_of.replace(day=monthrange(as_of.year, as_of.month)[1])
    sessions = (
        Schedule.query.filter(
            Schedule.class_id.in_(class_ids),
            Schedule.is_cancelled.is_(False),
            Schedule.date.between(month_start, month_end),
        ).order_by(Schedule.date, Schedule.start_time, Schedule.id).all()
    )
    sessions_by_class = defaultdict(list)
    for session in sessions:
        sessions_by_class[session.class_id].append(session)

    completed_ids = {
        row.schedule_id for row in db.session.query(Attendance.schedule_id).filter(
            Attendance.schedule_id.in_([session.id for session in sessions]),
        ).distinct().all()
    }
    student_sessions = []
    for enrollment, class_, student in enrollments:
        monthly = sessions_by_class[class_.id]
        completed = [
            session for session in monthly
            if enrollment.enrolled_at.date() <= session.date <= as_of
            and session.id in completed_ids
        ]
        if not completed:
            continue
        student_sessions.append((class_, student, len(monthly), completed))
    if not student_sessions:
        return []
    session_ids = {session.id for _, _, _, completed in student_sessions for session in completed}
    student_ids = {student.id for _, student, _, _ in student_sessions}
    absences = {
        (attendance.student_id, attendance.schedule_id)
        for attendance in Attendance.query.filter(
            Attendance.schedule_id.in_(session_ids),
            Attendance.student_id.in_(student_ids),
            Attendance.status.in_([AttendanceStatus.ABSENT, AttendanceStatus.EXCUSED]),
        ).all()
    }
    leaves = defaultdict(list)
    for leave in LeaveRequest.query.filter(
        LeaveRequest.student_id.in_(student_ids),
        LeaveRequest.status == LeaveRequestStatus.APPROVED,
        LeaveRequest.start_date <= as_of,
        LeaveRequest.end_date >= month_start,
    ).all():
        leaves[leave.student_id].append(leave)

    warnings = []
    for class_, student, total, completed in student_sessions:
        count = sum(
            (student.id, session.id) in absences
            or any(leave.start_date <= session.date <= leave.end_date for leave in leaves[student.id])
            for session in completed
        )
        if count * 4 <= total:
            continue
        warnings.append({
            'student_id': student.id,
            'student_name': student.full_name,
            'class_id': class_.id,
            'class_name': class_.name,
            'absence_count': count,
            'monthly_sessions': total,
            'month_label': as_of.strftime('%m/%Y'),
            'completed_sessions': len(completed),
            'start_date': month_start.strftime('%d/%m/%Y'),
            'end_date': month_end.strftime('%d/%m/%Y'),
        })
    return sorted(warnings, key=lambda warning: (warning['class_name'], warning['student_name'], warning['student_id']))
