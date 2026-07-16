from flask import Blueprint, render_template, request, jsonify, current_app, send_from_directory
from datetime import date, timedelta
from sqlalchemy.orm import joinedload, contains_eager
from models import Schedule, Class, Course, Score, SystemConfig, StudentLevel, ContactInquiry, Student, School, Reward
from extensions import db

public_bp = Blueprint('public', __name__)


@public_bp.route('/manifest.json')
def pwa_manifest():
    return send_from_directory(current_app.static_folder, 'manifest.json', mimetype='application/manifest+json')


@public_bp.route('/sw.js')
def pwa_service_worker():
    # Served from root (not /static/sw.js) so its scope covers the whole site.
    return send_from_directory(current_app.static_folder, 'sw.js', mimetype='application/javascript')


@public_bp.route('/')
def index():
    # Week navigation
    today = date.today()
    week_offset = request.args.get('week', 0, type=int)
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    sunday = monday + timedelta(days=6)

    # Filters
    course_id = request.args.get('course_id', type=int)
    level = request.args.get('level', '')

    # Build schedule query — contains_eager populates Schedule.class_ from
    # this same join (the template accesses s.class_ twice, for a mobile and
    # a desktop render of the same week grid), instead of a lazy-load per
    # distinct class.
    q = Schedule.query.filter(
        Schedule.date >= monday,
        Schedule.date <= sunday,
        Schedule.is_cancelled == False,
    ).join(Schedule.class_).options(contains_eager(Schedule.class_)).filter(Class.is_active == True)

    if course_id:
        q = q.filter(Class.course_id == course_id)
    if level:
        q = q.join(Class.course).filter(Course.level == level)

    schedules = q.order_by(Schedule.date, Schedule.start_time).all()

    # Group by date, deduplicating same-name/same-time parallel classes on
    # the same day (e.g. 3 different "Toán 6" sections both at 09:00-10:30)
    # into one card, and stripping down to only the two public-safe fields
    # (class name + time). This is deliberate: the card dicts below never
    # carry the Schedule/Class ORM objects at all, so capacity, room, and
    # teacher can't leak into the public page even via a future template
    # edit — there's nothing to leak a reference to.
    week_days = [(monday + timedelta(days=i)) for i in range(7)]
    schedule_by_day = {d: [] for d in week_days}
    seen_keys = set()
    for s in schedules:
        if s.date not in schedule_by_day:
            continue
        key = (s.date, s.class_.subject_grade_label, s.start_time, s.end_time)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        schedule_by_day[s.date].append({
            'class_name': s.class_.subject_grade_label,
            'time_label': f"{s.start_time.strftime('%H:%M')}–{s.end_time.strftime('%H:%M')}",
            'is_intensive': s.schedule_type == 'intensive',
        })

    # Courses for filter
    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()

    # Schools for contact form dropdown (from distinct student schools)
    # Note: School table may not exist, so we use student.current_school directly
    rows = (db.session.query(Student.current_school)
            .filter(Student.current_school.isnot(None), Student.current_school != '')
            .distinct().order_by(Student.current_school).all())
    distinct_schools = [{'name': r[0], 'range': ''} for r in rows]

    # Batch every SystemConfig lookup this route needs into one query instead
    # of 12 sequential round trips (SystemConfig.get() issues its own query
    # per call) — this is the highest-traffic page in the app.
    config_keys = [
        'hall_of_fame_min_score', 'center_name', 'center_address', 'center_phone',
        'zalo_link', 'messenger_link', 'hero_bg', 'hero_badge',
        'hero_headline1', 'hero_headline2', 'hero_sub', 'hero_note',
    ]
    _config_rows = {
        row.key: row.value for row in
        SystemConfig.query.filter(SystemConfig.key.in_(config_keys)).all()
    }

    def cfg(key, default=None):
        # Matches SystemConfig.get()'s exact fallback semantics: missing key
        # -> default, present-but-NULL value -> None (not default).
        return _config_rows.get(key, default)

    # Hall of Fame
    min_score_val = float(cfg('hall_of_fame_min_score', '8'))
    hall_of_fame = (
        Score.query
        .options(joinedload(Score.class_), joinedload(Score.student))
        .filter(Score.score_value >= min_score_val)
        .order_by(Score.score_value.desc(), Score.exam_date.desc())
        .limit(60)
        .all()
    )

    # Confirmed reward per hall-of-fame score, batched in one query instead
    # of a per-row `s.rewards.filter_by(is_confirmed=True).first()` in the
    # template (was the worst N+1 found in the whole codebase audit — a
    # dynamic-relationship query per row on the public homepage).
    _hof_score_ids = [s.id for s in hall_of_fame]
    hof_rewards = {}
    if _hof_score_ids:
        for r in Reward.query.filter(
            Reward.score_id.in_(_hof_score_ids), Reward.is_confirmed == True
        ).all():
            hof_rewards[r.score_id] = r

    # Group hall of fame by class name (ordered by class name)
    from collections import defaultdict
    _hof_grouped = defaultdict(list)
    for _s in hall_of_fame:
        _hof_grouped[_s.class_.name].append(_s)
    hall_of_fame_by_class = dict(sorted(_hof_grouped.items()))

    center_name = cfg('center_name', 'Trung tâm Nhật Tuyền')
    center_address = cfg('center_address', '')
    center_phone = cfg('center_phone', '')
    zalo_link = cfg('zalo_link', '')
    messenger_link = cfg('messenger_link', '')
    hero_bg         = cfg('hero_bg',         '#f8fdf9')
    hero_badge      = cfg('hero_badge',      '')
    hero_headline1  = cfg('hero_headline1',  center_name)
    hero_headline2  = cfg('hero_headline2',  '')
    hero_sub        = cfg('hero_sub',        '')
    hero_note       = cfg('hero_note',       '')

    return render_template(
        'public/index.html',
        week_days=week_days,
        schedule_by_day=schedule_by_day,
        week_offset=week_offset,
        monday=monday,
        sunday=sunday,
        today=today,
        courses=courses,
        selected_course_id=course_id,
        selected_level=level,
        hall_of_fame=hall_of_fame,
        hall_of_fame_by_class=hall_of_fame_by_class,
        hof_rewards=hof_rewards,
        hero_bg=hero_bg,
        hero_badge=hero_badge,
        hero_headline1=hero_headline1,
        hero_headline2=hero_headline2,
        hero_sub=hero_sub,
        hero_note=hero_note,
        levels=StudentLevel.LABELS,
        center_name=center_name,
        center_address=center_address,
        center_phone=center_phone,
        zalo_link=zalo_link,
        messenger_link=messenger_link,
        distinct_schools=distinct_schools,
    )


@public_bp.route('/contact', methods=['POST'])
def contact_inquiry():
    """Save contact inquiry and auto-create pending student record."""
    student_name = request.form.get('student_name', '').strip()
    parent_phone = request.form.get('parent_phone', '').strip()
    grade        = request.form.get('grade', '').strip()
    subject      = request.form.get('subject', '').strip()
    school_val   = request.form.get('school', '').strip()
    # If "Khác" selected, use the typed value
    school_other = request.form.get('school_other', '').strip()
    school       = school_other if school_val == '__other__' else school_val
    note_val     = request.form.get('note', '').strip()
    confirm_tuition = request.form.get('confirm_tuition') == '1'

    if not student_name or not parent_phone or not grade or not subject or not school:
        return jsonify({'ok': False, 'msg': 'Vui lòng điền đầy đủ thông tin bắt buộc.'}), 400

    inquiry = ContactInquiry(
        student_name=student_name,
        grade=grade,
        subject=subject,
        school=school,
        parent_phone=parent_phone,
        note=note_val,
        confirm_tuition=confirm_tuition,
    )
    db.session.add(inquiry)

    # Auto-create pending student (skip if duplicate name+phone)
    existing = Student.query.filter_by(full_name=student_name, parent_phone=parent_phone).first()
    if not existing:
        pending_note = f'Đăng ký qua form liên hệ. Môn: {subject}.'
        if note_val:
            pending_note += f' Ghi chú: {note_val}'
        student = Student(
            full_name=student_name,
            current_school=school,
            current_grade=grade,
            level=StudentLevel.SECONDARY,
            parent_phone=parent_phone,
            note=pending_note,
            status='pending_confirmation',
        )
        db.session.add(student)

    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Cảm ơn! Cô Tuyền sẽ liên hệ lại với bạn sớm nhất có thể.'})
