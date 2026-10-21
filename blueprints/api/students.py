from datetime import date
from flask import request
from extensions import db
from models import Student, StudentLevel, Enrollment, Class, School, GRADE_BY_LEVEL
from blueprints.api import (api_bp, api_ok, api_error, api_login_required, api_require_module,
                            get_page_args, pagination_meta, get_body, body_int, body_bool)
from services.schedule_service import find_student_schedule_conflict, schedule_conflict_message


STUDENT_TEXT_LIMITS = {
    'gender': 10,
    'current_school': 200,
    'parent_name': 100,
    'parent_phone': 15,
}


def _parse_student_date(value):
    if value in (None, ''):
        return None, None
    if not isinstance(value, str):
        return None, 'date_of_birth phải có định dạng YYYY-MM-DD.'
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, 'date_of_birth phải có định dạng YYYY-MM-DD.'


def _student_request_body():
    body = get_body()
    if not isinstance(body, dict):
        return None, api_error('Nội dung yêu cầu phải là một đối tượng JSON.', 400,
                               code='validation_error')
    return body, None


def _student_school(body):
    raw_school_id = body.get('school_id')
    if raw_school_id in (None, ''):
        return None, None
    school_id = body_int(body, 'school_id')
    if school_id is None or school_id < 1:
        return None, api_error('school_id không hợp lệ.', 400, code='validation_error')
    school = School.query.filter_by(id=school_id, is_active=True).first()
    if not school:
        return None, api_error('Không tìm thấy trường học đang hoạt động.', 400,
                               code='validation_error')
    return school, None


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
    body, error = _student_request_body()
    if error:
        return error
    full_name = body.get('full_name')
    level = body.get('level')
    current_grade = body.get('current_grade')
    if not all(isinstance(value, str) for value in (full_name, level, current_grade)):
        return api_error('full_name, level và current_grade phải là chuỗi.', 400,
                         code='validation_error')
    full_name = full_name.strip()
    level = level.strip()
    current_grade = current_grade.strip()

    if (not full_name or len(full_name) > 100 or
            current_grade not in GRADE_BY_LEVEL.get(level, [])):
        return api_error('full_name, level, current_grade là bắt buộc và current_grade phải hợp lệ với level.',
                         400, code='validation_error')

    dob, error = _parse_student_date(body.get('date_of_birth'))
    if error:
        return api_error(error, 400, code='validation_error')
    school, error = _student_school(body)
    if error:
        return error
    optional_text = ('gender', 'current_school', 'parent_name', 'parent_phone', 'note')
    if any(body.get(field) is not None and not isinstance(body.get(field), str)
           for field in optional_text):
        return api_error('Thông tin học sinh dạng văn bản phải là chuỗi.', 400,
                         code='validation_error')
    if any(body.get(field) is not None and len(body[field]) > limit
           for field, limit in STUDENT_TEXT_LIMITS.items()):
        return api_error('Thông tin học sinh vượt quá độ dài cho phép.', 400,
                         code='validation_error')
    student = Student(
        full_name=full_name,
        level=level,
        current_grade=current_grade,
        gender=(body.get('gender') or '').strip() or None,
        date_of_birth=dob,
        current_school=school.name if school else ((body.get('current_school') or '').strip() or None),
        school_id=school.id if school else None,
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

    body, error = _student_request_body()
    if error:
        return error
    level = body.get('level', student.level)
    current_grade = body.get('current_grade', student.current_grade)
    if isinstance(level, str):
        level = level.strip()
    if isinstance(current_grade, str):
        current_grade = current_grade.strip()
    if (not isinstance(level, str) or not isinstance(current_grade, str) or
            current_grade not in GRADE_BY_LEVEL.get(level, [])):
        return api_error('current_grade không hợp lệ với level.', 400, code='validation_error')

    if 'school_id' in body or 'current_school' in body:
        school, error = _student_school(body)
        if error:
            return error
        if 'current_school' in body and body.get('current_school') is not None and not isinstance(
                body.get('current_school'), str):
            return api_error('current_school phải là chuỗi.', 400, code='validation_error')
    else:
        school = None

    if 'is_active' in body:
        active_value = body.get('is_active')
        if active_value is not None and (
                not isinstance(active_value, (bool, int, str)) or (
                isinstance(active_value, str) and
                active_value.strip().lower() not in ('1', '0', 'true', 'false', 'yes', 'no', 'on', 'off')) or (
                isinstance(active_value, int) and not isinstance(active_value, bool) and
                active_value not in (0, 1))):
            return api_error('is_active phải là giá trị đúng/sai.', 400, code='validation_error')

    student_updates = {}
    for field in ('full_name', 'gender', 'current_school', 'parent_name', 'parent_phone', 'note'):
        if field in body:
            value = body.get(field)
            if value is not None and not isinstance(value, str):
                return api_error(f'{field} phải là chuỗi.', 400, code='validation_error')
            if field == 'full_name':
                value = value.strip() if value else ''
                if not value or len(value) > 100:
                    return api_error('full_name không được để trống hoặc vượt quá 100 ký tự.',
                                     400, code='validation_error')
            else:
                value = (value.strip() or None) if value else None
            limit = STUDENT_TEXT_LIMITS.get(field)
            if value is not None and limit is not None and len(value) > limit:
                return api_error(f'{field} không được vượt quá {limit} ký tự.',
                                 400, code='validation_error')
            student_updates[field] = value

    dob = student.date_of_birth
    if 'date_of_birth' in body:
        dob, error = _parse_student_date(body.get('date_of_birth'))
        if error:
            return api_error(error, 400, code='validation_error')

    for field, value in student_updates.items():
        setattr(student, field, value)

    if 'school_id' in body or 'current_school' in body:
        student.school_id = school.id if school else None
        if school:
            student.current_school = school.name
        elif 'current_school' in body:
            current_school = body.get('current_school')
            student.current_school = (current_school.strip() or None) if current_school else None
        else:
            student.current_school = None

    student.level = level
    student.current_grade = current_grade
    student.date_of_birth = dob

    is_active = body_bool(body, 'is_active')
    if is_active is not None:
        student.is_active = is_active
        if not is_active:
            Enrollment.query.filter_by(student_id=student.id, is_active=True).update(
                {'is_active': False}, synchronize_session=False
            )
    if student.student_user:
        student.student_user.full_name = student.full_name
        student.student_user.is_active = (
            student.is_active
            and student.level in (StudentLevel.SECONDARY, StudentLevel.HIGH_SCHOOL)
        )

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
    student.is_active = False
    Enrollment.query.filter_by(student_id=student.id, is_active=True).update(
        {'is_active': False}, synchronize_session=False
    )
    if student.student_user:
        student.student_user.is_active = False
    db.session.commit()
    return api_ok({'message': 'Đã xoá học sinh.'})


@api_bp.route('/students/<int:student_id>/enroll', methods=['POST'])
@api_login_required
@api_require_module('students', write=True)
def students_enroll(student_id):
    student = Student.query.filter_by(id=student_id, is_deleted=False).first()
    if not student:
        return api_error('Không tìm thấy học sinh.', 404, code='not_found')

    body, error = _student_request_body()
    if error:
        return error
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
