from flask import render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import login_required
from datetime import date, timedelta, time as time_type
from sqlalchemy import or_, and_
from extensions import db
from models import (Class, Course, Teacher, Schedule, Semester, Enrollment, Student, Room,
                    TuitionPayment, GRADE_BY_LEVEL, GRADE_SEQUENCE, User,
                    Attendance, AttendanceSummary)
from blueprints.admin import admin_bp, require_admin
from services.schedule_service import (find_student_schedule_conflict, schedule_conflict_message,
                                       notify_class_teachers)
from services.tuition_service import create_tuition_payment
from services.academic_year_service import is_period_writable

# ── Constants ──────────────────────────────────────────────────────────────

ALL_GRADES = GRADE_SEQUENCE + ['Loại khác']

GRADE_LEVEL_OPTIONS = [(g, g) for g in ALL_GRADES]
GRADE_LEVEL_LABELS = {g: g for g in ALL_GRADES}

def _generate_time_points(start='07:00', end='23:45', step_minutes=15):
    """15-phút một mốc, từ 07:00 đến 23:45, dùng cho các dropdown "Từ"/"Đến"
    của khung giờ học. Giờ kết thúc mặc định tự cộng thêm 90 phút ở phía JS,
    nhưng admin có thể chọn lại giờ kết thúc khác trong danh sách này."""
    points = []
    h, m = map(int, start.split(':'))
    eh, em = map(int, end.split(':'))
    cur = h * 60 + m
    end_total = eh * 60 + em
    while cur <= end_total:
        points.append(f'{cur // 60:02d}:{cur % 60:02d}')
        cur += step_minutes
    return points


# All time points (07:00–23:45, mỗi 15 phút), dùng cho các dropdown "Từ"/"Đến"
TIME_POINTS = _generate_time_points()

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


def _teacher_busy_conflict(teacher_id, sched_date, start_time, end_time,
                           exclude_schedule_id=None, exclude_class_id=None):
    """Return the Schedule that makes teacher_id busy at this date/time, if any.
    Busy = teacher is the effective teacher for that session: either the regular
    assignment with no substitute covering it, or they are the substitute
    covering someone else's session."""
    q = Schedule.query.filter(
        Schedule.is_cancelled == False,
        Schedule.date == sched_date,
        Schedule.start_time < end_time,
        Schedule.end_time > start_time,
        or_(
            and_(Schedule.teacher_id == teacher_id, Schedule.substitute_teacher_id.is_(None)),
            Schedule.substitute_teacher_id == teacher_id,
        ),
    )
    if exclude_schedule_id:
        q = q.filter(Schedule.id != exclude_schedule_id)
    if exclude_class_id:
        q = q.filter(Schedule.class_id != exclude_class_id)
    return q.first()


def _find_teacher_conflict(start_date, end_date, sched_rows, exclude_class_id=None):
    """Return the first existing Schedule that conflicts with any row's own
    assigned teacher (rows can carry different teachers when a class has a
    trợ giảng), checked across [start_date, end_date]. Fetches all of those
    teachers' schedules in that range with a single query instead of one per
    day, since day-by-day queries over a full school year against a remote DB
    are what caused request timeouts (502) on class creation."""
    if not sched_rows:
        return None
    teacher_ids = {t for (_, _, _, _, _, t) in sched_rows if t}
    if not teacher_ids:
        return None
    q = Schedule.query.filter(
        Schedule.is_cancelled == False,
        Schedule.date >= start_date,
        Schedule.date <= end_date,
        or_(
            and_(Schedule.teacher_id.in_(teacher_ids), Schedule.substitute_teacher_id.is_(None)),
            Schedule.substitute_teacher_id.in_(teacher_ids),
        ),
    )
    if exclude_class_id:
        q = q.filter(Schedule.class_id != exclude_class_id)

    slots_by_teacher = {}
    for (wd, s, e, _, _, t) in sched_rows:
        if not t:
            continue
        slots_by_teacher.setdefault(t, []).append((wd, time_type.fromisoformat(s), time_type.fromisoformat(e)))

    for sched in q.all():
        busy_teacher_id = sched.substitute_teacher_id or sched.teacher_id
        slots = slots_by_teacher.get(busy_teacher_id)
        if not slots:
            continue
        wd = sched.date.weekday()
        for (target_wd, start_t, end_t) in slots:
            if wd == target_wd and sched.start_time < end_t and sched.end_time > start_t:
                return sched
    return None


def _class_subject_label(cls):
    """Short label like 'Hoá 8' (course name + short grade), for conflict messages."""
    course_name = cls.course.name if cls.course else ''
    grade_level = cls.grade_level or ''
    grade_short = grade_level[len('Lớp '):] if grade_level.startswith('Lớp ') else grade_level
    return f'{course_name} {grade_short}'.strip()


def _conflict_message(teacher, conflict_schedule):
    label = _class_subject_label(conflict_schedule.class_)
    date_str = conflict_schedule.date.strftime('%d/%m/%Y')
    return f'{teacher.display_name} có lịch dạy {label} ngày {date_str}.'


def _current_school_year_range(today=None):
    """01/07–30/06 school year containing `today` (defaults to today)."""
    today = today or date.today()
    if today.month >= 7:
        return date(today.year, 7, 1), date(today.year + 1, 6, 30)
    return date(today.year - 1, 7, 1), date(today.year, 6, 30)


def _semester_for_date(d):
    """Return the semester overlapping date d, if any (for stats tagging only)."""
    return Semester.query.filter(
        Semester.start_date <= d,
        Semester.end_date >= d,
    ).first()


def _generate_schedules(class_id, start_date, end_date, sched_rows, semester_id=None):
    """
    Generate Schedule rows for each (weekday, start_time, end_time, room_id, room_text,
    teacher_id) entry across [start_date, end_date]. Skip conflicts. Return
    (created, skipped_conflict) counts. Each row carries its own teacher_id
    (a class with a trợ giảng can split sessions between the two teachers).
    semester_id is optional metadata, kept only for future statistics.

    Existing class schedules and room bookings in the date range are fetched with
    two queries up front (instead of two queries per matching day) — day-by-day
    queries over a full school year against a remote DB were what caused request
    timeouts (502) when creating a class.
    """
    created = 0
    skipped = 0
    if not sched_rows:
        return created, skipped

    existing_keys = {
        (s.date, s.start_time)
        for s in Schedule.query.filter(
            Schedule.class_id == class_id,
            Schedule.date >= start_date,
            Schedule.date <= end_date,
        ).all()
    }

    room_ids = {room_id for (_, _, _, room_id, _, _) in sched_rows if room_id}
    room_bookings = {}
    if room_ids:
        for s in Schedule.query.filter(
            Schedule.room_id.in_(room_ids),
            Schedule.date >= start_date,
            Schedule.date <= end_date,
            Schedule.is_cancelled == False,
        ).all():
            room_bookings.setdefault(s.room_id, []).append((s.date, s.start_time, s.end_time))

    current = start_date
    while current <= end_date:
        wd = current.weekday()
        for (target_wd, start_str, end_str, room_id, room_text, teacher_id) in sched_rows:
            if wd == target_wd:
                start_t = time_type.fromisoformat(start_str)
                end_t = time_type.fromisoformat(end_str)
                if (current, start_t) in existing_keys:
                    continue
                if room_id and any(
                    b_date == current and b_start < end_t and b_end > start_t
                    for (b_date, b_start, b_end) in room_bookings.get(room_id, [])
                ):
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
                    semester_id=semester_id,
                )
                db.session.add(s)
                created += 1
                existing_keys.add((current, start_t))
                if room_id:
                    room_bookings.setdefault(room_id, []).append((current, start_t, end_t))
        current += timedelta(days=1)
    return created, skipped


def _make_class_name(course_name, grade_level, teacher):
    """Build display name like 'Toán 5 - Cô Gấu' (môn học + lớp - Thầy/Cô + tên giáo viên)."""
    grade_short = grade_level[len('Lớp '):] if grade_level and grade_level.startswith('Lớp ') else (grade_level or '')
    left = f'{course_name} {grade_short}'.strip()
    if teacher:
        given_name = (teacher.full_name or '').strip().split(' ')[-1]
        right = f'{teacher.title} {given_name}'.strip()
    else:
        right = ''
    return f'{left} - {right}' if right else left


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

    # One batched fetch of every candidate class's schedules instead of one
    # query per (class, schedule-row) pair.
    schedules_by_class = {}
    for s in Schedule.query.filter(
        Schedule.class_id.in_([cls.id for cls in existing]),
        Schedule.is_cancelled == False,
    ).all():
        schedules_by_class.setdefault(s.class_id, []).append(s)

    for cls in existing:
        for (wd, start_str, end_str, room_id, room_text, row_teacher_id) in sched_rows:
            start_t = time_type.fromisoformat(start_str)
            for sched in schedules_by_class.get(cls.id, []):
                if sched.start_time == start_t and sched.date.weekday() == wd:
                    return cls
    return None


def _parse_sched_rows(allowed_teacher_ids, default_teacher_id):
    """Parse schedule rows from POST form data. "Từ"/"Đến" are independent
    dropdowns (Đến only auto-fills client-side, admin can override it).
    Each row may carry its own teacher_id (sched_teacher_id[]) — only
    meaningful when the class has a trợ giảng, letting sessions be split
    between the giáo viên chính and trợ giảng. Falls back to
    default_teacher_id (the primary teacher) when absent or not one of the
    allowed teachers for this class."""
    days = request.form.getlist('sched_day[]')
    starts = request.form.getlist('sched_start[]')
    ends = request.form.getlist('sched_end[]')
    room_ids_raw = request.form.getlist('sched_room_id[]')
    teacher_ids_raw = request.form.getlist('sched_teacher_id[]')
    rows = []
    rooms_by_id = {r.id: r for r in Room.query.all()}
    for i in range(len(days)):
        try:
            wd = int(days[i])
        except (ValueError, IndexError):
            continue
        start_str = starts[i] if i < len(starts) else ''
        end_str = ends[i] if i < len(ends) else ''
        if start_str not in TIME_POINTS or end_str not in TIME_POINTS or end_str <= start_str:
            continue
        try:
            room_id = int(room_ids_raw[i]) if i < len(room_ids_raw) and room_ids_raw[i] else None
        except ValueError:
            room_id = None
        room_text = rooms_by_id[room_id].display_name if room_id and room_id in rooms_by_id else ''
        try:
            row_teacher_id = int(teacher_ids_raw[i]) if i < len(teacher_ids_raw) and teacher_ids_raw[i] else None
        except ValueError:
            row_teacher_id = None
        if row_teacher_id not in allowed_teacher_ids:
            row_teacher_id = default_teacher_id
        rows.append((wd, start_str, end_str, room_id, room_text, row_teacher_id))
    return rows


def _suggested_students(cls):
    """Students in the same grade as cls (exact match on the canonical grade
    label), not already actively enrolled in any class sharing cls.course_id
    (i.e. not already taking that subject). Classes with a non-canonical
    grade_level (e.g. "Loại khác") skip the grade filter entirely."""
    grade_filter = cls.grade_level if cls.grade_level in GRADE_SEQUENCE else None
    already_ids = {
        e.student_id for e in
        Enrollment.query.join(Class, Enrollment.class_id == Class.id)
        .filter(Class.course_id == cls.course_id, Enrollment.is_active == True).all()
    }
    query = Student.query.filter(Student.is_active == True, Student.is_deleted == False)
    if grade_filter:
        query = query.filter(Student.current_grade == grade_filter)
    students = query.order_by(Student.full_name).all()
    return [s for s in students if s.id not in already_ids]


# ── Routes ─────────────────────────────────────────────────────────────────

def _form_context(action, courses, teachers, rooms, form=None, class_=None):
    return dict(
        action=action, courses=courses, teachers=teachers, rooms=rooms,
        grade_options=GRADE_LEVEL_OPTIONS,
        time_points=TIME_POINTS, day_options=DAY_OPTIONS,
        form=form, class_=class_,
    )


@admin_bp.route('/classes')
@login_required
@require_admin
def classes():
    q = request.args.get('q', '').strip()
    course_id = request.args.get('course_id', type=int)
    grade_level = request.args.get('grade_level', '')
    teacher_id = request.args.get('teacher_id', type=int)

    query = Class.query
    if course_id:
        query = query.filter(Class.course_id == course_id)
    if grade_level:
        query = query.filter(Class.grade_level == grade_level)
    if teacher_id:
        query = query.filter(Class.primary_teacher_id == teacher_id)
    if q:
        query = (query
                .outerjoin(Course, Class.course_id == Course.id)
                .outerjoin(Teacher, Class.primary_teacher_id == Teacher.id)
                .outerjoin(User, Teacher.user_id == User.id)
                .filter(db.or_(
                    Class.name.ilike(f'%{q}%'),
                    Class.grade_level.ilike(f'%{q}%'),
                    Class.description.ilike(f'%{q}%'),
                    Course.name.ilike(f'%{q}%'),
                    User.full_name.ilike(f'%{q}%'),
                )))
    page = request.args.get('page', 1, type=int)
    pagination = query.order_by(Class.name).paginate(page=page, per_page=30, error_out=False)
    classes = pagination.items

    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()
    teachers = Teacher.query.join(Teacher.user).order_by('full_name').all()
    grade_rows = db.session.query(Class.grade_level).distinct().all()
    grade_options = sorted(
        {row[0] for row in grade_rows if row[0]},
        key=lambda g: GRADE_SEQUENCE.index(g) if g in GRADE_SEQUENCE else len(GRADE_SEQUENCE)
    )

    is_filtered = bool(q or course_id or grade_level or teacher_id)

    return render_template('admin/classes/list.html',
                           classes=classes, q=q, course_id=course_id,
                           grade_level=grade_level, teacher_id=teacher_id,
                           courses=courses, teachers=teachers, grade_options=grade_options,
                           is_filtered=is_filtered, pagination=pagination,
                           grade_labels=GRADE_LEVEL_LABELS)


@admin_bp.route('/classes/add', methods=['GET', 'POST'])
@login_required
@require_admin
def class_add():
    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()
    teachers = Teacher.query.join(Teacher.user).order_by('full_name').all()
    rooms = Room.query.filter_by(is_active=True).order_by(Room.branch, Room.floor, Room.room_number).all()

    if request.method == 'POST':
        # Grade level: select value or custom text for "Loại khác"
        grade_select = request.form.get('grade_level_select', '').strip()
        grade_custom = request.form.get('grade_level_custom', '').strip()
        grade_level = grade_custom if grade_select == 'Loại khác' else grade_select

        course_id = request.form.get('course_id', type=int)
        primary_teacher_id = request.form.get('primary_teacher_id', type=int) or None
        assistant_teacher_ids = [int(x) for x in request.form.getlist('assistant_teacher_ids[]') if x]
        max_students = request.form.get('max_students', type=int) or None
        monthly_fee = request.form.get('monthly_fee', 0, type=float)
        description = request.form.get('description', '').strip()
        start_date, end_date = _current_school_year_range()

        allowed_teacher_ids = {tid for tid in [primary_teacher_id, *assistant_teacher_ids] if tid}
        sched_rows = _parse_sched_rows(allowed_teacher_ids, primary_teacher_id)
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
        elif sessions_per_week != len(sched_rows):
            errors.append('Vui lòng kiểm tra lại Lịch học.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('admin/classes/form.html',
                                   **_form_context('add', courses, teachers, rooms, form=request.form))

        # Duplicate slot check
        dup = _has_duplicate_slot(grade_level, course_id, primary_teacher_id, sched_rows)
        if dup:
            flash(f'Giáo viên đã dạy lớp "{dup.name}" (cùng lớp, cùng môn) ở khung giờ này.', 'danger')
            return render_template('admin/classes/form.html',
                                   **_form_context('add', courses, teachers, rooms, form=request.form))

        # Teacher availability check from today onward — a past session that
        # already happened can't actually double-book anyone, so don't let
        # it block creating a new class (start_date is the school year's
        # start, which can itself be in the past relative to today).
        primary_teacher = Teacher.query.get(primary_teacher_id)
        conflict = _find_teacher_conflict(max(date.today(), start_date), end_date, sched_rows)
        if conflict:
            flash(_conflict_message(conflict.effective_teacher, conflict), 'danger')
            return render_template('admin/classes/form.html',
                                   **_form_context('add', courses, teachers, rooms, form=request.form))

        # Tên lớp: dùng tên admin nhập nếu có, không thì tự sinh như trước.
        course = Course.query.get(course_id)
        custom_name = request.form.get('name', '').strip()
        name = custom_name or _make_class_name(course.name if course else '', grade_level, primary_teacher)

        cl = Class(
            name=name,
            course_id=course_id,
            grade_level=grade_level,
            max_students=max_students,
            monthly_fee=monthly_fee,
            sessions_per_week=sessions_per_week,
            description=description,
            primary_teacher_id=primary_teacher_id,
            start_date=start_date,
            end_date=end_date,
        )
        db.session.add(cl)
        db.session.flush()
        if assistant_teacher_ids:
            cl.assistant_teachers = Teacher.query.filter(Teacher.id.in_(assistant_teacher_ids)).all()

        # Học kỳ chỉ được gắn tự động cho mục đích thống kê, không bắt buộc chọn.
        semester = _semester_for_date(start_date)
        created, skipped = _generate_schedules(cl.id, start_date, end_date, sched_rows,
                                               semester_id=semester.id if semester else None)
        msg_extra = f' Đã tạo {created} buổi học'
        if skipped:
            msg_extra += f' ({skipped} buổi bỏ qua do phòng trùng)'
        msg_extra += '.'

        if created:
            notify_class_teachers(cl, 'Lịch học mới',
                                  f'Đã tạo {created} buổi học mới cho lớp {cl.name}.',
                                  link=url_for('teacher.schedule'))

        db.session.commit()
        flash(f'Đã tạo lớp {name}.{msg_extra}', 'success')
        return redirect(url_for('admin.class_detail', class_id=cl.id))

    return render_template('admin/classes/form.html',
                           **_form_context('add', courses, teachers, rooms, form={}))


@admin_bp.route('/classes/detail/<int:class_id>')
@login_required
@require_admin
def class_detail(class_id):
    class_ = Class.query.get_or_404(class_id)
    teachers = Teacher.query.join(Teacher.user).order_by('full_name').all()
    rooms = Room.query.filter_by(is_active=True).order_by(Room.branch, Room.floor, Room.room_number).all()
    today = date.today()

    upcoming_schedules = class_.schedules.filter(
        Schedule.date >= today, Schedule.is_cancelled == False
    ).order_by(Schedule.date, Schedule.start_time).all()

    # Khung giờ học hàng tuần đang áp dụng (dựa trên buổi sắp tới, chưa hủy) —
    # dùng để hiển thị "Lịch học" gọn theo tuần thay vì liệt kê từng ngày cả năm.
    weekly_pattern = {}
    for s in upcoming_schedules:
        key = (s.date.weekday(), s.start_time, s.end_time, s.room_id, s.teacher_id)
        weekly_pattern[key] = s
    weekly_slots = sorted(weekly_pattern.values(), key=lambda s: (s.date.weekday(), s.start_time))

    return render_template('admin/classes/detail.html',
                           class_=class_, teachers=teachers, rooms=rooms,
                           weekly_slots=weekly_slots,
                           suggested_students=_suggested_students(class_),
                           grade_label=GRADE_LEVEL_LABELS.get(class_.grade_level, class_.grade_level or ''),
                           day_options=DAY_OPTIONS, time_points=TIME_POINTS,
                           today=today)


@admin_bp.route('/classes/<int:class_id>/edit', methods=['GET', 'POST'])
@login_required
@require_admin
def class_edit(class_id):
    class_ = Class.query.get_or_404(class_id)
    courses = Course.query.filter_by(is_active=True).all()
    teachers = Teacher.query.join(Teacher.user).all()
    rooms = Room.query.filter_by(is_active=True).order_by(Room.branch, Room.floor, Room.room_number).all()

    if request.method == 'POST':
        grade_select = request.form.get('grade_level_select', '').strip()
        grade_custom = request.form.get('grade_level_custom', '').strip()
        grade_level = grade_custom if grade_select == 'Loại khác' else grade_select
        new_course_id = request.form.get('course_id', type=int) or class_.course_id
        new_primary_id = request.form.get('primary_teacher_id', type=int) or None

        # Tên lớp: admin có thể tự sửa trực tiếp (ngoài tên hệ thống tự đặt lúc
        # tạo lớp). Chỉ tự sinh lại tên khi admin để trống ô này.
        custom_name = request.form.get('name', '').strip()
        if custom_name:
            class_.name = custom_name
        elif (grade_level and grade_level != class_.grade_level) or new_course_id != class_.course_id \
                or new_primary_id != class_.primary_teacher_id:
            course = Course.query.get(new_course_id)
            primary_teacher = Teacher.query.get(new_primary_id)
            class_.name = _make_class_name(course.name if course else '', grade_level or class_.grade_level, primary_teacher)

        # Đổi giáo viên chính phải kéo theo các buổi học TỪ HÔM NAY trở đi vẫn
        # đang gán cho giáo viên cũ — nếu không, Schedule.teacher_id cũ vẫn
        # còn đó và làm giáo viên cũ bị coi là "bận" ở khung giờ đó khi tạo
        # lớp khác, dù họ đã được thay thế trên lớp này. Buổi đã qua giữ
        # nguyên (lịch sử), và buổi đang có người dạy thay (assistant) không
        # bị đụng tới — chỉ những buổi vẫn còn gán đúng giáo viên chính cũ.
        old_primary_id = class_.primary_teacher_id
        if new_primary_id != old_primary_id and old_primary_id:
            Schedule.query.filter(
                Schedule.class_id == class_id,
                Schedule.teacher_id == old_primary_id,
                Schedule.date >= date.today(),
            ).update({'teacher_id': new_primary_id}, synchronize_session=False)

        class_.course_id = new_course_id
        class_.grade_level = grade_level or class_.grade_level
        class_.max_students = request.form.get('max_students', type=int) or class_.max_students
        class_.monthly_fee = request.form.get('monthly_fee', type=float, default=class_.monthly_fee or 0)
        class_.sessions_per_week = request.form.get('sessions_per_week', type=int) or class_.sessions_per_week or 1
        class_.description = request.form.get('description', '').strip()
        class_.is_active = request.form.get('is_active') == '1'
        class_.primary_teacher_id = new_primary_id
        assistant_teacher_ids = [int(x) for x in request.form.getlist('assistant_teacher_ids[]') if x]
        class_.assistant_teachers = Teacher.query.filter(Teacher.id.in_(assistant_teacher_ids)).all() if assistant_teacher_ids else []

        db.session.commit()
        flash('Đã cập nhật thông tin lớp.', 'success')
        return redirect(url_for('admin.class_detail', class_id=class_id))

    return render_template('admin/classes/form.html',
                           **_form_context('edit', courses, teachers, rooms, class_=class_))


@admin_bp.route('/classes/<int:class_id>/reschedule', methods=['POST'])
@login_required
@require_admin
def class_reschedule(class_id):
    """Thay đổi khung giờ học hàng tuần. Chỉ xóa/tạo lại các buổi TỪ HÔM NAY trở
    đi — các buổi đã qua giữ nguyên, không bị ảnh hưởng."""
    class_ = Class.query.get_or_404(class_id)
    allowed_teacher_ids = {tid for tid in [class_.primary_teacher_id, *[t.id for t in class_.assistant_teachers]] if tid}
    sched_rows = _parse_sched_rows(allowed_teacher_ids, class_.primary_teacher_id)

    if not sched_rows:
        flash('Vui lòng thêm ít nhất một khung giờ học.', 'danger')
        return redirect(url_for('admin.class_detail', class_id=class_id))

    today = date.today()
    range_start = max(today, class_.start_date) if class_.start_date else today
    range_end = class_.end_date or today

    conflict = _find_teacher_conflict(range_start, range_end, sched_rows, exclude_class_id=class_id)
    if conflict:
        flash(_conflict_message(conflict.effective_teacher, conflict), 'danger')
        return redirect(url_for('admin.class_detail', class_id=class_id))

    # Xóa các buổi học từ hôm nay trở đi (chưa hủy) — không đụng dữ liệu đã qua.
    # Xóa hàng loạt (bulk) thay vì từng dòng một: với cả năm học, xóa từng
    # Schedule qua ORM tốn một round-trip riêng mỗi dòng tới DB ở xa, dễ vượt
    # timeout của server (502) — bulk delete chỉ tốn vài câu lệnh cố định.
    future_schedule_ids = [row[0] for row in db.session.query(Schedule.id).filter(
        Schedule.class_id == class_id,
        Schedule.date >= today,
        Schedule.is_cancelled == False,
    ).all()]
    if future_schedule_ids:
        Attendance.query.filter(Attendance.schedule_id.in_(future_schedule_ids)).delete(synchronize_session=False)
        AttendanceSummary.query.filter(AttendanceSummary.schedule_id.in_(future_schedule_ids)).delete(synchronize_session=False)
        Schedule.query.filter(Schedule.id.in_(future_schedule_ids)).delete(synchronize_session=False)

    semester = _semester_for_date(range_start)
    created, skipped = _generate_schedules(class_id, range_start, range_end, sched_rows,
                                           semester_id=semester.id if semester else None)

    if created:
        notify_class_teachers(class_, 'Lịch học mới',
                              f'Lịch học lớp {class_.name} đã được cập nhật: {created} buổi học mới.',
                              link=url_for('teacher.schedule'))

    db.session.commit()
    msg = f'Đã cập nhật lịch học: {created} buổi học mới từ {range_start.strftime("%d/%m/%Y")}.'
    if skipped:
        msg += f' ({skipped} buổi bỏ qua do phòng trùng)'
    flash(msg, 'success')
    return redirect(url_for('admin.class_detail', class_id=class_id))


@admin_bp.route('/classes/<int:class_id>/schedule/delete-weekly', methods=['POST'])
@login_required
@require_admin
def class_delete_weekly_slot(class_id):
    """Xóa các buổi học TƯƠNG LAI (chưa hủy) của MỘT khung giờ trong tuần —
    xác định qua schedule_id đại diện — không đụng các khung giờ khác hay
    dữ liệu quá khứ."""
    ref_id = request.form.get('schedule_id', type=int)
    ref = Schedule.query.get_or_404(ref_id)
    if ref.class_id != class_id:
        abort(404)

    today = date.today()
    weekday, start_t, end_t = ref.date.weekday(), ref.start_time, ref.end_time

    future_schedules = Schedule.query.filter(
        Schedule.class_id == class_id,
        Schedule.date >= today,
        Schedule.is_cancelled == False,
    ).all()
    match_ids = [s.id for s in future_schedules
                 if s.date.weekday() == weekday and s.start_time == start_t and s.end_time == end_t]
    deleted = len(match_ids)
    if match_ids:
        Attendance.query.filter(Attendance.schedule_id.in_(match_ids)).delete(synchronize_session=False)
        AttendanceSummary.query.filter(AttendanceSummary.schedule_id.in_(match_ids)).delete(synchronize_session=False)
        Schedule.query.filter(Schedule.id.in_(match_ids)).delete(synchronize_session=False)

    db.session.commit()
    flash(f'Đã xóa {deleted} buổi học sắp tới của khung giờ này.', 'success')
    return redirect(url_for('admin.class_detail', class_id=class_id))


# Tạm ẩn: chức năng phân công dạy thay sẽ cập nhật lại sau.
# @admin_bp.route('/classes/<int:class_id>/schedule/substitute', methods=['POST'])
# @login_required
# @require_admin
# def schedule_substitute(class_id):
#     """Phân công (hoặc hủy) giáo viên dạy thay cho một hoặc nhiều buổi học sắp tới."""
#     schedule_ids = [int(x) for x in request.form.getlist('schedule_ids') if x]
#     substitute_teacher_id = request.form.get('substitute_teacher_id', type=int)
#
#     if not schedule_ids:
#         flash('Vui lòng chọn ít nhất một buổi học.', 'danger')
#         return redirect(url_for('admin.class_detail', class_id=class_id))
#
#     schedules = Schedule.query.filter(
#         Schedule.id.in_(schedule_ids),
#         Schedule.class_id == class_id,
#         Schedule.date >= date.today(),
#     ).all()
#
#     if substitute_teacher_id:
#         substitute = Teacher.query.get_or_404(substitute_teacher_id)
#         for s in schedules:
#             conflict = _teacher_busy_conflict(
#                 substitute_teacher_id, s.date, s.start_time, s.end_time, exclude_schedule_id=s.id
#             )
#             if conflict:
#                 flash(_conflict_message(substitute, conflict), 'danger')
#                 return redirect(url_for('admin.class_detail', class_id=class_id))
#         for s in schedules:
#             s.substitute_teacher_id = substitute_teacher_id
#         db.session.commit()
#         flash(f'Đã phân công {substitute.display_name} dạy thay cho {len(schedules)} buổi học.', 'success')
#     else:
#         for s in schedules:
#             s.substitute_teacher_id = None
#         db.session.commit()
#         flash(f'Đã hủy phân công dạy thay cho {len(schedules)} buổi học.', 'success')
#
#     return redirect(url_for('admin.class_detail', class_id=class_id))


@admin_bp.route('/classes/<int:class_id>/add-students', methods=['POST'])
@login_required
@require_admin
def class_add_students(class_id):
    """Ghi danh hàng loạt học sinh được gợi ý (cùng khối, chưa học môn này), và
    tự tạo học phí tháng hiện tại theo học phí chuẩn của lớp."""
    class_ = Class.query.get_or_404(class_id)
    student_ids = [int(x) for x in request.form.getlist('student_ids') if x]

    if not student_ids:
        flash('Vui lòng chọn ít nhất một học sinh.', 'danger')
        return redirect(url_for('admin.class_detail', class_id=class_id))

    # A schedule-conflicted student is skipped, not a reason to abort the
    # whole batch — everyone else selected still gets added normally.
    students = Student.query.filter(Student.id.in_(student_ids)).all()
    ok_student_ids = []
    for student in students:
        conflict = find_student_schedule_conflict(student, class_)
        if conflict:
            flash(schedule_conflict_message(student, class_, conflict), 'danger')
        else:
            ok_student_ids.append(student.id)

    if not ok_student_ids:
        return redirect(url_for('admin.class_detail', class_id=class_id))

    today = date.today()

    # Batch the existing-enrollment / existing-tuition-row checks into one
    # query each instead of one per student.
    existing_enrollments = {
        e.student_id: e for e in
        Enrollment.query.filter(Enrollment.student_id.in_(ok_student_ids), Enrollment.class_id == class_id).all()
    }
    students_with_tuition = {
        t.student_id for t in TuitionPayment.query.filter(
            TuitionPayment.student_id.in_(ok_student_ids), TuitionPayment.class_id == class_id,
            TuitionPayment.month == today.month, TuitionPayment.year == today.year,
        ).all()
    }
    # If the current month somehow isn't the active academic year (no
    # AcademicYear configured for "now"), skip auto-creating tuition
    # rather than raising mid-loop — enrollment itself should still
    # succeed; the school just needs to set up this year's AcademicYear.
    can_bill_this_month = is_period_writable(today.month, today.year)

    added = tuition_added = 0
    for student_id in ok_student_ids:
        existing = existing_enrollments.get(student_id)
        if existing:
            if not existing.is_active:
                existing.is_active = True
                added += 1
        else:
            db.session.add(Enrollment(student_id=student_id, class_id=class_id))
            added += 1

        if can_bill_this_month and student_id not in students_with_tuition:
            _, was_created = create_tuition_payment(
                student_id, class_id, today.month, today.year, class_.monthly_fee or 0,
                note='Tự động tạo khi thêm vào lớp',
            )
            if was_created:
                tuition_added += 1

    if added:
        notify_class_teachers(class_, 'Học sinh mới',
                              f'{added} học sinh mới được thêm vào lớp {class_.name}.',
                              link=url_for('teacher.scores_list'))

    db.session.commit()
    msg = f'Đã thêm {added} học sinh vào lớp {class_.name}.'
    if tuition_added:
        msg += f' Đã tạo {tuition_added} bản ghi học phí tháng {today.month}/{today.year}.'
    flash(msg, 'success')
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

    semester = _semester_for_date(sched_date)
    db.session.add(Schedule(
        class_id=class_id, teacher_id=teacher_id,
        date=sched_date, start_time=start_time, end_time=end_time,
        room=room_text, room_id=room_id, topic=topic,
        schedule_type=schedule_type, semester_id=semester.id if semester else None,
    ))

    if schedule_type == 'intensive':
        from services.zalo_service import ZaloService
        for student in class_.active_students:
            ZaloService.send_intensive_schedule(student, None)

    notify_class_teachers(class_, 'Lịch học mới',
                          f'Đã thêm 1 buổi học mới cho lớp {class_.name} ngày {sched_date.strftime("%d/%m/%Y")}.',
                          link=url_for('teacher.schedule'))

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
