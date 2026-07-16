from extensions import db
from models import Room
from blueprints.api import (api_bp, api_ok, api_error, api_login_required, api_require_module,
                            get_page_args, pagination_meta, get_body, body_int, body_bool)


@api_bp.route('/rooms', methods=['GET'])
@api_login_required
@api_require_module('rooms')
def rooms_list():
    query = Room.query.filter_by(is_active=True)
    page, per_page = get_page_args()
    pagination = query.order_by(Room.branch, Room.floor, Room.room_number).paginate(page=page, per_page=per_page, error_out=False)
    return api_ok([r.to_dict() for r in pagination.items], meta=pagination_meta(pagination))


@api_bp.route('/rooms/<int:room_id>', methods=['GET'])
@api_login_required
@api_require_module('rooms')
def rooms_detail(room_id):
    room = Room.query.get(room_id)
    if not room:
        return api_error('Không tìm thấy phòng học.', 404, code='not_found')
    return api_ok(room.to_dict())


@api_bp.route('/rooms', methods=['POST'])
@api_login_required
@api_require_module('rooms', write=True)
def rooms_create():
    body = get_body()
    name = (body.get('name') or '').strip()
    if not name:
        return api_error('name là bắt buộc.', 400, code='validation_error')
    room = Room(
        name=name,
        branch=body.get('branch'),
        floor=body.get('floor'),
        room_number=body.get('room_number'),
        capacity=body_int(body, 'capacity') or 20,
    )
    db.session.add(room)
    db.session.commit()
    return api_ok(room.to_dict(), status=201)


@api_bp.route('/rooms/<int:room_id>', methods=['PUT'])
@api_login_required
@api_require_module('rooms', write=True)
def rooms_update(room_id):
    room = Room.query.get(room_id)
    if not room:
        return api_error('Không tìm thấy phòng học.', 404, code='not_found')
    body = get_body()
    for field in ('name', 'branch', 'floor', 'room_number'):
        if field in body:
            setattr(room, field, body.get(field))
    if 'capacity' in body:
        room.capacity = body_int(body, 'capacity')
    is_active = body_bool(body, 'is_active')
    if is_active is not None:
        room.is_active = is_active
    db.session.commit()
    return api_ok(room.to_dict())


@api_bp.route('/rooms/<int:room_id>', methods=['DELETE'])
@api_login_required
@api_require_module('rooms', write=True)
def rooms_delete(room_id):
    room = Room.query.get(room_id)
    if not room:
        return api_error('Không tìm thấy phòng học.', 404, code='not_found')
    room.is_active = False
    db.session.commit()
    return api_ok({'message': 'Đã xoá phòng học.'})
