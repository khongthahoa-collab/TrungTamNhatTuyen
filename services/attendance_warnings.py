from bisect import bisect_left
from collections import defaultdict
from datetime import date, timedelta

from extensions import db
from models import Attendance, AttendanceStatus, Class, Enrollment, LeaveRequest, LeaveRequestStatus, Schedule, Student


def get_absence_warnings(class_ids, *, as_of: date):
    """Current personal cycle, based on completed class sessions since enrollment."""
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
    first_date = min(enrollment.enrolled_at.date() for enrollment, _, _ in enrollments)
    sessions = (
        Schedule.query.filter(
            Schedule.class_id.in_(class_ids),
            Schedule.is_cancelled.is_(False),
            Schedule.date.between(first_date, as_of),
            Schedule.attendances.any(),
        ).order_by(Schedule.date, Schedule.start_time, Schedule.id).all()
    )
    sessions_by_class = defaultdict(list)
    dates_by_class = defaultdict(list)
    for session in sessions:
        sessions_by_class[session.class_id].append(session)
        dates_by_class[session.class_id].append(session.date)

    cycles = []
    for enrollment, class_, student in enrollments:
        size = class_.sessions_per_week * 4
        if size <= 0:
            raise ValueError(f'Class {class_.id} must have positive sessions_per_week')
        start = bisect_left(dates_by_class[class_.id], enrollment.enrolled_at.date())
        personal_sessions = sessions_by_class[class_.id][start:]
        if not personal_sessions:
            continue
        # Keep a completed cycle visible until the next completed session starts a new one.
        cycle_index = (len(personal_sessions) - 1) // size
        current = personal_sessions[cycle_index * size:]
        cycles.append((class_, student, size, cycle_index + 1, current))
    if not cycles:
        return []
    session_ids = {session.id for _, _, _, _, cycle in cycles for session in cycle}
    student_ids = {student.id for _, student, _, _, _ in cycles}
    absences = {
        (attendance.student_id, attendance.schedule_id)
        for attendance in Attendance.query.filter(
            Attendance.schedule_id.in_(session_ids),
            Attendance.student_id.in_(student_ids),
            Attendance.status.in_([AttendanceStatus.ABSENT, AttendanceStatus.EXCUSED]),
        ).all()
    }
    leaves = defaultdict(list)
    cycle_start = min(cycle[0].date for _, _, _, _, cycle in cycles)
    for leave in LeaveRequest.query.filter(
        LeaveRequest.student_id.in_(student_ids),
        LeaveRequest.status == LeaveRequestStatus.APPROVED,
        LeaveRequest.start_date <= as_of,
        LeaveRequest.end_date >= cycle_start,
    ).all():
        leaves[leave.student_id].append(leave)

    warnings = []
    for class_, student, size, number, cycle in cycles:
        count = sum(
            (student.id, session.id) in absences
            or any(leave.start_date <= session.date <= leave.end_date for leave in leaves[student.id])
            for session in cycle
        )
        if count <= 2:
            continue
        warnings.append({
            'student_id': student.id,
            'student_name': student.full_name,
            'class_id': class_.id,
            'class_name': class_.name,
            'absence_count': count,
            'cycle_size': size,
            'cycle_number': number,
            'completed_sessions': len(cycle),
            'start_date': cycle[0].date.strftime('%d/%m/%Y'),
            'end_date': cycle[-1].date.strftime('%d/%m/%Y'),
        })
    return sorted(warnings, key=lambda warning: (warning['class_name'], warning['student_name'], warning['student_id']))
