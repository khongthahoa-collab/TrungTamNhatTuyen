from flask import request
from extensions import db
from models import Teacher, User, UserRole
from blueprints.api import (api_bp, api_ok, api_error, api_login_required, api_require_module,
                            get_page_args, pagination_meta, get_body, body_bool)
from blueprints.admin.account_utils import next_username, DEFAULT_TEMP_PASSWORD


@api_bp.route('/teachers', methods=['GET'])
@api_login_required
@api_require_module('teachers')
def teachers_list():
    query = Teacher.query.join(Teacher.user).filter(User.is_deleted == False)
    page, per_page = get_page_args()
    pagination = query.order_by(User.full_name).paginate(page=page, per_page=per_page, error_out=False)
    return api_ok([t.to_dict() for t in pagination.items], meta=pagination_meta(pagination))


@api_bp.route('/teachers/<int:teacher_id>', methods=['GET'])
@api_login_required
@api_require_module('teachers')
def teachers_detail(teacher_id):
    teacher = Teacher.query.get(teacher_id)
    if not teacher:
        return api_error('Không tìm thấy giáo viên.', 404, code='not_found')
    return api_ok(teacher.to_dict())


@api_bp.route('/teachers', methods=['POST'])
@api_login_required
@api_require_module('teachers', write=True)
def teachers_create():
    body = get_body()
    full_name = (body.get('full_name') or '').strip()
    gender = (body.get('gender') or '').strip() or None
    if not full_name or not gender:
        return api_error('full_name và gender là bắt buộc.', 400, code='validation_error')

    username = (body.get('username') or '').strip() or next_username(UserRole.TEACHER)
    phone = (body.get('phone') or '').strip() or None

    dup_filters = [User.username == username]
    if phone:
        dup_filters.append(User.phone == phone)
    if User.query.filter(db.or_(*dup_filters)).first():
        return api_error('Tên đăng nhập hoặc số điện thoại đã tồn tại.', 409, code='duplicate')

    user = User(full_name=full_name, username=username, phone=phone,
               role=UserRole.TEACHER, gender=gender, must_change_password=True)
    user.set_password(DEFAULT_TEMP_PASSWORD)
    db.session.add(user)
    db.session.flush()

    teacher = Teacher(user_id=user.id, is_staff=body_bool(body, 'is_staff', True),
                      base_salary=float(body.get('base_salary') or 0))
    db.session.add(teacher)
    db.session.commit()

    data = teacher.to_dict()
    data['temp_password'] = DEFAULT_TEMP_PASSWORD
    return api_ok(data, status=201)


@api_bp.route('/teachers/<int:teacher_id>', methods=['PUT'])
@api_login_required
@api_require_module('teachers', write=True)
def teachers_update(teacher_id):
    teacher = Teacher.query.get(teacher_id)
    if not teacher:
        return api_error('Không tìm thấy giáo viên.', 404, code='not_found')

    body = get_body()
    if 'full_name' in body:
        teacher.user.full_name = body.get('full_name')
    if 'phone' in body:
        teacher.user.phone = body.get('phone') or None
    if 'gender' in body:
        teacher.user.gender = body.get('gender')
    is_staff = body_bool(body, 'is_staff')
    if is_staff is not None:
        teacher.is_staff = is_staff
    if 'base_salary' in body:
        teacher.base_salary = float(body.get('base_salary') or 0)

    db.session.commit()
    return api_ok(teacher.to_dict())


@api_bp.route('/teachers/<int:teacher_id>', methods=['DELETE'])
@api_login_required
@api_require_module('teachers', write=True)
def teachers_delete(teacher_id):
    teacher = Teacher.query.get(teacher_id)
    if not teacher:
        return api_error('Không tìm thấy giáo viên.', 404, code='not_found')
    teacher.user.is_deleted = True
    teacher.user.is_active = False
    db.session.commit()
    return api_ok({'message': 'Đã xoá giáo viên.'})
