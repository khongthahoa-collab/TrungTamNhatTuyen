from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required
from datetime import date, timedelta, time as time_type
import re
from extensions import db
from models import Class, Course, Teacher, Schedule, Semester, Enrollment, Student, Room
from blueprints.admin import admin_bp, require_admin

# ── Constants ──────────────────────────────────────────────────────────────

# Grades grouped by school level (for JS filtering when course level is known)
GRADE_BY_LEVEL = {
    'primary':     ['Tiền tiểu học', 'Lớp 1', 'Lớp 2', 'Lớp 3', 'Lớp 4', 'Lớp 5'],
    'secondary':   ['Lớp 6', 'Lớp 7', 'Lớp 8', 'Lớp 9'],
    'high_school': ['Lớp 10', 'Lớp 11', 'Lớp 12'],
}
ALL_GRADES = (
    GRADE_BY_LEVEL['primary'] +
    GRADE_BY_LEVEL['secondary'] +
    GRADE_BY_LEVEL['high_school'] +
    ['Loại khác']
)

GRADE_LEVEL_OPTIONS = [(g, g) for g in ALL_GRADES]
GRADE_LEVEL_LABELS = {g: g for g in ALL_GRADES}

# Preset time slots: start → end (+90 min)
TIME_SLOTS = [
    ('07:30', '09:00'),
    ('09:00', '10:30'),
    ('10:30', '12:00'),
    ('13:30', '15:00'),
    ('14:30', '16:00'),
    ('16:00', '17:30'),
    ('17:30', '19:00'),
    ('19:00', '20:30'),
    ('20:30', '22:00'),
]
# Lookup: start → end
TIME_SLOT_END = {s: e for s, e in TIME_SLOTS}

# Vietnamese weekday names → Python weekday index (Mon=0)
DAY_OPTIONS = [
    ('0', 'Thứ 2'),
    ('1', 'Thứ 3'),
    ('2', 'Thứ 4'),
    ('3', 'Thứ 5'),
    ('4', 'Thứ 6'),
    ('5', 'Thứ 7'),
    ('6', 'Chủ nhật'),
]


# ── Helpers ────────────────────────────────────────────────────────────────

def _check_room_conflict(room_id, sched_date, start_time, end_time, exclude_id=None):
    if not room_id:
        return None
    q = Schedule.query.filter(
        Schedule.room_id == room_id,
        Schedule.date == sched_date,
        Schedule.is_cancelled == False,
        Schedule.start_time < end_time,
        Schedule.end_time > start_time,
    )
    if exclude_id:
        q = q.filter(Schedule.id != exclude_id)
    return q.first()


def _get_active_semester():
    """Return the currently active semester, or the next upcoming one."""
    today = date.today()
    sem = Semester.query.filter(
        Semester.start_date <= today,
        Semester.end_date >= today,
    ).first()
    if not sem:
        sem = Semester.query.filter(Semester.start_date > today).order_by(Semester.start_date).first()
    return sem


def _generate_schedules(class_id, teacher_id, semester, sched_rows):
    """
    Generate Schedule rows for each (weekday, start_time, end_time, room_id) entry
    across the semester date range. Skip conflicts. Return (created, skipped_conflict) counts.
    """
    created = 0
    skipped = 0
    current = semester.start_date
    while current <= semester.end_date:
        wd = current.weekday()
        for (target_wd, start_str, end_str, room_id, room_text) in sched_rows:
            if wd == target_wd:
                start_t = time_type.fromisoformat(start_str)
                end_t = time_type.fromisoformat(end_str)
                # Skip if already exists for this class/date/time
                exists = Schedule.query.filter_by(
                    class_id=class_id, date=current, start_time=start_t
                ).first()
                if exists:
                    continue
                # Room conflict check
                if room_id and _check_room_conflict(room_id, current, start_t, end_t):
                    skipped += 1
                    continue
                s = Schedule(
                    class_id=class_id,
                    teacher_id=teacher_id,
                    date=current,
                    start_time=start_t,
                    end_time=end_t,
                    room=room_text,
                    room_id=room_id,
                    schedule_type='regular',
                    semester_id=semester.id,
                )
                db.session.add(s)
                created += 1
        current += timedelta(days=1)
    return created, skipped


def _gen_class_suffix(grade_level, course_id, exclude_id=None):
    """Return next available letter suffix (A, B, C…) for this grade+course."""
    q = Class.query.filter_by(grade_level=grade_level, course_id=course_id)
    if exclude_id:
        q = q.filter(Class.id != exclude_id)
    count = q.count()
    return chr(ord('A') + count)


def _make_class_name(grade_level, course_name, suffix):
    """Build display name like 'Lớp 6A - Toán' or 'Tiền tiểu học A - Toán'."""
    if grade_level and re.search(r'\d$', grade_level):
        combined = f'{grade_level}{suffix}'
    else:
        combined = f'{grade_level} {suffix}'.strip()
    return f'{combined} - {course_name}' if course_name else combined


def _has_duplicate_slot(grade_level, course_id, teacher_id, sched_rows, exclude_class_id=None):
    """Return conflicting class if same teacher already teaches same grade+course at same weekday+time."""
    if not teacher_id or not sched_rows:
        return None
    q = Class.query.filter(
        Class.grade_level == grade_level,
        Class.course_id == course_id,
        Class.primary_teacher_id == teacher_id,
        Class.is_active == True,
    )
    if exclude_class_id:
        q = q.filter(Class.id != exclude_class_id)
    existing = q.all()
    if not existing:
        return None
    for cls in existing:
        for (wd, start_str, end_str, room_id, room_text) in sched_rows:
            start_t = time_type.fromisoformat(start_str)
            sched = Schedule.query.filter(
                Schedule.class_id == cls.id,
                Schedule.start_time == start_t,
                Schedule.is_cancelled == False,
            ).first()
            if sched and sched.date.weekday() == wd:
                return cls
    return None


def _parse_sched_rows(teachers_by_id, default_teacher_id):
    """Parse schedule rows from POST form data."""
    days = request.form.getlist('sched_day')
    starts = request.form.getlist('sched_start')
    room_ids_raw = request.form.getlist('sched_room_id')
    rows = []
    rooms_by_id = {r.id: r for r in Room.query.all()}
    for i in range(len(days)):
        try:
            wd = int(days[i])
        except (ValueError, IndexError):
            continue
        start_str = starts[i] if i < len(starts) else ''
        if start_str not in TIME_SLOT_END:
            continue
        end_str = TIME_SLOT_END[start_str]
        try:
            room_id = int(room_ids_raw[i]) if i < len(room_ids_raw) and room_ids_raw[i] else None
        except ValueError:
            room_id = None
        room_text = rooms_by_id[room_id].display_name if room_id and room_id in rooms_by_id else ''
        rows.append((wd, start_str, end_str, room_id, room_text))
    return rows


# ── Routes ─────────────────────────────────────────────────────────────────

def _build_suffix_counts():
    """Build a mapping of 'grade|course_id' → existing class count for name preview."""
    rows = db.session.query(Class.grade_level, Class.course_id, db.func.count(Class.id)) \
        .group_by(Class.grade_level, Class.course_id).all()
    return {f'{g}|{c}': cnt for g, c, cnt in rows}


def _form_context(action, courses, teachers, rooms, semesters, default_semester, form=None, class_=None):
    return dict(
        action=action, courses=courses, teachers=teachers, rooms=rooms,
        semesters=semesters, default_semester_id=default_semester.id if default_semester else None,
        grade_options=GRADE_LEVEL_OPTIONS,
        time_slots=TIME_SLOTS, day_options=DAY_OPTIONS,
        form=form, class_=class_,
        suffix_counts=_build_suffix_counts() if action == 'add' else {},
    )


@admin_bp.route('/classes')
@login_required
@require_admin
def classes():
    q = request.args.get('q', '').strip()
    active_only = request.args.get('active_only', '1')
    query = Class.query
    if q:
        query = query.filter(Class.name.ilike(f'%{q}%'))
    if active_only == '1':
        query = query.filter_by(is_active=True)
    classes = query.order_by(Class.name).all()
    return render_template('admin/classes/list.html',
                           classes=classes, q=q, active_only=active_only,
                           grade_labels=GRADE_LEVEL_LABELS)


@admin_bp.route('/classes/add', methods=['GET', 'POST'])
@login_required
@require_admin
def class_add():
    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()
    teachers = Teacher.query.join(Teacher.user).order_by('full_name').all()
    rooms = Room.query.filter_by(is_active=True).order_by(Room.branch, Room.floor, Room.room_number).all()
    semesters = Semester.query.order_by(Semester.start_date.desc()).all()
    default_semester = _get_active_semester()

    if request.method == 'POST':
        # Grade level: select value or custom text for "Loại khác"
        grade_select = request.form.get('grade_level_select', '').strip()
        grade_custom = request.form.get('grade_level_custom', '').strip()
        grade_level = grade_custom if grade_select == 'Loại khác' else grade_select

        course_id = request.form.get('course_id', type=int)
        primary_teacher_id = request.form.get('primary_teacher_id', type=int) or None
        assistant_teacher_id = request.form.get('assistant_teacher_id', type=int) or None
        max_students = request.form.get('max_students', type=int) or None
        monthly_fee = request.form.get('monthly_fee', 0, type=float)
        description = request.form.get('description', '').strip()
        semester_id = request.form.get('semester_id', type=int)

        sched_rows = _parse_sched_rows({t.id: t for t in teachers}, primary_teacher_id)
        # sessions_per_week: from form override, else auto from schedule row count
        sessions_per_week = request.form.get('sessions_per_week', type=int) or len(sched_rows) or 1

        errors = []
        if not grade_level:
            errors.append('Vui lòng chọn lớp học.')
        if not course_id:
            errors.append('Vui lòng chọn môn học.')
        if not primary_teacher_id:
            errors.append('Vui lòng chọn giáo viên chính.')
        if not sched_rows:
            errors.append('Vui lòng thêm ít nhất một lịch học.')
        if not semester_id:
            errors.append('Vui lòng chọn học kỳ.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('admin/classes/form.html',
                                   **_form_context('add', courses, teachers, rooms, semesters, default_semester,
                                                   form=request.form))

        # Duplicate slot check
        dup = _has_duplicate_slot(grade_level, course_id, primary_teacher_id, sched_rows)
        if dup:
            flash(f'Giáo viên đã dạy lớp "{dup.name}" (cùng lớp, cùng môn) ở khung giờ này.', 'danger')
            return render_template('admin/classes/form.html',
                                   **_form_context('add', courses, teachers, rooms, semesters, default_semester,
                                                   form=request.form))

        # Auto-generate class name
        course = Course.query.get(course_id)
        suffix = _gen_class_suffix(grade_level, course_id)
        name = _make_class_name(grade_level, course.name if course else '', suffix)

        cl = Class(
            name=name,
            course_id=course_id,
            grade_level=grade_level,
            max_students=max_students,
            monthly_fee=monthly_fee,
            sessions_per_week=sessions_per_week,
            description=description,
            primary_teacher_id=primary_teacher_id,
            assistant_teacher_id=assistant_teacher_id,
        )
        db.session.add(cl)
        db.session.flush()

        semester = Semester.query.get(semester_id)
        msg_extra = ''
        if semester:
            created, skipped = _generate_schedules(cl.id, primary_teacher_id, semester, sched_rows)
            msg_extra = f' Đã tạo {created} buổi học'
            if skipped:
                msg_extra += f' ({skipped} buổi bỏ qua do phòng trùng)'
            msg_extra += f' cho {semester.name}.'

        db.session.commit()
        flash(f'Đã tạo lớp {name}.{msg_extra}', 'success')
        return redirect(url_for('admin.class_detail', class_id=cl.id))

    return render_template('admin/classes/form.html',
                           **_form_context('add', courses, teachers, rooms, semesters, default_semester,
                                           form={}))


@admin_bp.route('/classes/<int:class_id>')
@login_required
@require_admin
def class_detail(class_id):
    class_ = Class.query.get_or_404(class_id)
    teachers = Teacher.query.join(Teacher.user).all()
    semesters = Semester.query.order_by(Semester.start_date.desc()).all()
    rooms = Room.query.filter_by(is_active=True).order_by(Room.branch, Room.floor, Room.room_number).all()
    today = date.today()

    upcoming = class_.schedules.filter(
        Schedule.date >= today
    ).order_by(Schedule.date, Schedule.start_time).limit(10).all()

    past = class_.schedules.filter(
        Schedule.date < today
    ).order_by(Schedule.date.desc()).limit(10).all()

    return render_template('admin/classes/detail.html',
                           class_=class_, teachers=teachers,
                           semesters=semesters, rooms=rooms,
                           grade_label=GRADE_LEVEL_LABELS.get(class_.grade_level, class_.grade_level or ''),  # grade_level IS the label now
                           upcoming=upcoming, past=past, today=today)


@admin_bp.route('/classes/<int:class_id>/edit', methods=['GET', 'POST'])
@login_required
@require_admin
def class_edit(class_id):
    class_ = Class.query.get_or_404(class_id)
    courses = Course.query.filter_by(is_active=True).all()
    teachers = Teacher.query.join(Teacher.user).all()
    rooms = Room.query.filter_by(is_active=True).order_by(Room.branch, Room.floor, Room.room_number).all()
    semesters = Semester.query.order_by(Semester.start_date.desc()).all()
    default_semester = _get_active_semester()

    if request.method == 'POST':
        grade_select = request.form.get('grade_level_select', '').strip()
        grade_custom = request.form.get('grade_level_custom', '').strip()
        grade_level = grade_custom if grade_select == 'Loại khác' else grade_select
        new_course_id = request.form.get('course_id', type=int) or class_.course_id
        new_primary_id = request.form.get('primary_teacher_id', type=int) or None

        # Auto-update name if grade or course changed
        if grade_level and grade_level != class_.grade_level or new_course_id != class_.course_id:
            course = Course.query.get(new_course_id)
            suffix = _gen_class_suffix(grade_level or class_.grade_level, new_course_id, exclude_id=class_.id)
            class_.name = _make_class_name(grade_level or class_.grade_level, course.name if course else '', suffix)

        class_.course_id = new_course_id
        class_.grade_level = grade_level or class_.grade_level
        class_.max_students = request.form.get('max_students', type=int) or class_.max_students
        class_.monthly_fee = request.form.get('monthly_fee', type=float, default=class_.monthly_fee or 0)
        class_.sessions_per_week = request.form.get('sessions_per_week', type=int) or class_.sessions_per_week or 1
        class_.description = request.form.get('description', '').strip()
        class_.is_active = request.form.get('is_active') == '1'
        class_.primary_teacher_id = new_primary_id
        class_.assistant_teacher_id = request.form.get('assistant_teacher_id', type=int) or None

        sched_rows = _parse_sched_rows({t.id: t for t in teachers}, class_.primary_teacher_id)
        msg_extra = ''
        if sched_rows:
            semester_id = request.form.get('semester_id', type=int)
            semester = Semester.query.get(semester_id) if semester_id else default_semester
            if semester:
                created, skipped = _generate_schedules(class_.id, class_.primary_teacher_id, semester, sched_rows)
                if created:
                    msg_extra = f' Đã thêm {created} buổi học mới'
                    if skipped:
                        msg_extra += f' ({skipped} buổi bỏ qua do phòng trùng)'
                    msg_extra += '.'

        db.session.commit()
        flash(f'Đã cập nhật thông tin lớp.{msg_extra}', 'success')
        return redirect(url_for('admin.class_detail', class_id=class_id))

    return render_template('admin/classes/form.html',
                           **_form_context('edit', courses, teachers, rooms, semesters, default_semester,
                                           class_=class_))


@admin_bp.route('/classes/<int:class_id>/generate-schedule', methods=['POST'])
@login_required
@require_admin
def generate_schedule(class_id):
    class_ = Class.query.get_or_404(class_id)
    semester_id = request.form.get('semester_id', type=int)
    teacher_id = request.form.get('teacher_id', type=int)
    days_of_week = request.form.getlist('days_of_week')
    start_time_str = request.form.get('start_time', '')
    end_time_str = request.form.get('end_time', '')
    room_id = request.form.get('room_id', type=int) or None
    room_text = request.form.get('room', '').strip()

    if not semester_id or not days_of_week or not start_time_str or not end_time_str:
        flash('Vui lòng điền đầy đủ thông tin lịch học.', 'danger')
        return redirect(url_for('admin.class_detail', class_id=class_id))

    semester = Semester.query.get_or_404(semester_id)

    try:
        start_time = time_type.fromisoformat(start_time_str)
        end_time = time_type.fromisoformat(end_time_str)
    except ValueError:
        flash('Giờ học không hợp lệ.', 'danger')
        return redirect(url_for('admin.class_detail', class_id=class_id))

    if room_id and not room_text:
        r = Room.query.get(room_id)
        if r:
            room_text = r.display_name

    target_days = [int(d) for d in days_of_week]
    current = semester.start_date
    count = 0
    room_conflicts = 0

    while current <= semester.end_date:
        if current.weekday() in target_days:
            exists = Schedule.query.filter_by(
                class_id=class_id, date=current, start_time=start_time
            ).first()
            if not exists:
                if room_id and _check_room_conflict(room_id, current, start_time, end_time):
                    room_conflicts += 1
                else:
                    db.session.add(Schedule(
                        class_id=class_id, teacher_id=teacher_id,
                        date=current, start_time=start_time, end_time=end_time,
                        room=room_text, room_id=room_id,
                        schedule_type='regular', semester_id=semester_id,
                    ))
                    count += 1
        current += timedelta(days=1)

    db.session.commit()
    msg = f'Đã tạo {count} buổi học cho {class_.name}.'
    if room_conflicts:
        msg += f' Bỏ qua {room_conflicts} buổi do phòng học đã được đặt.'
    flash(msg, 'success' if count > 0 else 'warning')
    return redirect(url_for('admin.class_detail', class_id=class_id))


@admin_bp.route('/classes/<int:class_id>/add-schedule', methods=['POST'])
@login_required
@require_admin
def add_schedule(class_id):
    class_ = Class.query.get_or_404(class_id)
    teacher_id = request.form.get('teacher_id', type=int)
    date_str = request.form.get('date', '')
    start_str = request.form.get('start_time', '')
    end_str = request.form.get('end_time', '')
    room_id = request.form.get('room_id', type=int) or None
    room_text = request.form.get('room', '').strip()
    topic = request.form.get('topic', '').strip()
    schedule_type = request.form.get('schedule_type', 'regular')
    semester_id = request.form.get('semester_id', type=int)

    try:
        sched_date = date.fromisoformat(date_str)
        start_time = time_type.fromisoformat(start_str) if start_str else None
        end_time = time_type.fromisoformat(end_str) if end_str else None
    except ValueError:
        flash('Ngày hoặc giờ không hợp lệ.', 'danger')
        return redirect(url_for('admin.class_detail', class_id=class_id))

    if room_id and start_time and end_time:
        conflict = _check_room_conflict(room_id, sched_date, start_time, end_time)
        if conflict:
            room = Room.query.get(room_id)
            flash(
                f'Phòng "{room.display_name if room else room_id}" đã được đặt '
                f'vào {start_time.strftime("%H:%M")}–{end_time.strftime("%H:%M")} '
                f'ngày {sched_date.strftime("%d/%m/%Y")} (lớp {conflict.class_.name}).',
                'danger'
            )
            return redirect(url_for('admin.class_detail', class_id=class_id))

    if room_id and not room_text:
        r = Room.query.get(room_id)
        if r:
            room_text = r.display_name

    db.session.add(Schedule(
        class_id=class_id, teacher_id=teacher_id,
        date=sched_date, start_time=start_time, end_time=end_time,
        room=room_text, room_id=room_id, topic=topic,
        schedule_type=schedule_type, semester_id=semester_id,
    ))

    if schedule_type == 'intensive':
        from services.zalo_service import ZaloService
        for student in class_.active_students:
            ZaloService.send_intensive_schedule(student, None)

    db.session.commit()
    type_label = 'tăng cường' if schedule_type == 'intensive' else 'thường'
    flash(f'Đã thêm lịch {type_label} ngày {sched_date.strftime("%d/%m/%Y")}.', 'success')
    return redirect(url_for('admin.class_detail', class_id=class_id))


@admin_bp.route('/schedule/<int:schedule_id>/cancel', methods=['POST'])
@login_required
@require_admin
def cancel_schedule(schedule_id):
    schedule = Schedule.query.get_or_404(schedule_id)
    reason = request.form.get('reason', '').strip()
    schedule.is_cancelled = True
    schedule.cancel_reason = reason
    from services.zalo_service import ZaloService
    for student in schedule.class_.active_students:
        ZaloService.send_cancel_notification(student, schedule)
    db.session.commit()
    flash('Đã hủy buổi học và gửi thông báo.', 'success')
    return redirect(request.referrer or url_for('admin.class_detail', class_id=schedule.class_id))


@admin_bp.route('/schedule/<int:schedule_id>/delete', methods=['POST'])
@login_required
@require_admin
def delete_schedule(schedule_id):
    schedule = Schedule.query.get_or_404(schedule_id)
    class_id = schedule.class_id
    db.session.delete(schedule)
    db.session.commit()
    flash('Đã xóa buổi học.', 'success')
    return redirect(request.referrer or url_for('admin.class_detail', class_id=class_id))
