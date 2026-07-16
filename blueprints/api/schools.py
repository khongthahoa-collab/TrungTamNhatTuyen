from extensions import db
from models import School
from blueprints.api import (api_bp, api_ok, api_error, api_login_required, api_require_module,
                            get_page_args, pagination_meta, get_body, body_int, body_bool)


@api_bp.route('/schools', methods=['GET'])
@api_login_required
@api_require_module('schools')
def schools_list():
    query = School.query.filter_by(is_active=True)
    page, per_page = get_page_args()
    pagination = query.order_by(School.name).paginate(page=page, per_page=per_page, error_out=False)
    return api_ok([s.to_dict() for s in pagination.items], meta=pagination_meta(pagination))


@api_bp.route('/schools/<int:school_id>', methods=['GET'])
@api_login_required
@api_require_module('schools')
def schools_detail(school_id):
    school = School.query.get(school_id)
    if not school:
        return api_error('Không tìm thấy trường học.', 404, code='not_found')
    return api_ok(school.to_dict())


@api_bp.route('/schools', methods=['POST'])
@api_login_required
@api_require_module('schools', write=True)
def schools_create():
    body = get_body()
    name = (body.get('name') or '').strip()
    if not name:
        return api_error('name là bắt buộc.', 400, code='validation_error')
    if School.query.filter_by(name=name).first():
        return api_error('Trường học này đã tồn tại.', 409, code='duplicate')
    school = School(name=name, grade_from=body_int(body, 'grade_from'), grade_to=body_int(body, 'grade_to'))
    db.session.add(school)
    db.session.commit()
    return api_ok(school.to_dict(), status=201)


@api_bp.route('/schools/<int:school_id>', methods=['PUT'])
@api_login_required
@api_require_module('schools', write=True)
def schools_update(school_id):
    school = School.query.get(school_id)
    if not school:
        return api_error('Không tìm thấy trường học.', 404, code='not_found')
    body = get_body()
    if 'name' in body:
        school.name = body.get('name')
    if 'grade_from' in body:
        school.grade_from = body_int(body, 'grade_from')
    if 'grade_to' in body:
        school.grade_to = body_int(body, 'grade_to')
    is_active = body_bool(body, 'is_active')
    if is_active is not None:
        school.is_active = is_active
    db.session.commit()
    return api_ok(school.to_dict())


@api_bp.route('/schools/<int:school_id>', methods=['DELETE'])
@api_login_required
@api_require_module('schools', write=True)
def schools_delete(school_id):
    school = School.query.get(school_id)
    if not school:
        return api_error('Không tìm thấy trường học.', 404, code='not_found')
    school.is_active = False
    db.session.commit()
    return api_ok({'message': 'Đã xoá trường học.'})
