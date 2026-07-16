"""Shared schedule-conflict helpers used by both classes.py (bulk "add
students") and students.py (single-student enroll) — kept here instead of a
blueprint module since both blueprints need it and services/ has no
blueprint-side imports to create a cycle with."""
from datetime import date as date_cls
from extensions import db
from models import Schedule, Class, Notification

WEEKDAY_NAMES = ['Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'Chủ nhật']


def _weekly_slots(class_id, today, cache=None):
    """Distinct (weekday, start_time, end_time) slots from a class's future,
    non-cancelled schedules — i.e. its currently-active weekly pattern.

    cache, if given, is a dict this call may read/write to reuse a class's
    slots across repeated calls (e.g. checking many students against the
    same target class one at a time) instead of re-querying identical data
    for each one — see find_student_schedule_conflict's slot_cache param."""
    if cache is not None and class_id in cache:
        return cache[class_id]
    rows = Schedule.query.filter(
        Schedule.class_id == class_id,
        Schedule.date >= today,
        Schedule.is_cancelled == False,
    ).all()
    slots = {(s.date.weekday(), s.start_time, s.end_time) for s in rows}
    if cache is not None:
        cache[class_id] = slots
    return slots


def class_subject_label(cls):
    """Short label like 'Hoá 8' (course name + short grade)."""
    course_name = cls.course.name if cls.course else ''
    grade_level = cls.grade_level or ''
    grade_short = grade_level[len('Lớp '):] if grade_level.startswith('Lớp ') else grade_level
    return f'{course_name} {grade_short}'.strip()


def find_student_schedule_conflict(student, target_class, today=None, slot_cache=None, active_class_ids=None):
    """Return (conflicting_class, weekday, start_time, end_time) if one of the
    student's other actively-enrolled classes already occupies a weekday+time
    slot that overlaps with target_class's weekly pattern, else None.

    slot_cache: optional dict shared across repeated calls (batch enroll
    flows) so target_class's own slots — identical on every call — and any
    other class checked more than once aren't re-queried each time.
    active_class_ids: optional pre-fetched set of the student's actively-
    enrolled class ids, to skip the per-student `student.enrollments` query
    when the caller has already batch-loaded it for the whole group."""
    today = today or date_cls.today()

    target_slots = _weekly_slots(target_class.id, today, slot_cache)
    if not target_slots:
        return None

    if active_class_ids is None:
        active_class_ids = {e.class_id for e in student.enrollments.filter_by(is_active=True).all()}
    other_class_ids = {cid for cid in active_class_ids if cid != target_class.id}
    if not other_class_ids:
        return None

    for class_id in other_class_ids:
        for (wd, start_t, end_t) in _weekly_slots(class_id, today, slot_cache):
            for (twd, tstart, tend) in target_slots:
                if wd == twd and start_t < tend and end_t > tstart:
                    return Class.query.get(class_id), wd, start_t, end_t
    return None


def schedule_conflict_message(student, target_class, conflict):
    other_class, wd, start_t, end_t = conflict
    return (
        f'{student.full_name} đã có lịch học {class_subject_label(other_class)} '
        f'lúc {start_t.strftime("%H:%M")}–{end_t.strftime("%H:%M")} {WEEKDAY_NAMES[wd]} '
        f'— trùng với lịch {class_subject_label(target_class)} của lớp này.'
    )


def notify_class_teachers(cls, title, body, link=None):
    """Create an in-app Notification for the primary teacher + all assistant
    teachers of a class (all count as "quản lý lớp"). No-op if none assigned."""
    user_ids = set()
    if cls.primary_teacher and cls.primary_teacher.user_id:
        user_ids.add(cls.primary_teacher.user_id)
    for t in cls.assistant_teachers:
        if t.user_id:
            user_ids.add(t.user_id)
    for uid in user_ids:
        db.session.add(Notification(user_id=uid, title=title, body=body, link=link))
