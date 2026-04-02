from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user
from datetime import date, timedelta, datetime, time as time_type
from extensions import db
from models import Schedule, Attendance, Score, Class, Enrollment, Student, ClassDocument, Room, Notification
from services.zalo_service import ZaloService
from services.reward_service import create_suggested_reward

teacher_bp = Blueprint('teacher', __name__)


def require_teacher(f):
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_teacher:
            abort(403)
        return f(*args, **kwargs)
    return decorated


@teacher_bp.route('/')
@login_required
@require_teacher
def dashboard():
    teacher = current_user.teacher_profile
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)

    # Today's schedules
    today_schedules = Schedule.query.filter_by(
        teacher_id=teacher.id, is_cancelled=False
    ).filter(Schedule.date == today).order_by(Schedule.start_time).all()

    # This week's schedules
    week_schedules = Schedule.query.filter_by(
        teacher_id=teacher.id, is_cancelled=False
    ).filter(
        Schedule.date >= monday, Schedule.date <= sunday
    ).order_by(Schedule.date, Schedule.start_time).all()

    # Needs attendance (past sessions without attendance taken)
    pending_attendance = Schedule.query.filter_by(
        teacher_id=teacher.id, is_cancelled=False
    ).filter(
        Schedule.date < today,
        Schedule.date >= today - timedelta(days=7),
    ).order_by(Schedule.date.desc()).all()
    pending_attendance = [s for s in pending_attendance if not s.attendance_taken]

    return render_template('teacher/dashboard.html',
                           teacher=teacher,
                           today=today,
                           today_schedules=today_schedules,
                           week_schedules=week_schedules,
                           pending_attendance=pending_attendance)


@teacher_bp.route('/lich-day')
@login_required
@require_teacher
def schedule():
    teacher = current_user.teacher_profile
    today = date.today()
    week_offset = request.args.get('week', 0, type=int)
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_days = [(monday + timedelta(days=i)) for i in range(7)]

    schedules = Schedule.query.filter_by(
        teacher_id=teacher.id
    ).filter(
        Schedule.date >= monday,
        Schedule.date <= monday + timedelta(days=6),
    ).order_by(Schedule.date, Schedule.start_time).all()

    by_day = {d: [] for d in week_days}
    for s in schedules:
        if s.date in by_day:
            by_day[s.date].append(s)

    return render_template('teacher/schedule.html',
                           teacher=teacher,
                           week_days=week_days,
                           by_day=by_day,
                           week_offset=week_offset,
                           today=today,
                           monday=monday,
                           sunday=monday + timedelta(days=6))


@teacher_bp.route('/check-in/<int:schedule_id>', methods=['POST'])
@login_required
@require_teacher
def checkin(schedule_id):
    teacher = current_user.teacher_profile
    schedule = Schedule.query.get_or_404(schedule_id)

    if schedule.teacher_id != teacher.id:
        abort(403)

    if schedule.teacher_checked_in:
        flash('Bạn đã check-in buổi học này rồi.', 'info')
    else:
        schedule.teacher_checked_in = True
        schedule.teacher_checkin_time = datetime.utcnow()
        db.session.commit()
        flash(f'Check-in thành công buổi {schedule.class_.name} ngày {schedule.date.strftime("%d/%m/%Y")}.', 'success')

    next_url = request.referrer or url_for('teacher.dashboard')
    return redirect(next_url)


@teacher_bp.route('/diem-danh/<int:schedule_id>', methods=['GET', 'POST'])
@login_required
@require_teacher
def attendance(schedule_id):
    teacher = current_user.teacher_profile
    schedule = Schedule.query.get_or_404(schedule_id)

    if schedule.teacher_id != teacher.id and not current_user.is_admin:
        abort(403)

    students = schedule.class_.active_students
    existing = {a.student_id: a for a in schedule.attendances.all()}

    if request.method == 'POST':
        for student in students:
            status = request.form.get(f'status_{student.id}', 'present')
            note = request.form.get(f'note_{student.id}', '').strip()

            if student.id in existing:
                att = existing[student.id]
                att.status = status
                att.note = note
            else:
                att = Attendance(
                    schedule_id=schedule.id,
                    student_id=student.id,
                    status=status,
                    note=note,
                    recorded_by=current_user.id,
                )
                db.session.add(att)

            # Zalo notification for absent/late
            if status in ('absent', 'late') and not att.zalo_notified:
                ZaloService.send_absence_notification(student, schedule, status, note)
                att.zalo_notified = True

        db.session.commit()
        flash('Đã lưu điểm danh thành công.', 'success')
        return redirect(url_for('teacher.dashboard'))

    # Pre-fill: all present by default
    prefill = {s.id: existing.get(s.id) for s in students}
    return render_template('teacher/attendance.html',
                           schedule=schedule,
                           students=students,
                           existing=prefill)


@teacher_bp.route('/nhap-diem/<int:class_id>', methods=['GET', 'POST'])
@login_required
@require_teacher
def scores(class_id):
    teacher = current_user.teacher_profile
    class_ = Class.query.get_or_404(class_id)

    # Check teacher teaches this class
    teaches = Schedule.query.filter_by(
        class_id=class_id, teacher_id=teacher.id
    ).first()
    if not teaches:
        abort(403)

    students = class_.active_students
    from models import ScoreSource, ScoreType

    if request.method == 'POST':
        score_source = request.form.get('score_source')
        score_type = request.form.get('score_type')
        exam_date_str = request.form.get('exam_date')
        school_name = request.form.get('school_name', '').strip()
        max_score = float(request.form.get('max_score', 10))

        try:
            exam_date = date.fromisoformat(exam_date_str) if exam_date_str else date.today()
        except ValueError:
            exam_date = date.today()

        saved = 0
        suggested_rewards = []
        for student in students:
            val_str = request.form.get(f'score_{student.id}', '').strip()
            if not val_str:
                continue
            try:
                val = float(val_str)
            except ValueError:
                continue

            note = request.form.get(f'note_{student.id}', '').strip()

            sc = Score(
                student_id=student.id,
                class_id=class_id,
                score_source=score_source,
                score_type=score_type,
                score_value=val,
                max_score=max_score,
                exam_date=exam_date,
                school_name=school_name if score_source == 'truong' else None,
                note=note,
                entered_by=current_user.id,
            )
            db.session.add(sc)
            db.session.flush()

            # Auto-suggest reward
            reward = create_suggested_reward(sc, current_user.id)
            if reward:
                suggested_rewards.append((student.full_name, reward.amount))

            saved += 1

        db.session.commit()
        msg = f'Đã lưu {saved} điểm.'
        if suggested_rewards:
            names = ', '.join(f"{n} ({int(a):,}đ)" for n, a in suggested_rewards)
            msg += f' Đề xuất thưởng cho: {names} (Admin cần xác nhận).'
        flash(msg, 'success')
        return redirect(url_for('teacher.scores', class_id=class_id))

    # Existing scores for this class (most recent)
    recent_scores = (
        Score.query.filter_by(class_id=class_id)
        .order_by(Score.created_at.desc())
        .limit(20).all()
    )

    return render_template('teacher/scores.html',
                           class_=class_,
                           students=students,
                           recent_scores=recent_scores,
                           score_sources=ScoreSource.LABELS,
                           score_types=ScoreType.LABELS,
                           today=date.today())


@teacher_bp.route('/tai-lieu/<int:class_id>', methods=['GET', 'POST'])
@login_required
@require_teacher
def documents(class_id):
    import uuid, os
    from flask import current_app
    teacher = current_user.teacher_profile
    class_ = Class.query.get_or_404(class_id)

    teaches = Schedule.query.filter_by(class_id=class_id, teacher_id=teacher.id).first()
    if not teaches:
        abort(403)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        file = request.files.get('file')

        if not title or not file or file.filename == '':
            flash('Vui lòng điền tiêu đề và chọn file.', 'danger')
        else:
            ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
            allowed = current_app.config.get('ALLOWED_EXTENSIONS', set())
            if ext not in allowed:
                flash(f'Định dạng file .{ext} không được hỗ trợ.', 'danger')
            else:
                stored_name = f"{uuid.uuid4().hex}.{ext}"
                upload_dir = current_app.config['UPLOAD_FOLDER']
                os.makedirs(upload_dir, exist_ok=True)
                save_path = os.path.join(upload_dir, stored_name)
                file.save(save_path)
                size = os.path.getsize(save_path)

                doc = ClassDocument(
                    class_id=class_id,
                    uploaded_by=current_user.id,
                    title=title,
                    description=description,
                    original_filename=file.filename,
                    stored_filename=stored_name,
                    file_size=size,
                    file_type=ext,
                )
                db.session.add(doc)
                db.session.commit()
                flash(f'Đã tải lên tài liệu "{title}".', 'success')

        return redirect(url_for('teacher.documents', class_id=class_id))

    docs = class_.documents.filter_by(is_active=True).order_by(
        ClassDocument.uploaded_at.desc()
    ).all()
    allowed_ext = current_app.config.get('ALLOWED_EXTENSIONS', set())
    return render_template('teacher/documents.html',
                           class_=class_, docs=docs, allowed_ext=allowed_ext)


@teacher_bp.route('/tai-lieu/xoa/<int:doc_id>', methods=['POST'])
@login_required
@require_teacher
def delete_document(doc_id):
    doc = ClassDocument.query.get_or_404(doc_id)
    teacher = current_user.teacher_profile
    if doc.uploaded_by != current_user.id and not current_user.is_admin:
        abort(403)
    doc.is_active = False
    db.session.commit()
    flash('Đã xóa tài liệu.', 'success')
    return redirect(request.referrer or url_for('teacher.dashboard'))


@teacher_bp.route('/tao-lich-tang-cuong', methods=['GET', 'POST'])
@login_required
@require_teacher
def create_intensive():
    """Teacher creates an intensive (one-off extra) schedule for one of their classes."""
    teacher = current_user.teacher_profile

    # Classes this teacher is assigned to
    my_classes = Class.query.filter(
        Class.is_active == True,
    ).filter(
        db.or_(
            Class.primary_teacher_id == teacher.id,
            Class.assistant_teacher_id == teacher.id,
        )
    ).order_by(Class.name).all()

    # Also include classes with scheduled sessions for this teacher
    scheduled_class_ids = {
        s.class_id for s in Schedule.query.filter_by(teacher_id=teacher.id).all()
    }
    extra_classes = Class.query.filter(
        Class.id.in_(scheduled_class_ids),
        Class.is_active == True,
        Class.id.notin_([c.id for c in my_classes]),
    ).order_by(Class.name).all()
    my_classes = my_classes + extra_classes

    rooms = Room.query.filter_by(is_active=True).order_by(
        Room.branch, Room.floor, Room.room_number
    ).all()

    if request.method == 'POST':
        class_id = request.form.get('class_id', type=int)
        date_str = request.form.get('date', '')
        start_str = request.form.get('start_time', '')
        end_str = request.form.get('end_time', '')
        room_id = request.form.get('room_id', type=int) or None
        topic = request.form.get('topic', '').strip()

        if not class_id or not date_str or not start_str or not end_str:
            flash('Vui lòng điền đầy đủ thông tin bắt buộc.', 'danger')
            return render_template('teacher/create_intensive.html',
                                   teacher=teacher, classes=my_classes, rooms=rooms)

        try:
            sched_date = date.fromisoformat(date_str)
            start_time = time_type.fromisoformat(start_str)
            end_time = time_type.fromisoformat(end_str)
        except ValueError:
            flash('Ngày hoặc giờ không hợp lệ.', 'danger')
            return render_template('teacher/create_intensive.html',
                                   teacher=teacher, classes=my_classes, rooms=rooms)

        # Verify teacher is allowed to create for this class
        allowed_ids = {c.id for c in my_classes}
        if class_id not in allowed_ids:
            abort(403)

        # Check room conflict — first-come-first-served
        if room_id:
            conflict = Schedule.query.filter(
                Schedule.room_id == room_id,
                Schedule.date == sched_date,
                Schedule.is_cancelled == False,
                Schedule.start_time < end_time,
                Schedule.end_time > start_time,
            ).first()
            if conflict:
                room_obj = Room.query.get(room_id)
                flash(
                    f'Phòng "{room_obj.display_name if room_obj else room_id}" đã được đặt '
                    f'vào khung giờ đó (lớp {conflict.class_.name}). Vui lòng chọn phòng khác.',
                    'danger'
                )
                return render_template('teacher/create_intensive.html',
                                       teacher=teacher, classes=my_classes, rooms=rooms)

        room_text = ''
        if room_id:
            room_obj = Room.query.get(room_id)
            room_text = room_obj.display_name if room_obj else ''

        s = Schedule(
            class_id=class_id,
            teacher_id=teacher.id,
            date=sched_date,
            start_time=start_time,
            end_time=end_time,
            room=room_text,
            room_id=room_id,
            topic=topic,
            schedule_type='intensive',
        )
        db.session.add(s)

        # Notify parents
        class_ = Class.query.get(class_id)
        for student in class_.active_students:
            ZaloService.send_intensive_schedule(student, s)

        db.session.commit()
        flash(
            f'Đã tạo lịch tăng cường cho {class_.name} ngày {sched_date.strftime("%d/%m/%Y")}.',
            'success'
        )
        return redirect(url_for('teacher.dashboard'))

    return render_template('teacher/create_intensive.html',
                           teacher=teacher, classes=my_classes, rooms=rooms)


@teacher_bp.route('/phong-trong')
@login_required
@require_teacher
def available_rooms():
    """AJAX: return available rooms for a given date+time slot."""
    date_str = request.args.get('date', '')
    start_str = request.args.get('start', '')
    end_str = request.args.get('end', '')

    if not date_str or not start_str or not end_str:
        return jsonify({'rooms': []})

    try:
        sched_date = date.fromisoformat(date_str)
        start_time = time_type.fromisoformat(start_str)
        end_time = time_type.fromisoformat(end_str)
    except ValueError:
        return jsonify({'rooms': []})

    booked_ids = {
        r[0] for r in db.session.query(Schedule.room_id).filter(
            Schedule.room_id.isnot(None),
            Schedule.date == sched_date,
            Schedule.is_cancelled == False,
            Schedule.start_time < end_time,
            Schedule.end_time > start_time,
        ).all()
    }

    available = Room.query.filter(
        Room.is_active == True,
        Room.id.notin_(booked_ids),
    ).order_by(Room.branch, Room.floor, Room.room_number).all()

    return jsonify({'rooms': [
        {'id': r.id, 'name': r.name, 'display': r.display_name, 'capacity': r.capacity}
        for r in available
    ]})


@teacher_bp.route('/diem-so')
@login_required
@require_teacher
def scores_list():
    """List all classes the teacher can enter scores for."""
    teacher = current_user.teacher_profile
    # Collect classes this teacher teaches (by schedule or assignment)
    scheduled_ids = {s.class_id for s in Schedule.query.filter_by(teacher_id=teacher.id).all()}
    primary_ids = {c.id for c in Class.query.filter(
        Class.primary_teacher_id == teacher.id, Class.is_active == True
    ).all()}
    all_ids = scheduled_ids | primary_ids
    classes = Class.query.filter(Class.id.in_(all_ids), Class.is_active == True).order_by(Class.name).all()
    return render_template('teacher/scores_list.html', teacher=teacher, classes=classes)


@teacher_bp.route('/thong-bao')
@login_required
@require_teacher
def notifications():
    """Teacher notifications page — marks all as read."""
    notifs = Notification.query.filter_by(
        user_id=current_user.id
    ).order_by(Notification.created_at.desc()).limit(50).all()
    # Mark all as read
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return render_template('teacher/notifications.html', notifs=notifs)
