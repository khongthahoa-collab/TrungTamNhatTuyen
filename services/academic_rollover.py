"""Preview and execute year transitions without rebuilding historical records."""
from collections import defaultdict
from datetime import date, datetime, timedelta
import hashlib
import json
import re

import click
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy import insert, select, text
from sqlalchemy.orm import selectinload

from extensions import db
from models import (
    AcademicRollover, AcademicYear, Class, Enrollment, GRADE_SEQUENCE, GRADE_TO_LEVEL,
    Notification, Room, Schedule, Semester, Student, Teacher,
)


class RolloverError(ValueError):
    pass


def _snapshot(rows):
    return [
        {column.name: getattr(row, column.name) for column in row.__table__.columns}
        for row in sorted(rows, key=lambda row: row.id)
    ]


def _new_name(cls, next_grade):
    old = cls.grade_level.removeprefix('Lớp ')
    new = next_grade.removeprefix('Lớp ')
    # Replace only the grade following the subject, never a number in a suffix.
    prefix = f'{cls.course.name} {old}'
    if not re.match(re.escape(prefix) + r'(?=$|[\s\-–(])', cls.name, re.IGNORECASE):
        raise RolloverError(f'Lớp #{cls.id}: tên "{cls.name}" không khớp môn/khối. Hãy chuẩn hóa tên trước.')
    result = f'{cls.name[:len(cls.course.name)]} {new}{cls.name[len(prefix):]}'
    if len(result) > 100:
        raise RolloverError(f'Lớp #{cls.id}: tên mới vượt 100 ký tự.')
    return result


def build_rollover_plan(today=None):
    today = today or date.today()
    years = AcademicYear.query.order_by(AcademicYear.id).all()
    active = [year for year in years if year.is_active]
    errors = []
    if len(active) != 1:
        raise RolloverError('Cần đúng một năm học đang hoạt động trước khi chuyển năm.')
    year = active[0]
    target = year.start_date.year + 1
    start, end = date(target, 7, 1), date(target + 1, 6, 30)
    if year.start_date != date(target - 1, 7, 1) or year.end_date != date(target, 6, 30):
        errors.append('Năm học hiện tại phải theo mốc 01/07–30/06.')
    if today < start:
        errors.append(f'Chỉ chuyển năm từ {start.strftime("%d/%m/%Y")}.')
    if today > end:
        errors.append('Năm học đang hoạt động đã quá cũ. Cần đối chiếu dữ liệu trước khi chuyển.')
    destinations = [item for item in years if item.start_date == start]
    if len(destinations) > 1 or any(item.end_date != end for item in destinations):
        errors.append('Năm học đích trùng hoặc sai ngày kết thúc.')
    target_semesters = sorted(
        Semester.query.filter(Semester.academic_year_id.in_([item.id for item in destinations])).all(),
        key=lambda semester: semester.start_date,
    )
    for index, semester in enumerate(target_semesters):
        if semester.start_date < start or semester.end_date > end or semester.end_date < semester.start_date:
            errors.append(f'Học kỳ #{semester.id}: khoảng ngày không thuộc năm học đích.')
        if index and semester.start_date <= target_semesters[index - 1].end_date:
            errors.append(f'Học kỳ #{semester.id}: khoảng ngày chồng lấn.')
    if any(item.id != year.id and item not in destinations
           and item.start_date <= end and item.end_date >= start for item in years):
        errors.append('Khoảng năm học đích chồng lấn một năm học khác.')

    classes = Class.query.filter_by(is_active=True).options(
        selectinload(Class.assistant_teachers), selectinload(Class.course),
    ).order_by(Class.id).all()
    class_ids = [cls.id for cls in classes]
    all_students = Student.query.filter_by(is_active=True, is_deleted=False).options(
        selectinload(Student.student_user),
    ).order_by(Student.id).all()
    students = [student for student in all_students if student.status != 'pending_confirmation']
    student_map = {student.id: student for student in students}
    for student in students:
        if student.current_grade not in GRADE_SEQUENCE:
            errors.append(f'Học sinh #{student.id} {student.full_name}: khối không hợp lệ.')
        if student.grade_year != target - 1:
            errors.append(f'Học sinh #{student.id} {student.full_name}: mốc năm phải là {target - 1}, hiện là {student.grade_year}.')
    enrollments = Enrollment.query.filter(
        Enrollment.class_id.in_(class_ids), Enrollment.is_active.is_(True),
    ).order_by(Enrollment.id).all()
    rosters = defaultdict(list)
    for enrollment in enrollments:
        if enrollment.student_id not in student_map:
            errors.append(f'Đăng ký #{enrollment.id}: học sinh không hoạt động hoặc đang chờ xác nhận; cần xử lý trước.')
        rosters[enrollment.class_id].append(enrollment)
    schedules = Schedule.query.filter(
        Schedule.class_id.in_(class_ids),
        Schedule.date >= year.start_date, Schedule.date <= year.end_date,
        Schedule.schedule_type == 'regular', Schedule.is_cancelled.is_(False),
    ).order_by(Schedule.date, Schedule.id).all()
    by_class = defaultdict(list)
    for schedule in schedules:
        by_class[schedule.class_id].append(schedule)
    teachers = Teacher.query.options(selectinload(Teacher.user)).all()
    teacher_ids = {teacher.id for teacher in teachers
                   if teacher.user and teacher.user.is_active and not teacher.user.is_deleted}
    rooms = Room.query.all()
    room_ids = {room.id for room in rooms if room.is_active}
    room_aliases = defaultdict(set)
    for room in rooms:
        for label in (room.name, room.display_name):
            room_aliases[label.strip().casefold()].add(room.id)
    rolling, graduating, proposed = [], [], []
    for cls in classes:
        if (cls.start_date is None or cls.end_date is None
                or cls.start_date < year.start_date or cls.end_date > year.end_date
                or cls.start_date > cls.end_date):
            errors.append(f'Lớp #{cls.id} {cls.name}: ngày bắt đầu/kết thúc không nằm trong năm học nguồn.')
        if cls.grade_level not in GRADE_SEQUENCE:
            errors.append(f'Lớp #{cls.id} {cls.name}: khối tự do chưa có phương án chuyển; cần xử lý trước.')
            continue
        if cls.grade_level == 'Lớp 12':
            graduating.append(cls)
            if any(student_map.get(e.student_id)
                   and student_map[e.student_id].current_grade != 'Lớp 12' for e in rosters[cls.id]):
                errors.append(f'Lớp #{cls.id}: có học sinh không ở khối 12, không thể tự đóng lớp.')
            continue
        if cls.primary_teacher_id is not None and cls.primary_teacher_id not in teacher_ids:
            errors.append(f'Lớp #{cls.id}: giáo viên quản lý không còn hoạt động; cần xử lý trước.')
        if any(teacher.id not in teacher_ids for teacher in cls.assistant_teachers):
            errors.append(f'Lớp #{cls.id}: trợ giảng không còn hoạt động; cần xử lý trước.')
        next_grade = GRADE_SEQUENCE[GRADE_SEQUENCE.index(cls.grade_level) + 1]
        try:
            name = _new_name(cls, next_grade)
        except RolloverError as exc:
            errors.append(str(exc))
            continue
        rows = by_class[cls.id]
        # Latest occurrence of each weekday, including all slots on that date.
        latest = {row.date.weekday(): row.date for row in rows}
        pattern = [row for row in rows if row.date == latest[row.date.weekday()]]
        if not pattern:
            errors.append(f'Lớp #{cls.id} {cls.name}: không có lịch thường kỳ để kế thừa.')
        slots = []
        seen = set()
        for row in pattern:
            key = (row.date.weekday(), row.start_time, row.end_time, row.room_id, row.teacher_id)
            if key in seen:
                errors.append(f'Lớp #{cls.id}: lịch tuần bị trùng.')
                continue
            seen.add(key)
            if row.end_time <= row.start_time or row.teacher_id not in teacher_ids:
                errors.append(f'Lớp #{cls.id}: khung giờ/giáo viên của buổi #{row.id} không hợp lệ.')
                continue
            if row.room_id is not None and row.room_id not in room_ids:
                errors.append(f'Lớp #{cls.id}: phòng của buổi #{row.id} không còn hoạt động.')
                continue
            slots.append({
                'weekday': row.date.weekday(), 'start_time': row.start_time,
                'end_time': row.end_time, 'room_id': row.room_id, 'room': row.room,
                'teacher_id': row.teacher_id,
            })
        roster = [e for e in rosters[cls.id]
                  if e.student_id in student_map and student_map[e.student_id].current_grade != 'Lớp 12']
        rolling.append({'class': cls, 'name': name, 'grade': next_grade, 'slots': slots, 'roster': roster})
        day = start
        while day <= end:
            for slot in slots:
                if day.weekday() == slot['weekday']:
                    proposed.append({'source_class_id': cls.id, 'date': day,
                                     **{k: v for k, v in slot.items() if k != 'weekday'}})
            day += timedelta(days=1)

    if Class.query.filter(Class.rolled_over_from_id.in_(class_ids), Class.start_date == start).first():
        errors.append('Đã có lớp kế thừa trong năm đích; không thể tạo lại.')
    future = Schedule.query.filter(
        Schedule.date >= start, Schedule.date <= end, Schedule.is_cancelled.is_(False),
    ).order_by(Schedule.id).all()
    buckets = defaultdict(list)
    student_ids_by_class = {
        item['class'].id: {e.student_id for e in item['roster']} for item in rolling
    }
    future_rosters = Enrollment.query.filter(
        Enrollment.class_id.in_({row.class_id for row in future}), Enrollment.is_active.is_(True),
    ).all() if future else []
    existing_student_ids = defaultdict(set)
    for enrollment in future_rosters:
        existing_student_ids[enrollment.class_id].add(enrollment.student_id)
    conflicts = set()
    for row in [*future, *proposed]:
        existing = isinstance(row, Schedule)
        item = ({
            'date': row.date, 'start_time': row.start_time, 'end_time': row.end_time,
            'room_id': row.room_id, 'teacher_id': row.substitute_teacher_id or row.teacher_id,
            'source_class_id': row.class_id, 'room': row.room,
        } if existing else row)
        cid = item['source_class_id']
        resources = [('teacher', item['teacher_id']), ('room', item['room_id'])]
        if not item['room_id'] and item['room']:
            label = item['room'].strip().casefold()
            matches = room_aliases[label]
            if len(matches) == 1:
                room_id = next(iter(matches))
                resources.append(('room', room_id))
                if not existing and room_id not in room_ids:
                    errors.append(f'Lớp #{cid}: phòng "{item["room"]}" không còn hoạt động.')
            elif len(matches) > 1:
                errors.append(f'Lớp #{cid}: tên phòng "{item["room"]}" không xác định duy nhất; cần chọn phòng bằng ID.')
            else:
                resources.append(('room_text', label))
        resources += [('student', sid) for sid in
                      (existing_student_ids[cid] if existing else student_ids_by_class.get(cid, set()))]
        for kind, resource in resources:
            if resource is None:
                continue
            key = (item['date'], kind, resource)
            for other, other_existing in buckets[key]:
                if (not existing or not other_existing) and (
                    item['start_time'] < other['end_time'] and item['end_time'] > other['start_time']
                ):
                    conflicts.add(f'{kind} #{resource}: trùng lịch ngày {item["date"]} giữa lớp #{cid} và #{other["source_class_id"]}.')
            buckets[key].append((item, existing))
    errors.extend(sorted(conflicts))
    snapshot = {
        'years': _snapshot(years), 'classes': _snapshot(classes),
        'assistants': {cls.id: sorted(t.id for t in cls.assistant_teachers) for cls in classes},
        'courses': _snapshot({cls.course.id: cls.course for cls in classes}.values()),
        'students': _snapshot(all_students), 'enrollments': _snapshot(enrollments),
        'schedules': _snapshot(schedules), 'future': _snapshot(future),
        'future_rosters': _snapshot(future_rosters), 'teachers': _snapshot(teachers),
        'semesters': _snapshot(Semester.query.all()),
        'rooms': _snapshot(rooms),
        'teacher_accounts': {teacher.id: (teacher.user.is_active, teacher.user.is_deleted)
                             for teacher in teachers if teacher.user},
    }
    fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()
    return dict(current_year=target - 1, next_year=target, source=year, destination=destinations[0] if destinations else None,
                rolling=rolling, lop12=graduating, students=students, schedules=proposed,
                errors=list(dict.fromkeys(errors)), fingerprint=fingerprint,
                teacher_names={teacher.id: teacher.display_name for teacher in teachers},
                graduating=[s for s in students if s.current_grade == 'Lớp 12'])


def execute_rollover(job):
    if not current_app.config.get('ACADEMIC_ROLLOVER_ENABLED', False):
        raise RolloverError('Chức năng cuộn năm đang tắt; không được chuyển dữ liệu.')
    plan = build_rollover_plan()
    if plan['errors']:
        raise RolloverError('\n'.join(plan['errors']))
    if (job.target_year != plan['next_year'] or job.source_year_id != plan['source'].id
            or job.fingerprint != plan['fingerprint']):
        raise RolloverError('Dữ liệu đã thay đổi sau khi xem trước. Hãy xem trước và xác nhận lại.')
    target = plan['next_year']
    start, end = date(target, 7, 1), date(target + 1, 6, 30)
    destination = plan['destination']
    if destination is None:
        destination = AcademicYear(name=f'{target}-{target + 1}', start_date=start, end_date=end, is_active=False)
        db.session.add(destination)
        db.session.flush()
    semesters = Semester.query.filter_by(academic_year_id=destination.id).all()
    if not semesters:
        third = (end - start).days // 3
        first_end = start + timedelta(days=third)
        second_end = first_end + timedelta(days=third + 1)
        for kind, label, sem_start, sem_end in (
            ('semester_1', 'Học kỳ 1', start, first_end),
            ('semester_2', 'Học kỳ 2', first_end + timedelta(days=1), second_end),
            ('summer', 'Hè', second_end + timedelta(days=1), end),
        ):
            semester = Semester(academic_year_id=destination.id, semester_type=kind,
                                name=label, start_date=sem_start, end_date=sem_end)
            db.session.add(semester)
            semesters.append(semester)
        db.session.flush()
    class_map = {}
    for item in plan['rolling']:
        cls = item['class']
        new = Class(
            name=item['name'], grade_level=item['grade'], course_id=cls.course_id,
            max_students=cls.max_students, monthly_fee=cls.monthly_fee,
            sessions_per_week=cls.sessions_per_week, description=cls.description,
            primary_teacher_id=cls.primary_teacher_id, zalo_group_id=cls.zalo_group_id,
            start_date=start, end_date=end, rolled_over_from_id=cls.id,
        )
        new.assistant_teachers = list(cls.assistant_teachers)
        db.session.add(new)
        db.session.flush()
        class_map[cls.id] = new.id
        for enrollment in item['roster']:
            db.session.add(Enrollment(
                class_id=new.id, student_id=enrollment.student_id,
                discount_pct=enrollment.discount_pct, note=enrollment.note,
            ))
        for teacher in {t.id: t for t in [*cls.assistant_teachers, *([cls.primary_teacher] if cls.primary_teacher else [])]}.values():
            db.session.add(Notification(
                user_id=teacher.user_id, title='Lớp học năm mới',
                body=f'{cls.name} → {new.name}', link='/teacher/schedule',
            ))
        cls.is_active = False
    rows = []
    for schedule in plan['schedules']:
        matches = [sem for sem in semesters if sem.start_date <= schedule['date'] <= sem.end_date]
        if len(matches) > 1:
            raise RolloverError(f'Học kỳ chồng lấn ngày {schedule["date"]}.')
        rows.append({
            **{k: v for k, v in schedule.items() if k != 'source_class_id'},
            'class_id': class_map[schedule['source_class_id']],
            'schedule_type': 'regular', 'semester_id': matches[0].id if matches else None,
            'is_cancelled': False,
        })
    for offset in range(0, len(rows), 500):
        db.session.execute(insert(Schedule), rows[offset:offset + 500])
    for cls in plan['lop12']:
        cls.is_active = False
    for student in plan['students']:
        if student.current_grade == 'Lớp 12':
            student.is_active = False
            student.status = 'graduated'
            if student.student_user:
                student.student_user.is_active = False
        else:
            student.current_grade = GRADE_SEQUENCE[GRADE_SEQUENCE.index(student.current_grade) + 1]
            student.level = GRADE_TO_LEVEL[student.current_grade]
        student.grade_year = target
    plan['source'].is_active = False
    destination.is_active = True
    return {'classes': len(class_map), 'schedules': len(rows), 'students': len(plan['students']),
            'graduated': len(plan['graduating']), 'class_map': class_map}


@click.command('process-academic-rollovers')
@with_appcontext
def process_academic_rollovers():
    """Run pending year transitions outside web workers; safe to schedule every minute."""
    if not current_app.config.get('ACADEMIC_ROLLOVER_ENABLED', False):
        raise click.ClickException('Academic rollover is disabled; no data was changed.')
    try:
        if db.engine.dialect.name == 'postgresql':
            # One runner; a crashed process releases the transaction lock automatically.
            if not db.session.execute(text('SELECT pg_try_advisory_xact_lock(726021)')).scalar():
                db.session.rollback()
                click.echo('Another rollover worker is running.')
                return
        job = db.session.execute(
            select(AcademicRollover).where(AcademicRollover.status == 'pending')
            .order_by(AcademicRollover.id).with_for_update()
        ).scalars().first()
        if job is None:
            db.session.rollback()
            click.echo('No pending academic rollovers.')
            return
        job_id = job.id
        if db.engine.dialect.name == 'postgresql':
            db.session.execute(text("SET LOCAL lock_timeout = '5s'"))
            db.session.execute(text(
                'LOCK TABLE academic_years, classes, class_assistant_teachers, courses, '
                'enrollments, rooms, schedules, semesters, students, teachers, users '
                'IN SHARE ROW EXCLUSIVE MODE'
            ))
        result = execute_rollover(job)
        job.status = 'succeeded'
        job.finished_at = datetime.utcnow()
        job.result_json = json.dumps(result)
        db.session.commit()
        click.echo(f'Academic rollover #{job_id} succeeded: {json.dumps(result)}')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Academic rollover failed')
        if 'job_id' in locals():
            job = db.session.execute(
                select(AcademicRollover).where(AcademicRollover.id == job_id)
                .with_for_update().execution_options(populate_existing=True)
            ).scalar_one()
            if job.status == 'pending':
                job.status = 'failed'
                job.error = str(exc) if isinstance(exc, RolloverError) else 'Lỗi xử lý; xem log máy chủ. Dữ liệu đã được rollback.'
                job.finished_at = datetime.utcnow()
            db.session.commit()
        raise click.ClickException('Academic rollover failed; no transition changes committed.') from exc
