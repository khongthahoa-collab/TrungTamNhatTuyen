from datetime import date, time as time_type
from flask import request
from extensions import db
from models import Class, Course, Teacher, Schedule, Student, Enrollment, GRADE_SEQUENCE
from blueprints.api import (api_bp, api_ok, api_error, api_login_required, api_require_module,
                            get_page_args, pagination_meta, get_body, body_int)
from blueprints.admin.classes import (_generate_schedules, _find_teacher_conflict, _has_duplicate_slot,
                                      _current_school_year_range, _make_class_name, _semester_for_date)
from services.schedule_service import find_student_schedule_conflict, schedule_conflict_message


@api_bp.route('/classes', methods=['GET'])
@api_login_required
@api_require_module('classes')
def classes_list():
    course_id = request.args.get('course_id', type=int)
    grade_level = request.args.get('grade_level', '').strip()
    teacher_id = request.args.get('teacher_id', type=int)
    active = request.args.get('active', '1')

    query = Class.query
    if active == '1':
        query = query.filter_by(is_active=True)
    if course_id:
        query = query.filter_by(course_id=course_id)
    if grade_level:
        query = query.filter_by(grade_level=grade_level)
    if teacher_id:
        query = query.filter_by(primary_teacher_id=teacher_id)

    page, per_page = get_page_args()
    pagination = query.order_by(Class.name).paginate(page=page, per_page=per_page, error_out=False)
    return api_ok([c.to_dict() for c in pagination.items], meta=pagination_meta(pagination))


@api_bp.route('/classes/<int:class_id>', methods=['GET'])
@api_login_required
@api_require_module('classes')
def classes_detail(class_id):
    cls = Class.query.get(class_id)
    if not cls:
        return api_error('Không tìm thấy lớp học.', 404, code='not_found')
    data = cls.to_dict()
    data['current_enrollment'] = cls.current_enrollment
    return api_ok(data)


@api_bp.route('/classes/<int:class_id>/schedules', methods=['GET'])
@api_login_required
@api_require_module('classes')
def classes_schedules(class_id):
    cls = Class.query.get(class_id)
    if not cls:
        return api_error('Không tìm thấy lớp học.', 404, code='not_found')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    query = Schedule.query.filter_by(class_id=class_id)
    if date_from:
        query = query.filter(Schedule.date >= date.fromisoformat(date_from))
    if date_to:
        query = query.filter(Schedule.date <= date.fromisoformat(date_to))
    schedules = query.order_by(Schedule.date, Schedule.start_time).all()
    return api_ok([s.to_dict() for s in schedules])


def _parse_schedule_rows(body, allowed_teacher_ids, default_teacher_id):
    """API equivalent of blueprints/admin/classes.py's _parse_sched_rows,
    reading a JSON array instead of HTML sched_day[]/sched_start[]/...
    form fields. Same output tuple shape: (weekday, start_str, end_str,
    room_id, room_text, teacher_id)."""
    from models import Room
    rows = []
    for row in body.get('schedule') or []:
        try:
            wd = int(row.get('weekday'))
            start_str = row['start_time']
            end_str = row['end_time']
        except (KeyError, TypeError, ValueError):
            continue
        if end_str <= start_str:
            continue
        room_id = row.get('room_id')
        room_id = int(room_id) if room_id else None
        room = Room.query.get(room_id) if room_id else None
        row_teacher_id = row.get('teacher_id')
        row_teacher_id = int(row_teacher_id) if row_teacher_id else None
        if row_teacher_id not in allowed_teacher_ids:
            row_teacher_id = default_teacher_id
        rows.append((wd, start_str, end_str, room_id, room.display_name if room else '', row_teacher_id))
    return rows


@api_bp.route('/classes', methods=['POST'])
@api_login_required
@api_require_module('classes', write=True)
def classes_create():
    body = get_body()
    grade_level = (body.get('grade_level') or '').strip()
    course_id = body_int(body, 'course_id')
    primary_teacher_id = body_int(body, 'primary_teacher_id')
    assistant_teacher_ids = [int(x) for x in (body.get('assistant_teacher_ids') or []) if x]

    if not grade_level or not course_id or not primary_teacher_id:
        return api_error('grade_level, course_id, primary_teacher_id là bắt buộc.', 400, code='validation_error')

    allowed_teacher_ids = {tid for tid in [primary_teacher_id, *assistant_teacher_ids] if tid}
    sched_rows = _parse_schedule_rows(body, allowed_teacher_ids, primary_teacher_id)
    if not sched_rows:
        return api_error('Cần ít nhất một khung giờ học (schedule).', 400, code='validation_error')

    dup = _has_duplicate_slot(grade_level, course_id, primary_teacher_id, sched_rows)
    if dup:
        return api_error(f'Giáo viên đã dạy lớp "{dup.name}" (cùng lớp, cùng môn) ở khung giờ này.',
                         409, code='duplicate_slot')

    start_date, end_date = _current_school_year_range()
    conflict = _find_teacher_conflict(max(date.today(), start_date), end_date, sched_rows)
    if conflict:
        from blueprints.admin.classes import _conflict_message
        return api_error(_conflict_message(conflict.effective_teacher, conflict), 409, code='schedule_conflict')

    course = Course.query.get(course_id)
    primary_teacher = Teacher.query.get(primary_teacher_id)
    name = (body.get('name') or '').strip() or _make_class_name(course.name if course else '', grade_level, primary_teacher)

    cls = Class(
        name=name,
        course_id=course_id,
        grade_level=grade_level,
        max_students=body_int(body, 'max_students') or 20,
        monthly_fee=float(body.get('monthly_fee') or 0),
        sessions_per_week=len(sched_rows),
        description=(body.get('description') or '').strip() or None,
        primary_teacher_id=primary_teacher_id,
        start_date=start_date,
        end_date=end_date,
    )
    db.session.add(cls)
    db.session.flush()
    if assistant_teacher_ids:
        cls.assistant_teachers = Teacher.query.filter(Teacher.id.in_(assistant_teacher_ids)).all()

    semester = _semester_for_date(start_date)
    _generate_schedules(cls.id, start_date, end_date, sched_rows, semester_id=semester.id if semester else None)

    db.session.commit()
    return api_ok(cls.to_dict(), status=201)


@api_bp.route('/classes/<int:class_id>', methods=['PUT'])
@api_login_required
@api_require_module('classes', write=True)
def classes_update(class_id):
    cls = Class.query.get(class_id)
    if not cls:
        return api_error('Không tìm thấy lớp học.', 404, code='not_found')

    body = get_body()
    new_primary_id = body_int(body, 'primary_teacher_id') if 'primary_teacher_id' in body else cls.primary_teacher_id

    # Same cascade as the web class_edit(): a teacher reassignment must
    # follow through to that class's future Schedule rows, or the old
    # teacher stays falsely "busy" for a class they no longer teach.
    old_primary_id = cls.primary_teacher_id
    if new_primary_id != old_primary_id and old_primary_id:
        Schedule.query.filter(
            Schedule.class_id == class_id,
            Schedule.teacher_id == old_primary_id,
            Schedule.date >= date.today(),
        ).update({'teacher_id': new_primary_id}, synchronize_session=False)

    for field in ('name', 'grade_level', 'description'):
        if field in body:
            setattr(cls, field, body.get(field))
    if 'course_id' in body:
        cls.course_id = body_int(body, 'course_id')
    if 'max_students' in body:
        cls.max_students = body_int(body, 'max_students')
    if 'monthly_fee' in body:
        cls.monthly_fee = float(body.get('monthly_fee') or 0)
    if 'is_active' in body:
        cls.is_active = str(body.get('is_active')).lower() in ('1', 'true', 'yes')
    cls.primary_teacher_id = new_primary_id
    if 'assistant_teacher_ids' in body:
        ids = [int(x) for x in (body.get('assistant_teacher_ids') or []) if x]
        cls.assistant_teachers = Teacher.query.filter(Teacher.id.in_(ids)).all() if ids else []

    db.session.commit()
    return api_ok(cls.to_dict())


@api_bp.route('/classes/<int:class_id>', methods=['DELETE'])
@api_login_required
@api_require_module('classes', write=True)
def classes_delete(class_id):
    cls = Class.query.get(class_id)
    if not cls:
        return api_error('Không tìm thấy lớp học.', 404, code='not_found')
    cls.is_active = False
    db.session.commit()
    return api_ok({'message': 'Đã đóng lớp học.'})


@api_bp.route('/classes/<int:class_id>/students', methods=['POST'])
@api_login_required
@api_require_module('classes', write=True)
def classes_add_students(class_id):
    """Same "skip conflicting students, add the rest" behavior as the
    web's class_add_students()."""
    cls = Class.query.get(class_id)
    if not cls:
        return api_error('Không tìm thấy lớp học.', 404, code='not_found')

    body = get_body()
    student_ids = [int(x) for x in (body.get('student_ids') or []) if x]
    if not student_ids:
        return api_error('student_ids là bắt buộc.', 400, code='validation_error')

    students = Student.query.filter(Student.id.in_(student_ids)).all()
    ok_ids, skipped = [], []
    for student in students:
        conflict = find_student_schedule_conflict(student, cls)
        if conflict:
            skipped.append({'student_id': student.id, 'message': schedule_conflict_message(student, cls, conflict)})
        else:
            ok_ids.append(student.id)

    existing = {e.student_id: e for e in Enrollment.query.filter(
        Enrollment.student_id.in_(ok_ids), Enrollment.class_id == class_id).all()}
    added = 0
    for sid in ok_ids:
        e = existing.get(sid)
        if e:
            if not e.is_active:
                e.is_active = True
                added += 1
        else:
            db.session.add(Enrollment(student_id=sid, class_id=class_id))
            added += 1
    db.session.commit()
    return api_ok({'added': added, 'skipped': skipped}, status=201)
