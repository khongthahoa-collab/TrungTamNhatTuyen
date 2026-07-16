from datetime import date
from flask import request
from extensions import db
from models import Student, Enrollment, Class, GRADE_BY_LEVEL
from blueprints.api import (api_bp, api_ok, api_error, api_login_required, api_require_module,
                            get_page_args, pagination_meta, get_body, body_int, body_bool)
from services.schedule_service import find_student_schedule_conflict, schedule_conflict_message


@api_bp.route('/students', methods=['GET'])
@api_login_required
@api_require_module('students')
def students_list():
    q = request.args.get('q', '').strip()
    grade = request.args.get('grade', '').strip()
    school_q = request.args.get('school_q', '').strip()
    active = request.args.get('active', '1')

    query = Student.query.filter_by(is_deleted=False)
    if active == '1':
        query = query.filter_by(is_active=True)
    if q:
        query = query.filter(Student.full_name.ilike(f'%{q}%'))
    if grade:
        query = query.filter_by(current_grade=grade)
    if school_q:
        query = query.filter(Student.current_school.ilike(f'%{school_q}%'))

    page, per_page = get_page_args()
    pagination = query.order_by(Student.full_name).paginate(page=page, per_page=per_page, error_out=False)
    return api_ok([s.to_dict() for s in pagination.items], meta=pagination_meta(pagination))


@api_bp.route('/students/<int:student_id>', methods=['GET'])
@api_login_required
@api_require_module('students')
def students_detail(student_id):
    student = Student.query.filter_by(id=student_id, is_deleted=False).first()
    if not student:
        return api_error('Không tìm thấy học sinh.', 404, code='not_found')
    data = student.to_dict()
    data['active_classes'] = [c.to_dict() for c in student.active_classes]
    return api_ok(data)


@api_bp.route('/students', methods=['POST'])
@api_login_required
@api_require_module('students', write=True)
def students_create():
    body = get_body()
    full_name = (body.get('full_name') or '').strip()
    level = (body.get('level') or '').strip()
    current_grade = (body.get('current_grade') or '').strip()

    if not full_name or not level or current_grade not in GRADE_BY_LEVEL.get(level, []):
        return api_error('full_name, level, current_grade là bắt buộc và current_grade phải hợp lệ với level.',
                         400, code='validation_error')

    dob = body.get('date_of_birth')
    student = Student(
        full_name=full_name,
        level=level,
        current_grade=current_grade,
        gender=body.get('gender'),
        date_of_birth=date.fromisoformat(dob) if dob else None,
        current_school=(body.get('current_school') or '').strip() or None,
        school_id=body_int(body, 'school_id'),
        parent_name=(body.get('parent_name') or '').strip() or None,
        parent_phone=(body.get('parent_phone') or '').strip() or None,
        note=(body.get('note') or '').strip() or None,
    )
    db.session.add(student)
    db.session.commit()
    return api_ok(student.to_dict(), status=201)


@api_bp.route('/students/<int:student_id>', methods=['PUT'])
@api_login_required
@api_require_module('students', write=True)
def students_update(student_id):
    student = Student.query.filter_by(id=student_id, is_deleted=False).first()
    if not student:
        return api_error('Không tìm thấy học sinh.', 404, code='not_found')

    body = get_body()
    level = body.get('level', student.level)
    current_grade = body.get('current_grade', student.current_grade)
    if current_grade not in GRADE_BY_LEVEL.get(level, []):
        return api_error('current_grade không hợp lệ với level.', 400, code='validation_error')

    for field in ('full_name', 'gender', 'current_school', 'parent_name', 'parent_phone', 'note'):
        if field in body:
            setattr(student, field, body.get(field))
    student.level = level
    student.current_grade = current_grade
    is_active = body_bool(body, 'is_active')
    if is_active is not None:
        student.is_active = is_active
    if body.get('date_of_birth'):
        student.date_of_birth = date.fromisoformat(body['date_of_birth'])

    db.session.commit()
    return api_ok(student.to_dict())


@api_bp.route('/students/<int:student_id>', methods=['DELETE'])
@api_login_required
@api_require_module('students', write=True)
def students_delete(student_id):
    student = Student.query.filter_by(id=student_id, is_deleted=False).first()
    if not student:
        return api_error('Không tìm thấy học sinh.', 404, code='not_found')
    student.is_deleted = True
    db.session.commit()
    return api_ok({'message': 'Đã xoá học sinh.'})


@api_bp.route('/students/<int:student_id>/enroll', methods=['POST'])
@api_login_required
@api_require_module('students', write=True)
def students_enroll(student_id):
    student = Student.query.filter_by(id=student_id, is_deleted=False).first()
    if not student:
        return api_error('Không tìm thấy học sinh.', 404, code='not_found')

    body = get_body()
    class_id = body_int(body, 'class_id')
    if not class_id:
        return api_error('class_id là bắt buộc.', 400, code='validation_error')

    class_ = Class.query.get(class_id)
    if not class_:
        return api_error('Không tìm thấy lớp học.', 404, code='not_found')

    conflict = find_student_schedule_conflict(student, class_)
    if conflict:
        return api_error(schedule_conflict_message(student, class_, conflict), 409, code='schedule_conflict')

    existing = Enrollment.query.filter_by(student_id=student_id, class_id=class_id).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
    else:
        db.session.add(Enrollment(student_id=student_id, class_id=class_id))
    db.session.commit()
    return api_ok({'message': f'Đã thêm học sinh vào lớp {class_.name}.'}, status=201)


@api_bp.route('/students/<int:student_id>/enroll/<int:class_id>', methods=['DELETE'])
@api_login_required
@api_require_module('students', write=True)
def students_unenroll(student_id, class_id):
    enrollment = Enrollment.query.filter_by(student_id=student_id, class_id=class_id).first()
    if not enrollment:
        return api_error('Không tìm thấy đăng ký lớp học này.', 404, code='not_found')
    enrollment.is_active = False
    db.session.commit()
    return api_ok({'message': 'Đã hủy ghi danh.'})
