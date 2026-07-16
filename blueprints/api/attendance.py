from datetime import date, datetime
from flask import g
from extensions import db
from models import Schedule, Attendance, AttendanceSummary, Enrollment, Student
from blueprints.api import api_bp, api_ok, api_error, api_login_required, api_require_module, get_body


@api_bp.route('/schedules/<int:schedule_id>/attendance', methods=['GET'])
@api_login_required
@api_require_module('attendance')
def attendance_get(schedule_id):
    schedule = Schedule.query.get(schedule_id)
    if not schedule:
        return api_error('Không tìm thấy buổi học.', 404, code='not_found')

    enrollments = (Enrollment.query.join(Student)
                  .filter(Enrollment.class_id == schedule.class_id, Enrollment.is_active == True)
                  .order_by(Student.full_name).all())
    records = {a.student_id: a for a in Attendance.query.filter_by(schedule_id=schedule_id).all()}

    roster = []
    for e in enrollments:
        att = records.get(e.student_id)
        roster.append({
            'student_id': e.student_id,
            'student_name': e.student.full_name,
            'status': att.status if att else None,
            'reason': att.reason if att else None,
        })
    return api_ok({'schedule': schedule.to_dict(), 'roster': roster})


@api_bp.route('/schedules/<int:schedule_id>/attendance', methods=['POST'])
@api_login_required
@api_require_module('attendance', write=True)
def attendance_save(schedule_id):
    """Bulk upsert — body: {"attendance": [{"student_id":, "status":, "reason":?}, ...]}.
    Same status vocabulary/summary bookkeeping as the web's save_attendance().
    A teacher token may only record today's own session; an admin token
    isn't date-restricted (matches the web app's is_teacher-vs-is_admin
    distinction in that same route)."""
    schedule = Schedule.query.get(schedule_id)
    if not schedule:
        return api_error('Không tìm thấy buổi học.', 404, code='not_found')

    user = g.api_user
    if user.is_teacher and not user.is_admin:
        teacher = user.teacher_profile
        cls = schedule.class_
        is_assigned = teacher and (cls.primary_teacher_id == teacher.id or teacher in cls.assistant_teachers)
        if not is_assigned:
            return api_error('Bạn không phụ trách lớp này.', 403, code='forbidden')
        if schedule.date != date.today():
            return api_error('Chỉ có thể điểm danh đúng ngày diễn ra buổi học.', 403, code='forbidden')

    body = get_body()
    records = body.get('attendance') or []
    if not records:
        return api_error('attendance là bắt buộc (danh sách).', 400, code='validation_error')

    counts = {'present': 0, 'absent': 0, 'late': 0, 'excused': 0}
    for record in records:
        student_id = record.get('student_id')
        status = record.get('status')
        if not student_id or status not in counts:
            continue
        att = Attendance.query.filter_by(schedule_id=schedule_id, student_id=student_id).first()
        if not att:
            att = Attendance(schedule_id=schedule_id, student_id=student_id)
            db.session.add(att)
        att.status = status
        att.reason = record.get('reason', '')
        att.recorded_by = user.id
        att.recorded_at = datetime.utcnow()
        counts[status] += 1

    summary = AttendanceSummary.query.filter_by(schedule_id=schedule_id).first()
    if not summary:
        summary = AttendanceSummary(schedule_id=schedule_id, class_id=schedule.class_id)
        db.session.add(summary)
    summary.present_count = counts['present']
    summary.absent_count = counts['absent']
    summary.late_count = counts['late']
    summary.excused_count = counts['excused']
    summary.total_enrolled = len(records)

    db.session.commit()
    return api_ok({'counts': counts})
