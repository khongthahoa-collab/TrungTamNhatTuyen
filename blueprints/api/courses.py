from extensions import db
from models import Course
from blueprints.api import (api_bp, api_ok, api_error, api_login_required, api_require_module,
                            get_page_args, pagination_meta, get_body, body_bool)


@api_bp.route('/courses', methods=['GET'])
@api_login_required
@api_require_module('courses')
def courses_list():
    query = Course.query.filter_by(is_active=True)
    page, per_page = get_page_args()
    pagination = query.order_by(Course.name).paginate(page=page, per_page=per_page, error_out=False)
    return api_ok([c.to_dict() for c in pagination.items], meta=pagination_meta(pagination))


@api_bp.route('/courses/<int:course_id>', methods=['GET'])
@api_login_required
@api_require_module('courses')
def courses_detail(course_id):
    course = Course.query.get(course_id)
    if not course:
        return api_error('Không tìm thấy môn học.', 404, code='not_found')
    return api_ok(course.to_dict())


@api_bp.route('/courses', methods=['POST'])
@api_login_required
@api_require_module('courses', write=True)
def courses_create():
    body = get_body()
    name = (body.get('name') or '').strip()
    if not name:
        return api_error('name là bắt buộc.', 400, code='validation_error')
    course = Course(name=name, level=body.get('level'), description=body.get('description'))
    db.session.add(course)
    db.session.commit()
    return api_ok(course.to_dict(), status=201)


@api_bp.route('/courses/<int:course_id>', methods=['PUT'])
@api_login_required
@api_require_module('courses', write=True)
def courses_update(course_id):
    course = Course.query.get(course_id)
    if not course:
        return api_error('Không tìm thấy môn học.', 404, code='not_found')
    body = get_body()
    for field in ('name', 'level', 'description'):
        if field in body:
            setattr(course, field, body.get(field))
    is_active = body_bool(body, 'is_active')
    if is_active is not None:
        course.is_active = is_active
    db.session.commit()
    return api_ok(course.to_dict())


@api_bp.route('/courses/<int:course_id>', methods=['DELETE'])
@api_login_required
@api_require_module('courses', write=True)
def courses_delete(course_id):
    course = Course.query.get(course_id)
    if not course:
        return api_error('Không tìm thấy môn học.', 404, code='not_found')
    course.is_active = False
    db.session.commit()
    return api_ok({'message': 'Đã xoá môn học.'})
