from flask import Blueprint, render_template, request, jsonify
from datetime import date, timedelta
from models import Schedule, Class, Course, Score, SystemConfig, StudentLevel

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

    # Hall of Fame
    min_score_val = float(SystemConfig.get('hall_of_fame_min_score', '8'))
    hall_of_fame = (
        Score.query
        .filter(Score.score_value >= min_score_val)
        .order_by(Score.score_value.desc(), Score.exam_date.desc())
        .limit(30)
        .all()
    )

    center_name = SystemConfig.get('center_name', 'Trung tâm Nhật Tuyền')
    center_address = SystemConfig.get('center_address', '')
    center_phone = SystemConfig.get('center_phone', '')
    zalo_link = SystemConfig.get('zalo_link', '')
    messenger_link = SystemConfig.get('messenger_link', '')

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
        levels=StudentLevel.LABELS,
        center_name=center_name,
        center_address=center_address,
        center_phone=center_phone,
        zalo_link=zalo_link,
        messenger_link=messenger_link,
    )


@public_bp.route('/api/lich/<int:schedule_id>')
def schedule_detail(schedule_id):
    """API trả về chi tiết buổi học (không hiện học phí)."""
    s = Schedule.query.get_or_404(schedule_id)
    return jsonify({
        'class_name': s.class_.name,
        'course': s.class_.course.name,
        'level': s.class_.course.level_label,
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
