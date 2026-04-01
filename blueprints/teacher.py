from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user
from datetime import date, timedelta, datetime
from extensions import db
from models import Schedule, Attendance, Score, Class, Enrollment, Student, ClassDocument
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
                           monday=monday)


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
