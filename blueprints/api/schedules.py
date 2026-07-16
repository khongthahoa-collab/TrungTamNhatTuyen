from datetime import date, time as time_type
from flask import request
from extensions import db
from models import Schedule, Room
from blueprints.api import (api_bp, api_ok, api_error, api_login_required, api_require_module,
                            get_page_args, pagination_meta, get_body, body_int)
from blueprints.admin.classes import _check_room_conflict


@api_bp.route('/schedules', methods=['GET'])
@api_login_required
@api_require_module('classes')
def schedules_list():
    class_id = request.args.get('class_id', type=int)
    teacher_id = request.args.get('teacher_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    query = Schedule.query
    if class_id:
        query = query.filter_by(class_id=class_id)
    if teacher_id:
        query = query.filter_by(teacher_id=teacher_id)
    if date_from:
        query = query.filter(Schedule.date >= date.fromisoformat(date_from))
    if date_to:
        query = query.filter(Schedule.date <= date.fromisoformat(date_to))

    page, per_page = get_page_args()
    pagination = query.order_by(Schedule.date, Schedule.start_time).paginate(page=page, per_page=per_page, error_out=False)
    return api_ok([s.to_dict() for s in pagination.items], meta=pagination_meta(pagination))


@api_bp.route('/schedules/<int:schedule_id>', methods=['GET'])
@api_login_required
@api_require_module('classes')
def schedules_detail(schedule_id):
    schedule = Schedule.query.get(schedule_id)
    if not schedule:
        return api_error('Không tìm thấy buổi học.', 404, code='not_found')
    return api_ok(schedule.to_dict())


@api_bp.route('/schedules', methods=['POST'])
@api_login_required
@api_require_module('classes', write=True)
def schedules_create():
    """A single ad-hoc session (e.g. buổi tăng cường), same shape as the
    web's add_schedule() — for a class's regular weekly pattern, use
    POST /classes (schedule=[...]) instead."""
    body = get_body()
    class_id = body_int(body, 'class_id')
    if not class_id:
        return api_error('class_id là bắt buộc.', 400, code='validation_error')

    try:
        sched_date = date.fromisoformat(body.get('date'))
        start_time = time_type.fromisoformat(body.get('start_time'))
        end_time = time_type.fromisoformat(body.get('end_time'))
    except (TypeError, ValueError):
        return api_error('date/start_time/end_time không hợp lệ.', 400, code='validation_error')

    room_id = body_int(body, 'room_id')
    if room_id:
        conflict = _check_room_conflict(room_id, sched_date, start_time, end_time)
        if conflict:
            room = Room.query.get(room_id)
            return api_error(
                f'Phòng "{room.display_name if room else room_id}" đã được đặt vào khung giờ này.',
                409, code='room_conflict')

    room = Room.query.get(room_id) if room_id else None
    schedule = Schedule(
        class_id=class_id,
        teacher_id=body_int(body, 'teacher_id'),
        date=sched_date,
        start_time=start_time,
        end_time=end_time,
        room_id=room_id,
        room=room.display_name if room else (body.get('room') or None),
        topic=(body.get('topic') or '').strip() or None,
        schedule_type=body.get('schedule_type', 'regular'),
    )
    db.session.add(schedule)
    db.session.commit()
    return api_ok(schedule.to_dict(), status=201)


@api_bp.route('/schedules/<int:schedule_id>', methods=['PUT'])
@api_login_required
@api_require_module('classes', write=True)
def schedules_update(schedule_id):
    schedule = Schedule.query.get(schedule_id)
    if not schedule:
        return api_error('Không tìm thấy buổi học.', 404, code='not_found')

    body = get_body()
    if 'teacher_id' in body:
        schedule.teacher_id = body_int(body, 'teacher_id')
    if 'topic' in body:
        schedule.topic = body.get('topic')
    if 'room_id' in body:
        room_id = body_int(body, 'room_id')
        schedule.room_id = room_id
        room = Room.query.get(room_id) if room_id else None
        schedule.room = room.display_name if room else None
    if body.get('date'):
        schedule.date = date.fromisoformat(body['date'])
    if body.get('start_time'):
        schedule.start_time = time_type.fromisoformat(body['start_time'])
    if body.get('end_time'):
        schedule.end_time = time_type.fromisoformat(body['end_time'])

    db.session.commit()
    return api_ok(schedule.to_dict())


@api_bp.route('/schedules/<int:schedule_id>/cancel', methods=['POST'])
@api_login_required
@api_require_module('classes', write=True)
def schedules_cancel(schedule_id):
    schedule = Schedule.query.get(schedule_id)
    if not schedule:
        return api_error('Không tìm thấy buổi học.', 404, code='not_found')
    body = get_body()
    schedule.is_cancelled = True
    schedule.cancel_reason = (body.get('reason') or '').strip() or None
    db.session.commit()
    return api_ok(schedule.to_dict())


@api_bp.route('/schedules/<int:schedule_id>', methods=['DELETE'])
@api_login_required
@api_require_module('classes', write=True)
def schedules_delete(schedule_id):
    schedule = Schedule.query.get(schedule_id)
    if not schedule:
        return api_error('Không tìm thấy buổi học.', 404, code='not_found')
    db.session.delete(schedule)
    db.session.commit()
    return api_ok({'message': 'Đã xóa buổi học.'})
