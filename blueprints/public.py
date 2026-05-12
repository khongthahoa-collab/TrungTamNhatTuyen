from flask import Blueprint, render_template, request, jsonify
from datetime import date, timedelta
from models import Schedule, Class, Course, Score, SystemConfig, StudentLevel, ContactInquiry, Student, School
from extensions import db

public_bp = Blueprint('public', __name__)


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

    # Build schedule query
    q = Schedule.query.filter(
        Schedule.date >= monday,
        Schedule.date <= sunday,
        Schedule.is_cancelled == False,
    ).join(Schedule.class_).filter(Class.is_active == True)

    if course_id:
        q = q.filter(Class.course_id == course_id)
    if level:
        q = q.join(Class.course).filter(Course.level == level)

    schedules = q.order_by(Schedule.date, Schedule.start_time).all()

    # Group by date
    week_days = [(monday + timedelta(days=i)) for i in range(7)]
    schedule_by_day = {d: [] for d in week_days}
    for s in schedules:
        if s.date in schedule_by_day:
            schedule_by_day[s.date].append(s)

    # Courses for filter
    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()

    # Schools for contact form dropdown (from distinct student schools)
    # Note: School table may not exist, so we use student.current_school directly
    rows = (db.session.query(Student.current_school)
            .filter(Student.current_school.isnot(None), Student.current_school != '')
            .distinct().order_by(Student.current_school).all())
    distinct_schools = [{'name': r[0], 'range': ''} for r in rows]

    # Hall of Fame
    min_score_val = float(SystemConfig.get('hall_of_fame_min_score', '8'))
    hall_of_fame = (
        Score.query
        .filter(Score.score_value >= min_score_val)
        .order_by(Score.score_value.desc(), Score.exam_date.desc())
        .limit(60)
        .all()
    )

    # Group hall of fame by class name (ordered by class name)
    from collections import defaultdict
    _hof_grouped = defaultdict(list)
    for _s in hall_of_fame:
        _hof_grouped[_s.class_.name].append(_s)
    hall_of_fame_by_class = dict(sorted(_hof_grouped.items()))

    center_name = SystemConfig.get('center_name', 'Trung tâm Nhật Tuyền')
    center_address = SystemConfig.get('center_address', '')
    center_phone = SystemConfig.get('center_phone', '')
    zalo_link = SystemConfig.get('zalo_link', '')
    messenger_link = SystemConfig.get('messenger_link', '')
    hero_bg         = SystemConfig.get('hero_bg',         '#f8fdf9')
    hero_badge      = SystemConfig.get('hero_badge',      '')
    hero_headline1  = SystemConfig.get('hero_headline1',  center_name)
    hero_headline2  = SystemConfig.get('hero_headline2',  '')
    hero_sub        = SystemConfig.get('hero_sub',        '')
    hero_note       = SystemConfig.get('hero_note',       '')

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


@public_bp.route('/api/schedule/<int:schedule_id>')
def schedule_detail(schedule_id):
    """API trả về chi tiết buổi học (không hiện học phí)."""
    s = Schedule.query.get_or_404(schedule_id)
    return jsonify({
        'class_name': s.class_.name,
        'course': s.class_.course.name,
        'level': s.class_.grade_level or '',
        'grade_level': s.class_.grade_level or '',
        'date': s.date.strftime('%d/%m/%Y'),
        'time': f"{s.start_time.strftime('%H:%M')} - {s.end_time.strftime('%H:%M')}",
        'room': s.room or 'Chưa xác định',
        'topic': s.topic or '',
        'type': s.type_label,
        'enrolled': s.class_.current_enrollment,
        'max_students': s.class_.max_students,
        'teacher': s.teacher.full_name if s.teacher else 'Chưa phân công',
    })
