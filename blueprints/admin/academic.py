from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required
from datetime import date, timedelta
from extensions import db
from models import (AcademicYear, Semester, SemesterType, Student, Class, Enrollment, Schedule,
                    GRADE_SEQUENCE, GRADE_TO_LEVEL)
from blueprints.admin import admin_bp, require_admin
from blueprints.admin.classes import _generate_schedules, _semester_for_date, _make_class_name
from services.schedule_service import notify_class_teachers


def current_academic_year_start(today=None):
    """Start-year of the currently active AcademicYear, or — if none is
    marked active — the school year the given/today's date falls in
    (Jul–Jun rule, same convention as classes.py's _current_school_year_range)."""
    active = AcademicYear.query.filter_by(is_active=True).first()
    if active:
        return active.start_date.year
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


def _rollover_window_open(today=None):
    """Both grade-advancement actions ('Cuộn năm học' and 'Đồng bộ lớp học')
    only make sense once the new school year has actually started — running
    them in, say, March would advance everyone a year early. Open the
    01/07–31/12 half of the calendar, locked the rest (01/01–30/06)."""
    today = today or date.today()
    return today.month >= 7


@admin_bp.route('/academic-years')
@login_required
@require_admin
def academic_years():
    years = AcademicYear.query.order_by(AcademicYear.start_date.desc()).all()
    return render_template('admin/academic/list.html', years=years,
                           semester_types=SemesterType.LABELS,
                           rollover_window_open=_rollover_window_open())


@admin_bp.route('/academic-years/add', methods=['POST'])
@login_required
@require_admin
def academic_year_add():
    name = request.form.get('name', '').strip()
    start_str = request.form.get('start_date', '')
    end_str = request.form.get('end_date', '')

    if not name or not start_str or not end_str:
        flash('Vui lòng điền đầy đủ thông tin.', 'danger')
        return redirect(url_for('admin.academic_years'))

    start_date = date.fromisoformat(start_str)
    end_date = date.fromisoformat(end_str)
    if end_date <= start_date:
        flash('Ngày kết thúc phải sau ngày bắt đầu.', 'danger')
        return redirect(url_for('admin.academic_years'))

    ay = AcademicYear(name=name, start_date=start_date, end_date=end_date)
    db.session.add(ay)
    db.session.flush()

    # Tự động chia năm học thành 3 học kỳ bằng nhau (HK1, HK2, Hè) — chỉ
    # dùng cho mục đích thống kê, không ràng buộc việc tạo lớp học.
    third = (end_date - start_date).days // 3
    hk1_end = start_date + timedelta(days=third)
    hk2_start = hk1_end + timedelta(days=1)
    hk2_end = hk2_start + timedelta(days=third)
    he_start = hk2_end + timedelta(days=1)
    for sem_type, sem_start, sem_end in (
        (SemesterType.SEMESTER_1, start_date, hk1_end),
        (SemesterType.SEMESTER_2, hk2_start, hk2_end),
        (SemesterType.SUMMER, he_start, end_date),
    ):
        db.session.add(Semester(
            academic_year_id=ay.id,
            name=SemesterType.LABELS[sem_type],
            semester_type=sem_type,
            start_date=sem_start,
            end_date=sem_end,
        ))

    db.session.commit()
    flash(f'Đã tạo năm học {name} cùng 3 học kỳ (HK1, HK2, Hè) để thống kê.', 'success')
    return redirect(url_for('admin.academic_years'))


@admin_bp.route('/academic-years/<int:year_id>/activate', methods=['POST'])
@login_required
@require_admin
def academic_year_activate(year_id):
    # Deactivate all
    AcademicYear.query.update({'is_active': False})
    ay = AcademicYear.query.get_or_404(year_id)
    ay.is_active = True
    db.session.commit()
    flash(f'Đã kích hoạt năm học {ay.name}.', 'success')
    return redirect(url_for('admin.academic_years'))


@admin_bp.route('/semesters/add', methods=['POST'])
@login_required
@require_admin
def semester_add():
    academic_year_id = request.form.get('academic_year_id', type=int)
    name = request.form.get('name', '').strip()
    semester_type = request.form.get('semester_type', SemesterType.SEMESTER_1)
    start_str = request.form.get('start_date', '')
    end_str = request.form.get('end_date', '')

    if not all([academic_year_id, name, start_str, end_str]):
        flash('Vui lòng điền đầy đủ thông tin học kỳ.', 'danger')
        return redirect(url_for('admin.academic_years'))

    sem = Semester(
        academic_year_id=academic_year_id,
        name=name,
        semester_type=semester_type,
        start_date=date.fromisoformat(start_str),
        end_date=date.fromisoformat(end_str),
    )
    db.session.add(sem)
    db.session.commit()
    flash(f'Đã thêm học kỳ {name}.', 'success')
    return redirect(url_for('admin.academic_years'))


@admin_bp.route('/semesters/<int:sem_id>/delete', methods=['POST'])
@login_required
@require_admin
def semester_delete(sem_id):
    sem = Semester.query.get_or_404(sem_id)
    name = sem.name
    db.session.delete(sem)
    db.session.commit()
    flash(f'Đã xóa học kỳ {name}.', 'success')
    return redirect(url_for('admin.academic_years'))


def _advance_student_grades(target_year):
    """Advance every active, non-deleted student whose grade_year is behind
    target_year by that many steps through GRADE_SEQUENCE. A student who
    hasn't been baselined yet just gets grade_year stamped (not clear how
    many steps they're behind). A step that would go past 'Lớp 12' graduates
    the student (is_active=False, status='graduated') instead of clamping
    them at 'Lớp 12' forever — their current_grade/profile stay as a record.
    Students with a free-text current_grade (not in GRADE_SEQUENCE, legacy
    data) are skipped — need a one-time manual fix by an admin."""
    baselined = advanced = graduated = 0
    students = Student.query.filter(Student.is_active == True, Student.is_deleted == False).all()
    for s in students:
        if s.current_grade not in GRADE_SEQUENCE:
            continue
        if s.grade_year is None:
            s.grade_year = target_year
            baselined += 1
            continue
        if s.grade_year < target_year:
            steps = target_year - s.grade_year
            new_idx = GRADE_SEQUENCE.index(s.current_grade) + steps
            if new_idx >= len(GRADE_SEQUENCE):
                s.is_active = False
                s.status = 'graduated'
                s.grade_year = target_year
                graduated += 1
                continue
            new_grade = GRADE_SEQUENCE[new_idx]
            if new_grade != s.current_grade:
                s.current_grade = new_grade
                s.level = GRADE_TO_LEVEL[new_grade]
                advanced += 1
            s.grade_year = target_year
    return baselined, advanced, graduated


@admin_bp.route('/academic-years/sync-grades', methods=['POST'])
@login_required
@require_admin
def academic_sync_grades():
    """Đồng bộ lớp học cho năm học hiện tại — thao tác thủ công (bấm nút),
    chưa chạy tự động theo cron/queue. Xem _advance_student_grades() cho chi
    tiết logic lên lớp/tốt nghiệp."""
    if not _rollover_window_open():
        flash('Chỉ có thể lên lớp từ ngày 01/07 hàng năm.', 'danger')
        return redirect(url_for('admin.academic_years'))
    current_year = current_academic_year_start()
    baselined, advanced, graduated = _advance_student_grades(current_year)
    db.session.commit()
    msg = (f'Đã đồng bộ lớp học theo năm học hiện tại: {advanced} học sinh lên lớp, '
           f'{baselined} học sinh được gắn mốc năm học lần đầu.')
    if graduated:
        msg += f' {graduated} học sinh đã tốt nghiệp (Lớp 12).'
    flash(msg, 'success')
    return redirect(url_for('admin.academic_years'))


def _weekly_pattern(cls):
    """Latest regular, non-cancelled Schedule row per weekday for a class —
    the source pattern for rolling it into next year. Latest (not first)
    picks up a mid-year room/time change if one happened. Shape matches what
    _generate_schedules() expects: (weekday, start_str, end_str, room_id,
    room_text, teacher_id)."""
    rows = Schedule.query.filter_by(class_id=cls.id, schedule_type='regular',
                                    is_cancelled=False).order_by(Schedule.date).all()
    latest_by_weekday = {s.date.weekday(): s for s in rows}
    return [
        (wd, s.start_time.strftime('%H:%M'), s.end_time.strftime('%H:%M'),
         s.room_id, s.room, s.teacher_id)
        for wd, s in sorted(latest_by_weekday.items())
    ]


def _rollover_next_class_name(cls, next_grade):
    """Replace just the grade token at the front of the class name (e.g.
    'KHTN 8 - Cô Gấu' -> 'KHTN 9 - Cô Gấu'), preserving any custom suffix an
    admin typed in. Falls back to a freshly generated name if the class's
    name doesn't start with the expected '<course> <grade>' pattern (e.g. it
    was fully custom-named)."""
    old_short = cls.grade_level[len('Lớp '):] if cls.grade_level.startswith('Lớp ') else cls.grade_level
    new_short = next_grade[len('Lớp '):] if next_grade.startswith('Lớp ') else next_grade
    course_name = cls.course.name if cls.course else ''
    prefix_old = f'{course_name} {old_short}'.strip()
    prefix_new = f'{course_name} {new_short}'.strip()
    if cls.name.startswith(prefix_old):
        return prefix_new + cls.name[len(prefix_old):]
    return _make_class_name(course_name, next_grade, cls.primary_teacher)


def _rollover_plan():
    """What a 'Cuộn năm học' run would do, computed fresh every time (never
    cached/trusted across requests) so the preview page and the execute
    route can't drift apart."""
    current_year = current_academic_year_start()
    next_year = current_year + 1
    next_start = date(next_year, 7, 1)
    already_rolled = Class.query.filter_by(start_date=next_start).first() is not None
    active = Class.query.filter_by(is_active=True).all()
    rolling = [c for c in active if c.grade_level in GRADE_SEQUENCE and c.grade_level != 'Lớp 12']
    lop12 = [c for c in active if c.grade_level == 'Lớp 12']
    manual = [c for c in active if c.grade_level not in GRADE_SEQUENCE]
    graduating = Student.query.filter_by(current_grade='Lớp 12', is_active=True, is_deleted=False).all()
    return dict(current_year=current_year, next_year=next_year, already_rolled=already_rolled,
               rolling=rolling, lop12=lop12, manual=manual, graduating=graduating)


@admin_bp.route('/academic-years/rollover')
@login_required
@require_admin
def academic_year_rollover_preview():
    if not _rollover_window_open():
        flash('Chỉ có thể cuộn năm học từ ngày 01/07 hàng năm.', 'danger')
        return redirect(url_for('admin.academic_years'))
    plan = _rollover_plan()
    rolling_info = [
        (cls, GRADE_SEQUENCE[GRADE_SEQUENCE.index(cls.grade_level) + 1],
         _rollover_next_class_name(cls, GRADE_SEQUENCE[GRADE_SEQUENCE.index(cls.grade_level) + 1]),
         cls.current_enrollment)
        for cls in plan['rolling']
    ]
    return render_template('admin/academic/rollover_preview.html', plan=plan, rolling_info=rolling_info)


@admin_bp.route('/academic-years/rollover', methods=['POST'])
@login_required
@require_admin
def academic_year_rollover_execute():
    if not _rollover_window_open():
        flash('Chỉ có thể cuộn năm học từ ngày 01/07 hàng năm.', 'danger')
        return redirect(url_for('admin.academic_years'))
    plan = _rollover_plan()
    if plan['already_rolled']:
        flash('Năm học tới đã được cuộn rồi — không thể cuộn lại.', 'danger')
        return redirect(url_for('admin.academic_years'))

    next_year = plan['next_year']
    new_start = date(next_year, 7, 1)
    new_end = date(next_year + 1, 6, 30)
    graduating_ids = {s.id for s in plan['graduating']}

    classes_rolled = 0
    for cls in plan['rolling']:
        next_grade = GRADE_SEQUENCE[GRADE_SEQUENCE.index(cls.grade_level) + 1]
        new_name = _rollover_next_class_name(cls, next_grade)
        sched_rows = _weekly_pattern(cls)

        new_cls = Class(
            name=new_name,
            course_id=cls.course_id,
            grade_level=next_grade,
            max_students=cls.max_students,
            monthly_fee=cls.monthly_fee,
            sessions_per_week=len(sched_rows) or cls.sessions_per_week,
            description=cls.description,
            primary_teacher_id=cls.primary_teacher_id,
            start_date=new_start,
            end_date=new_end,
        )
        db.session.add(new_cls)
        db.session.flush()
        new_cls.assistant_teachers = list(cls.assistant_teachers)

        semester = _semester_for_date(new_start)
        _generate_schedules(new_cls.id, new_start, new_end, sched_rows,
                            semester_id=semester.id if semester else None)

        for e in cls.enrollments.filter_by(is_active=True).all():
            if e.student_id in graduating_ids:
                continue
            db.session.add(Enrollment(student_id=e.student_id, class_id=new_cls.id))

        notify_class_teachers(new_cls, 'Lịch học mới',
                              f'Lớp {cls.name} đã được cuộn sang năm học mới: {new_cls.name}.',
                              link=url_for('teacher.schedule'))
        classes_rolled += 1

    for cls in plan['rolling'] + plan['lop12'] + plan['manual']:
        cls.is_active = False

    baselined, advanced, graduated = _advance_student_grades(next_year)

    db.session.commit()
    flash(f'Đã cuộn năm học: {classes_rolled} lớp được tạo mới, {advanced} học sinh lên lớp, '
          f'{graduated} học sinh tốt nghiệp, {baselined} học sinh được gắn mốc năm học lần đầu.',
          'success')
    return redirect(url_for('admin.academic_years'))
