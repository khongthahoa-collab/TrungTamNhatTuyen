"""WebCal (iCalendar) subscription feed — lets Teachers and Parents add
their schedule to their phone's native Calendar app. Deliberately its own
top-level blueprint (not part of api_bp/'/api/v1'): the feed can't use
Bearer-header or session-cookie auth since calendar apps only ever issue a
plain GET, so it's authenticated via a dedicated query-string secret
(User.calendar_token) instead, and — unlike api_bp — is NOT csrf-exempt,
since the token-rotation route is a real browser form POST.
"""
import secrets
from datetime import datetime

from flask import Blueprint, request, Response, abort, redirect, flash
from flask_login import login_required, current_user
from sqlalchemy import or_, and_
from sqlalchemy.orm import joinedload

from extensions import db
from models import Schedule, Class, Enrollment, Student, Teacher, User
from blueprints.auth import _dashboard_for
from blueprints.admin.classes import _current_school_year_range

api_calendar_bp = Blueprint('api_calendar', __name__)


def rfc5545_escape(text):
    """Escape RFC 5545 TEXT value special characters so a comma/semicolon
    in a class name or cancel reason can't corrupt the .ics structure."""
    if not text:
        return ''
    text = text.replace('\\', '\\\\')
    text = text.replace('\n', '\\n').replace('\r', '')
    text = text.replace(',', '\\,')
    text = text.replace(';', '\\;')
    return text


def _teacher_feed_schedules(teacher, start_date, end_date):
    """Schedules where this teacher is the *effective* teacher (assigned,
    unless a substitute has taken over — matches _find_teacher_conflict's
    definition in blueprints/admin/classes.py so 'my schedule' means the
    same thing everywhere in the app)."""
    return Schedule.query.options(joinedload(Schedule.class_)).join(
        Class, Schedule.class_id == Class.id
    ).filter(
        Class.is_active == True,
        Schedule.date >= start_date,
        Schedule.date <= end_date,
        or_(
            and_(Schedule.teacher_id == teacher.id, Schedule.substitute_teacher_id.is_(None)),
            Schedule.substitute_teacher_id == teacher.id,
        ),
    ).order_by(Schedule.date.asc(), Schedule.start_time.asc()).all()


def _parent_feed_schedules(parent_user, start_date, end_date):
    """Schedules across every active class of every active child of this
    parent — a parent can have more than one child enrolled."""
    student_ids = [s.id for s in Student.query.filter_by(parent_user_id=parent_user.id).all()]
    if not student_ids:
        return []
    active_class_ids = db.session.query(Enrollment.class_id).filter(
        Enrollment.student_id.in_(student_ids),
        Enrollment.is_active == True,
    ).scalar_subquery()
    return Schedule.query.options(joinedload(Schedule.class_)).join(
        Class, Schedule.class_id == Class.id
    ).filter(
        Class.is_active == True,
        Schedule.class_id.in_(active_class_ids),
        Schedule.date >= start_date,
        Schedule.date <= end_date,
    ).order_by(Schedule.date.asc(), Schedule.start_time.asc()).all()


def _build_ics(schedules):
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//TrungTamNhatTuyen//SchoolCalendar//VN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'X-WR-CALNAME:Lich hoc - Trung tam Nhat Tuyen',
        'X-WR-TIMEZONE:Asia/Ho_Chi_Minh',
        'BEGIN:VTIMEZONE',
        'TZID:Asia/Ho_Chi_Minh',
        'BEGIN:STANDARD',
        'DTSTART:19700101T000000',
        'TZOFFSETFROM:+0700',
        'TZOFFSETTO:+0700',
        'TZNAME:GMT+7',
        'END:STANDARD',
        'END:VTIMEZONE',
    ]

    for sched in schedules:
        date_str = sched.date.strftime('%Y%m%d')
        start_str = sched.start_time.strftime('%H%M%S')
        end_str = sched.end_time.strftime('%H%M%S')
        dtstamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')

        class_name = sched.class_.public_name if sched.class_ else ''
        summary = f'[ĐÃ HỦY] {class_name}' if sched.is_cancelled else class_name

        room_name = sched.room_obj.name if sched.room_obj else (sched.room or '')
        branch_name = sched.room_obj.branch if (sched.room_obj and sched.room_obj.branch) else ''
        location_parts = [p for p in (room_name, branch_name) if p]
        location = ', '.join(location_parts)

        desc_lines = [f'Lớp: {class_name}',
                      f'Thời gian: {sched.start_time.strftime("%H:%M")} - {sched.end_time.strftime("%H:%M")}']
        if room_name:
            desc_lines.append(f'Phòng: {room_name}')
        if branch_name:
            desc_lines.append(f'Cơ sở: {branch_name}')
        if sched.is_cancelled:
            desc_lines.insert(0, '⚠️ CẢNH BÁO: Buổi học này đã bị HỦY BỎ từ trung tâm.')
        description = '\n'.join(desc_lines)

        lines.extend([
            'BEGIN:VEVENT',
            f'UID:schedule_{sched.id}@trungtamnhattuyen',
            f'DTSTAMP:{dtstamp}',
            f'DTSTART;TZID=Asia/Ho_Chi_Minh:{date_str}T{start_str}',
            f'DTEND;TZID=Asia/Ho_Chi_Minh:{date_str}T{end_str}',
            f'SUMMARY:{rfc5545_escape(summary)}',
            f'LOCATION:{rfc5545_escape(location)}',
            f'DESCRIPTION:{rfc5545_escape(description)}',
            'BEGIN:VALARM',
            'TRIGGER:-PT30M',
            'ACTION:DISPLAY',
            'DESCRIPTION:Nhắc nhở lịch học/dạy sắp diễn ra tại Trung tâm',
            'END:VALARM',
            'END:VEVENT',
        ])

    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines)


@api_calendar_bp.route('/api/calendar/feed', methods=['GET'])
def calendar_feed():
    token = request.args.get('token')
    if not token:
        abort(403, description='Yêu cầu mã xác thực bảo mật lịch học.')

    user = User.query.filter_by(calendar_token=token, is_active=True, is_deleted=False).first()
    if not user:
        abort(403, description='Mã xác thực lịch không hợp lệ hoặc đã bị vô hiệu hóa.')

    # Cả năm học (01/07 - 30/06), giống quy ước cuộn năm học/lịch học ở
    # những chỗ khác trong hệ thống — trước đây chỉ lấy quanh ngày hiện tại
    # (-7/+30 ngày) khiến app Lịch không thấy được các buổi học xa hơn.
    start_date, end_date = _current_school_year_range()

    if user.role == 'teacher':
        teacher = Teacher.query.filter_by(user_id=user.id).first()
        if not teacher:
            abort(404, description='Không tìm thấy hồ sơ giáo viên liên kết.')
        schedules = _teacher_feed_schedules(teacher, start_date, end_date)
    elif user.role == 'parent':
        schedules = _parent_feed_schedules(user, start_date, end_date)
    else:
        abort(403, description='Vai trò của tài khoản không hỗ trợ tính năng đồng bộ lịch.')

    return Response(
        _build_ics(schedules),
        mimetype='text/calendar',
        headers={
            'Content-Disposition': 'inline; filename=lich-hoc.ics',
            'Cache-Control': 'public, max-age=1800',
        },
    )


@api_calendar_bp.route('/api/calendar/rotate-token', methods=['POST'])
@login_required
def rotate_calendar_token():
    current_user.calendar_token = secrets.token_hex(32)
    db.session.commit()
    flash('Đã cập nhật mã liên kết lịch. Vui lòng đăng ký lại đường dẫn mới trên thiết bị.', 'success')
    return redirect(request.referrer or _dashboard_for(current_user))
