from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify, current_app
from flask_login import login_required, current_user
from datetime import date, timedelta, datetime, time as time_type
import calendar
from sqlalchemy import extract
from sqlalchemy.orm import contains_eager, joinedload
from extensions import db
from models import Schedule, Attendance, Score, Class, Enrollment, Student, ClassDocument, Room, Notification, User, Salary, LeaveRequest, LeaveRequestStatus, Teacher
from services.zalo_service import ZaloService
from services.reward_service import create_suggested_reward
from services.salary_service import scheduled_sessions, substituted_sessions, taught_classes_count
from services.auth_context import get_active_role
from blueprints.pagination_utils import paginate_list

teacher_bp = Blueprint('teacher', __name__)


def _teacher_schedule_visibility(teacher):
    """SQLAlchemy filter condition for "does this teacher get to see this
    Schedule row on their Lịch dạy / Điểm danh": true if they're currently
    the class's primary teacher or one of its trợ giảng (covers past,
    today, and future), OR — for a class they're no longer attached to —
    if the row is in the past and they were the one actually assigned to
    teach it. This way, editing a class's trợ giảng list only changes what
    a teacher sees from today onward; their history isn't erased."""
    is_current_member = db.or_(
        Class.primary_teacher_id == teacher.id,
        Class.assistant_teachers.any(id=teacher.id),
    )
    return db.or_(
        is_current_member,
        db.and_(Schedule.date < date.today(), Schedule.teacher_id == teacher.id),
    )


def _teacher_score_class_ids(teacher):
    """Tập class_id giáo viên được xem/nhập điểm: là GV chính, HOẶC là trợ
    giảng, HOẶC có lịch dạy buổi nào đó của lớp.

    Trước đây mỗi trang điểm tự kiểm tra một kiểu khác nhau: trang danh sách
    chấp nhận "có lịch dạy HOẶC là GV chính", còn trang nhập điểm chỉ chấp
    nhận "có lịch dạy" — nên GV chính của lớp chưa xếp lịch thấy lớp trong
    danh sách nhưng bấm vào thì bị 403. Gộp về một quy tắc duy nhất ở đây,
    và bổ sung trợ giảng cho khớp với trang Lịch dạy/Điểm danh."""
    scheduled_ids = {
        r[0] for r in db.session.query(Schedule.class_id)
        .filter(Schedule.class_id.isnot(None), Schedule.teacher_id == teacher.id)
        .distinct().all()
    }
    primary_ids = {
        r[0] for r in db.session.query(Class.id)
        .filter(Class.primary_teacher_id == teacher.id).all()
    }
    assistant_ids = {c.id for c in teacher.assistant_classes}
    return scheduled_ids | primary_ids | assistant_ids


def _teacher_can_access_class(teacher, cls):
    """Cùng quy tắc với _teacher_score_class_ids() nhưng cho đúng 1 lớp —
    kiểm tra ngắn mạch, không phải tải toàn bộ danh sách lớp của giáo viên."""
    if not teacher or not cls:
        return False
    if cls.primary_teacher_id == teacher.id:
        return True
    if any(t.id == teacher.id for t in cls.assistant_teachers):
        return True
    return Schedule.query.filter_by(class_id=cls.id, teacher_id=teacher.id).first() is not None


def require_teacher(f):
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        # is_teacher_linked covers a dual-role admin (role == 'admin')
        # with a linked Teacher profile — is_teacher alone (role ==
        # 'teacher') would never be true for that account.
        if not current_user.is_authenticated or not (current_user.is_teacher or current_user.is_teacher_linked):
            abort(403)
        if get_active_role(current_user) != 'teacher':
            abort(403)
        return f(*args, **kwargs)
    return decorated


@teacher_bp.before_request
def check_module_permission():
    """Per-account feature restriction, on top of require_teacher above."""
    if not current_user.is_authenticated or not current_user.is_teacher:
        return
    from blueprints.permissions import TEACHER_ENDPOINT_MODULES
    endpoint = (request.endpoint or '').split('.')[-1]
    module = TEACHER_ENDPOINT_MODULES.get(endpoint)
    if module and not current_user.can_access(module):
        abort(403)


@teacher_bp.route('/')
@login_required
@require_teacher
def dashboard():
    teacher = current_user.teacher_profile
    today = date.today()
    month = request.args.get('month', today.month, type=int)
    year = request.args.get('year', today.year, type=int)

    salary = Salary.query.filter_by(teacher_id=teacher.id, month=month, year=year).first()

    return render_template('teacher/dashboard.html',
                           teacher=teacher,
                           today=today,
                           month=month,
                           year=year,
                           sessions_taught=scheduled_sessions(teacher.id, month, year),
                           sessions_substituted=substituted_sessions(teacher.id, month, year),
                           classes_taught=taught_classes_count(teacher.id, month, year),
                           base_amount=salary.base_amount if salary else (teacher.base_salary or 0),
                           total_amount=salary.total if salary else None)


@teacher_bp.route('/profile/update', methods=['POST'])
@login_required
@require_teacher
def update_profile():
    phone = request.form.get('phone', '').strip()
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    if phone and phone != current_user.phone:
        if User.query.filter(User.phone == phone, User.id != current_user.id).first():
            flash('Số điện thoại đã được sử dụng.', 'danger')
            return redirect(url_for('teacher.dashboard'))
        current_user.phone = phone

    if new_password or confirm_password:
        if len(new_password) < 6:
            flash('Mật khẩu mới phải có ít nhất 6 ký tự.', 'danger')
            return redirect(url_for('teacher.dashboard'))
        if new_password != confirm_password:
            flash('Mật khẩu xác nhận không khớp.', 'danger')
            return redirect(url_for('teacher.dashboard'))
        current_user.set_password(new_password)

    db.session.commit()
    flash('Đã cập nhật thông tin.', 'success')
    return redirect(url_for('teacher.dashboard'))


@teacher_bp.route('/schedule')
@login_required
@require_teacher
def schedule():
    teacher = current_user.teacher_profile
    today = date.today()

    date_str = request.args.get('date', '')
    try:
        ref_date = date.fromisoformat(date_str) if date_str else today
    except ValueError:
        ref_date = today

    monday = ref_date - timedelta(days=ref_date.weekday())
    week_days = [(monday + timedelta(days=i)) for i in range(7)]

    filter_mode = request.args.get('filter', 'all')
    if filter_mode not in ('all', 'mine'):
        filter_mode = 'all'

    # "Tất cả": mọi buổi của lớp mà giáo viên này ĐANG là GV chính HOẶC trợ
    # giảng (kể cả buổi do người khác đứng lớp) — để thấy lịch đầy đủ của lớp.
    # Nếu không còn là thành viên lớp nữa (bị gỡ khỏi trợ giảng), vẫn thấy các
    # buổi ĐÃ QUA mà chính họ từng đứng lớp — đổi danh sách trợ giảng chỉ
    # ảnh hưởng từ hôm nay trở đi, không xóa lịch sử.
    query = Schedule.query.join(Class, Schedule.class_id == Class.id).options(
        contains_eager(Schedule.class_),
        joinedload(Schedule.teacher).joinedload(Teacher.user),
        joinedload(Schedule.substitute_teacher).joinedload(Teacher.user),
    ).filter(
        Schedule.date >= monday,
        Schedule.date <= monday + timedelta(days=6),
    )
    if filter_mode == 'mine':
        query = query.filter(Schedule.teacher_id == teacher.id)
    else:
        query = query.filter(_teacher_schedule_visibility(teacher))

    # Only 3 sessions loaded per request instead of the whole week at once —
    # scrolling near the bottom fetches the next 3 as a small HTML fragment
    # (see the fragment branch below) instead of ever pulling every session
    # in the week in one response.
    spage = request.args.get('spage', 1, type=int)
    sched_pagination = query.order_by(Schedule.date, Schedule.start_time).paginate(
        page=spage, per_page=3, error_out=False)
    schedules = sched_pagination.items

    by_day = {}
    for s in schedules:
        by_day.setdefault(s.date, []).append(s)
    present_days = [d for d in week_days if d in by_day]

    if request.args.get('fragment') == '1':
        html = render_template('teacher/_schedule_fragment.html',
                               present_days=present_days, by_day=by_day, today=today, teacher=teacher)
        return jsonify({'html': html, 'has_next': sched_pagination.has_next})

    this_week_start = today - timedelta(days=today.weekday())
    this_month_start = today.replace(day=1)

    return render_template('teacher/schedule.html',
                           teacher=teacher,
                           week_days=week_days,
                           present_days=present_days,
                           by_day=by_day,
                           has_any=sched_pagination.total > 0,
                           has_next=sched_pagination.has_next,
                           ref_date=ref_date,
                           today=today,
                           monday=monday,
                           sunday=monday + timedelta(days=6),
                           filter_mode=filter_mode,
                           prev_date=ref_date - timedelta(days=7),
                           next_date=ref_date + timedelta(days=7),
                           prev2_date=ref_date - timedelta(days=14),
                           next2_date=ref_date + timedelta(days=14),
                           this_week_start=this_week_start,
                           this_month_start=this_month_start)


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




@teacher_bp.route('/scores/<int:class_id>', methods=['GET', 'POST'])
@login_required
@require_teacher
def scores(class_id):
    teacher = current_user.teacher_profile
    class_ = Class.query.get_or_404(class_id)

    if not _teacher_can_access_class(teacher, class_):
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

        # Validate thang điểm một lần cho cả đợt nhập — max_score <= 0 sẽ
        # gây chia cho 0 khi quy đổi điểm ở trang chi tiết.
        if max_score <= 0:
            flash('Điểm tối đa phải lớn hơn 0.', 'danger')
            return redirect(url_for('teacher.scores', class_id=class_id))

        saved = 0
        skipped = []
        suggested_rewards = []
        for student in students:
            val_str = request.form.get(f'score_{student.id}', '').strip()
            if not val_str:
                continue
            try:
                val = float(val_str)
            except ValueError:
                skipped.append(f'{student.full_name} (không phải số)')
                continue

            # Chặn điểm âm hoặc vượt thang điểm ngay khi ghi, thay vì để dữ
            # liệu sai lọt vào rồi làm sai thống kê Đạt/Không đạt về sau.
            if val < 0 or val > max_score:
                skipped.append(f'{student.full_name} (điểm phải từ 0 đến {max_score:g})')
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
        if skipped:
            flash('Bỏ qua do dữ liệu không hợp lệ: ' + '; '.join(skipped), 'warning')
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


def _normalized_10(score):
    """Điểm quy về thang 10 để so sánh được giữa các bài có thang khác nhau.
    Trả về None nếu max_score không hợp lệ (thiếu, 0 hoặc âm) — không được
    mặc định coi max_score là 10 vì sẽ tạo ra điểm sai một cách âm thầm."""
    max_s = score.max_score or 0
    if max_s <= 0:
        return None
    return (score.score_value or 0) / max_s * 10


# Ngưỡng Đạt: 50% thang điểm, tức 5 trên thang 10 sau khi quy đổi.
PASS_THRESHOLD_10 = 5.0


@teacher_bp.route('/scores/<int:class_id>/detail')
@teacher_bp.route('/scores/<int:class_id>/detai')  # alias: giữ URL cũ trong tài liệu
@login_required
@require_teacher
def scores_detail(class_id):
    """Chi tiết điểm của một lớp theo năm — chỉ xem và phân tích, không nhập
    điểm (trang nhập điểm giữ riêng ở /teacher/scores/<class_id>).

    Chỉ tính điểm Trung tâm (score_source = center). Điểm thi ở trường không
    tham gia vào Đạt/Không đạt, điểm trung bình hay chỉ báo tiến bộ."""
    from models import ScoreSource, ScoreType

    teacher = current_user.teacher_profile
    class_ = Class.query.get_or_404(class_id)
    if not _teacher_can_access_class(teacher, class_):
        abort(403)

    today = date.today()
    year = request.args.get('year', today.year, type=int)
    score_type = request.args.get('score_type', '').strip()

    # Lọc ngay trong SQL, không lấy hết điểm rồi lọc bằng Python.
    base_q = (Score.query
              .join(Student, Score.student_id == Student.id)
              .options(contains_eager(Score.student))
              .filter(Score.class_id == class_id,
                      Score.score_source == ScoreSource.CENTER,
                      extract('year', Score.exam_date) == year))
    if score_type:
        base_q = base_q.filter(Score.score_type == score_type)

    # exam_date là cột nullable — các dòng thiếu ngày thi sẽ không khớp bất
    # kỳ bộ lọc năm nào và biến mất khỏi trang này. Đếm riêng để báo cho
    # giáo viên biết thay vì âm thầm bỏ sót dữ liệu.
    undated_count = Score.query.filter(
        Score.class_id == class_id,
        Score.score_source == ScoreSource.CENTER,
        Score.exam_date.is_(None),
    ).count()

    # Các năm thực sự có dữ liệu, để đổ vào dropdown thay vì đoán khoảng năm.
    year_rows = (db.session.query(extract('year', Score.exam_date))
                 .filter(Score.class_id == class_id,
                         Score.score_source == ScoreSource.CENTER,
                         Score.exam_date.isnot(None))
                 .distinct().all())
    available_years = sorted({int(r[0]) for r in year_rows if r[0] is not None}, reverse=True)
    if year not in available_years:
        available_years = sorted(set(available_years) | {year}, reverse=True)

    all_scores = base_q.order_by(Score.exam_date.desc(), Score.id.desc()).all()

    # Bảng lịch sử (phân trang trong Python: tập dữ liệu đã lọc theo 1 lớp +
    # 1 năm nên nhỏ, và phần tiến bộ bên dưới cần toàn bộ tập này).
    page = request.args.get('page', 1, type=int)
    history_pagination = paginate_list(all_scores, page, per_page=20)

    rows = []
    for sc in history_pagination.items:
        norm = _normalized_10(sc)
        rows.append({
            'score': sc,
            'student_name': sc.student.full_name if sc.student else '—',
            'normalized': norm,
            'passed': None if norm is None else norm >= PASS_THRESHOLD_10,
        })

    # Chỉ báo tiến bộ: so điểm lần đầu với lần gần nhất, tính trên điểm đã
    # quy về thang 10 để không bị lệch khi các bài có thang điểm khác nhau.
    by_student = {}
    for sc in all_scores:
        norm = _normalized_10(sc)
        if norm is None or not sc.exam_date:
            continue
        by_student.setdefault(sc.student_id, {'student': sc.student, 'items': []})
        by_student[sc.student_id]['items'].append((sc.exam_date, sc.id, norm))

    progress = []
    for data in by_student.values():
        items = sorted(data['items'], key=lambda x: (x[0], x[1]))
        first_val = items[0][2]
        last_val = items[-1][2]
        count = len(items)
        delta = last_val - first_val
        if count < 2:
            label, tone = 'Cần thêm lần kiểm tra', 'secondary'
        elif delta > 0:
            label, tone = 'Có tiến bộ', 'success'
        elif delta < 0:
            label, tone = 'Cần theo dõi', 'danger'
        else:
            label, tone = 'Ổn định', 'info'
        progress.append({
            'student': data['student'],
            'count': count,
            'first': first_val,
            'last': last_val,
            'delta': delta,
            'average': sum(i[2] for i in items) / count,
            'label': label,
            'tone': tone,
        })
    progress.sort(key=lambda p: p['student'].full_name if p['student'] else '')

    graded = [r for r in rows if r['normalized'] is not None]
    return render_template('teacher/scores_detail.html',
                           class_=class_,
                           rows=rows,
                           pagination=history_pagination,
                           progress=progress,
                           total_scores=len(all_scores),
                           undated_count=undated_count,
                           invalid_max_count=sum(1 for r in rows if r['normalized'] is None),
                           passed_count=sum(1 for r in graded if r['passed']),
                           failed_count=sum(1 for r in graded if not r['passed']),
                           year=year,
                           available_years=available_years,
                           score_type=score_type,
                           score_types=ScoreType.LABELS,
                           pass_threshold=PASS_THRESHOLD_10,
                           today=today)


@teacher_bp.route('/documents/<int:class_id>', methods=['GET', 'POST'])
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


@teacher_bp.route('/documents/<int:doc_id>/delete', methods=['POST'])
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


@teacher_bp.route('/intensive/create', methods=['GET', 'POST'])
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
            Class.assistant_teachers.any(id=teacher.id),
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


@teacher_bp.route('/rooms/available')
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


@teacher_bp.route('/scores')
@login_required
@require_teacher
def scores_list():
    """List all classes the teacher can enter scores for."""
    teacher = current_user.teacher_profile
    class_ids = _teacher_score_class_ids(teacher)
    classes = (Class.query
               .options(joinedload(Class.course))
               .filter(Class.id.in_(class_ids), Class.is_active == True)
               .order_by(Class.name).all()) if class_ids else []
    # Sĩ số gộp 1 query thay cho Class.current_enrollment (1 COUNT/lớp) mà
    # template đang gọi theo từng dòng.
    shown_ids = [c.id for c in classes]
    enrollment_counts = dict(
        db.session.query(Enrollment.class_id, db.func.count(Enrollment.id))
        .filter(Enrollment.class_id.in_(shown_ids), Enrollment.is_active == True)
        .group_by(Enrollment.class_id).all()
    ) if shown_ids else {}
    return render_template('teacher/scores_list.html', teacher=teacher, classes=classes,
                           enrollment_counts=enrollment_counts)


@teacher_bp.route('/notifications')
@login_required
@require_teacher
def notifications():
    """Teacher notifications page — infinite-scroll, not a single big load:
    page 1 renders server-side (7 items; CSS hides the last 3 on narrow
    screens), further pages are fetched on demand as the user scrolls (see
    the fragment branch below), so this never has to pull an unbounded
    notification history in one response."""
    page = request.args.get('page', 1, type=int)
    is_fragment = request.args.get('fragment') == '1'
    pagination = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .paginate(page=page, per_page=7, error_out=False)
    )

    if is_fragment:
        html = render_template('teacher/_notifications_fragment.html', notifs=pagination.items)
        return jsonify({'html': html, 'has_next': pagination.has_next})

    # Đánh dấu đã đọc giờ là hành động chủ động của giáo viên (nút "Đánh dấu
    # đã đọc" / "Đã đọc tất cả") — không còn tự động đánh dấu hết khi chỉ mở
    # trang xem qua.
    return render_template('teacher/notifications.html', notifs=pagination.items, pagination=pagination)


@teacher_bp.route('/notifications/<int:notif_id>/read', methods=['POST'])
@login_required
@require_teacher
def notification_mark_read(notif_id):
    n = Notification.query.filter_by(id=notif_id, user_id=current_user.id).first_or_404()
    n.is_read = True
    db.session.commit()
    return jsonify({'success': True})


@teacher_bp.route('/notifications/read-all', methods=['POST'])
@login_required
@require_teacher
def notifications_read_all():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return redirect(url_for('teacher.notifications'))


# ============================================================
# Attendance Management Routes
# ============================================================

def _shift_month(d, months):
    """Shift date d by `months` calendar months, clamping the day to the
    target month's last day if needed (e.g. 31/01 + 1 tháng -> 28/02)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


@teacher_bp.route('/attendance')
@login_required
@require_teacher
def attendance_list():
    """Schedules for a day/week/month (default: today, day view) — the
    teacher's own regular assignments. Only today's own session(s) can
    actually be attended (see can_edit in the template / save_attendance);
    everything else across the visible range is view-only."""
    from models import AttendanceSummary
    teacher = current_user.teacher_profile
    today = date.today()

    view_mode = request.args.get('view', 'day')
    if view_mode not in ('day', 'week', 'month'):
        view_mode = 'day'

    date_str = request.args.get('date', '')
    try:
        ref_date = date.fromisoformat(date_str) if date_str else today
    except ValueError:
        ref_date = today

    if view_mode == 'week':
        range_start = ref_date - timedelta(days=ref_date.weekday())
        range_end = range_start + timedelta(days=6)
    elif view_mode == 'month':
        range_start = ref_date.replace(day=1)
        range_end = range_start.replace(day=calendar.monthrange(range_start.year, range_start.month)[1])
    else:
        range_start = range_end = ref_date

    # Hiển thị cả các buổi của lớp mà giáo viên này là trợ giảng, không chỉ
    # buổi do chính họ đứng lớp — để trợ giảng thấy được lịch đầy đủ của lớp.
    # Ai thực sự dạy buổi nào (và ai được phép điểm danh) vẫn theo
    # Schedule.teacher_id, xem can_edit trong template + save_attendance().
    schedules = (Schedule.query
                .join(Class, Schedule.class_id == Class.id)
                .options(
                    contains_eager(Schedule.class_),
                    joinedload(Schedule.teacher).joinedload(Teacher.user),
                    joinedload(Schedule.substitute_teacher).joinedload(Teacher.user),
                )
                .filter(
                    _teacher_schedule_visibility(teacher),
                    Schedule.is_cancelled == False,
                    Schedule.date >= range_start,
                    Schedule.date <= range_end,
                ).order_by(Schedule.date, Schedule.start_time).all())

    # Load attendance summaries
    summaries = AttendanceSummary.query.filter(
        AttendanceSummary.schedule_id.in_([s.id for s in schedules])
    ).all()
    summary_dict = {s.schedule_id: s for s in summaries}

    # Full roster + existing attendance per schedule, for the inline panel.
    # Batched into 2 queries total instead of 2 per schedule (was 1 + 2N).
    # contains_eager populates Enrollment.student from this same join (the
    # template accesses enrollment.student per row) instead of a lazy-load
    # per student.
    class_ids = {s.class_id for s in schedules}
    schedule_ids = [s.id for s in schedules]

    enrollments_by_class = {}
    if class_ids:
        all_enrollments = (Enrollment.query.join(Student)
                           .options(contains_eager(Enrollment.student))
                           .filter(Enrollment.class_id.in_(class_ids), Enrollment.is_active == True)
                           .order_by(Student.full_name).all())
        for e in all_enrollments:
            enrollments_by_class.setdefault(e.class_id, []).append(e)

    attendance_by_schedule = {}
    if schedule_ids:
        all_attendances = Attendance.query.filter(Attendance.schedule_id.in_(schedule_ids)).all()
        for a in all_attendances:
            attendance_by_schedule.setdefault(a.schedule_id, {})[a.student_id] = a

    # Sĩ số / "đã điểm danh chưa" also used to be a .count() query per
    # schedule/class (Class.current_enrollment, Schedule.attendance_taken)
    # — derive both from the same batched data above instead.
    # Approved leave requests overlapping the visible date range, for every
    # student enrolled in a shown class — one query instead of one per
    # schedule. Membership is resolved per-schedule below since a request's
    # [start_date, end_date] can cover only some of the sessions on screen.
    all_student_ids = {e.student_id for lst in enrollments_by_class.values() for e in lst}
    leave_requests = []
    if all_student_ids:
        leave_requests = LeaveRequest.query.filter(
            LeaveRequest.student_id.in_(all_student_ids),
            LeaveRequest.status == LeaveRequestStatus.APPROVED,
            LeaveRequest.start_date <= range_end,
            LeaveRequest.end_date >= range_start,
        ).all()

    roster = {}
    for s in schedules:
        enrollments = enrollments_by_class.get(s.class_id, [])
        enrolled_ids = {e.student_id for e in enrollments}
        excused_student_ids = {
            lr.student_id for lr in leave_requests
            if lr.student_id in enrolled_ids and lr.start_date <= s.date <= lr.end_date
        }
        roster[s.id] = {
            'enrollments': enrollments,
            'attendance': attendance_by_schedule.get(s.id, {}),
            'enrollment_count': len(enrollments),
            'attendance_taken': bool(attendance_by_schedule.get(s.id)),
            'excused_student_ids': excused_student_ids,
        }

    if view_mode == 'week':
        prev_date, next_date = ref_date - timedelta(days=7), ref_date + timedelta(days=7)
        prev2_date, next2_date = ref_date - timedelta(days=14), ref_date + timedelta(days=14)
    elif view_mode == 'month':
        prev_date, next_date = _shift_month(ref_date, -1), _shift_month(ref_date, 1)
        prev2_date, next2_date = _shift_month(ref_date, -2), _shift_month(ref_date, 2)
    else:
        prev_date, next_date = ref_date - timedelta(days=1), ref_date + timedelta(days=1)
        prev2_date, next2_date = ref_date - timedelta(days=14), ref_date + timedelta(days=14)

    this_week_start = today - timedelta(days=today.weekday())
    this_month_start = today.replace(day=1)
    # Bất kỳ ai trong lớp (GV chính/trợ giảng) đều điểm danh được, nhưng chỉ
    # buổi đúng hôm nay mới thật sự thao tác được (buổi đã qua luôn bị khóa) —
    # nên chỉ nhắc "chưa điểm danh" cho đúng hôm nay, tránh nhắc việc không
    # còn làm được nữa.
    pending_count = sum(1 for s in schedules if s.date == today and not roster[s.id]['attendance_taken'])

    return render_template('teacher/attendance_list.html',
                         schedules=schedules,
                         summaries=summary_dict,
                         roster=roster,
                         today=today,
                         view_mode=view_mode,
                         ref_date=ref_date,
                         range_start=range_start,
                         range_end=range_end,
                         pending_count=pending_count,
                         prev_date=prev_date,
                         next_date=next_date,
                         prev2_date=prev2_date,
                         next2_date=next2_date,
                         this_week_start=this_week_start,
                         this_month_start=this_month_start)


@teacher_bp.route('/attendance/<int:schedule_id>')
@login_required
@require_teacher
def attendance_session(schedule_id):
    """Attendance taking for a specific session"""
    from models import AttendanceSummary
    schedule = Schedule.query.get_or_404(schedule_id)

    # Allow access: GV chính hoặc trợ giảng của lớp (không nhất thiết là
    # người được gán đứng lớp buổi này), hoặc admin.
    teacher = current_user.teacher_profile
    cls = schedule.class_
    is_assigned = teacher and (cls.primary_teacher_id == teacher.id or teacher in cls.assistant_teachers)
    if not current_user.is_admin and not is_assigned:
        abort(403)

    is_future = schedule.date > date.today()

    # Get enrolled students — chỉ những học sinh còn thực sự hoạt động (chưa
    # nghỉ/bị xoá) mới vào danh sách điểm danh hôm nay/tương lai.
    enrollments = (Enrollment.query
                   .join(Student, Enrollment.student_id == Student.id)
                   .options(contains_eager(Enrollment.student))
                   .filter(Enrollment.class_id == schedule.class_id, Enrollment.is_active == True,
                           Student.is_active == True, Student.is_deleted == False)
                   .all())

    if not is_future:
        # Buổi đã qua: học sinh đã nghỉ/bị xoá SAU buổi này nhưng có bản ghi điểm
        # danh thật cho đúng buổi đó vẫn phải hiện — không được để lịch sử biến mất.
        already_included_ids = {e.student_id for e in enrollments}
        recorded_student_ids = {
            r[0] for r in db.session.query(Attendance.student_id)
            .filter(Attendance.schedule_id == schedule_id).all()
        }
        missing_ids = recorded_student_ids - already_included_ids
        if missing_ids:
            enrollments += Enrollment.query.options(joinedload(Enrollment.student)).filter(
                Enrollment.class_id == schedule.class_id,
                Enrollment.student_id.in_(missing_ids),
            ).all()

    # Students with an approved leave request covering this exact session
    # date — locked to "excused" in the template so the teacher can't
    # accidentally mark them absent-unexcused (and trigger a parent alert).
    excused_student_ids = set()
    enrolled_student_ids = [e.student_id for e in enrollments]
    if enrolled_student_ids:
        excused_student_ids = {
            r[0] for r in db.session.query(LeaveRequest.student_id).filter(
                LeaveRequest.student_id.in_(enrolled_student_ids),
                LeaveRequest.start_date <= schedule.date,
                LeaveRequest.end_date >= schedule.date,
                LeaveRequest.status == LeaveRequestStatus.APPROVED,
            ).all()
        }

    # Get existing attendance records
    attendances = Attendance.query.filter_by(schedule_id=schedule_id).all()
    attendance_dict = {a.student_id: a for a in attendances}
    
    # Get or create summary
    summary = AttendanceSummary.query.filter_by(schedule_id=schedule_id).first()
    if not summary:
        summary = AttendanceSummary(
            schedule_id=schedule_id,
            class_id=schedule.class_id,
            total_enrolled=len(enrollments)
        )
        db.session.add(summary)
        db.session.commit()
    
    from models import SystemConfig
    center_name = SystemConfig.get('center_name', 'Trung tâm học thêm Nhật Tuyền')
    center_phone = SystemConfig.get('center_phone', '')

    return render_template('teacher/attendance_session.html',
                         schedule=schedule,
                         enrollments=enrollments,
                         attendance_dict=attendance_dict,
                         excused_student_ids=excused_student_ids,
                         summary=summary,
                         center_name=center_name,
                         center_phone=center_phone,
                         is_future=is_future,
                         attendance_status=dict(
                             PRESENT='Có mặt',
                             ABSENT='Vắng',
                             LATE='Trễ',
                             EXCUSED='Vắng có phép'
                         ))


@teacher_bp.route('/api/attendance/<int:schedule_id>/save', methods=['POST'])
@login_required
def save_attendance(schedule_id):
    """Save attendance records for a session (teacher or admin)"""
    from models import AttendanceSummary
    if not current_user.is_teacher and not current_user.is_admin:
        return jsonify({'error': 'Bạn không có quyền thực hiện thao tác này.'}), 403
    schedule = Schedule.query.get_or_404(schedule_id)

    # Giáo viên chỉ được điểm danh buổi thuộc lớp mà họ là GV chính hoặc trợ
    # giảng — không nhất thiết phải là người được gán đứng lớp buổi đó (một
    # trợ giảng có thể điểm danh thay buổi do GV chính/trợ giảng khác dạy).
    teacher = current_user.teacher_profile
    if current_user.is_teacher and not current_user.is_admin:
        cls = schedule.class_
        is_assigned = teacher and (cls.primary_teacher_id == teacher.id or teacher in cls.assistant_teachers)
        if not is_assigned:
            return jsonify({'error': 'Bạn không có quyền điểm danh lớp này.'}), 403

    # Chỉ được điểm danh đúng ngày diễn ra buổi học — không điểm danh trước
    # (buổi tương lai) hay điểm danh sau (buổi đã qua), dù đã điểm danh hay chưa.
    if schedule.date != date.today():
        return jsonify({'error': 'Chỉ có thể điểm danh đúng ngày diễn ra buổi học.'}), 403

    try:
        return _save_attendance_records(schedule, schedule_id)
    except Exception:
        db.session.rollback()
        current_app.logger.exception('save_attendance failed for schedule_id=%s', schedule_id)
        return jsonify({'error': 'Có lỗi xảy ra khi lưu điểm danh, vui lòng thử lại. Nếu vẫn lỗi, báo cho quản trị viên.'}), 500


def _save_attendance_records(schedule, schedule_id):
    from models import AttendanceSummary
    data = request.get_json()
    attendance_records = data.get('attendance', [])

    # Update or create attendance records
    present_count = 0
    absent_count = 0
    late_count = 0
    excused_count = 0

    for record in attendance_records:
        student_id = record['student_id']
        status = record['status']
        reason = record.get('reason', '')
        
        att = Attendance.query.filter_by(
            schedule_id=schedule_id,
            student_id=student_id
        ).first()
        
        if not att:
            att = Attendance(
                schedule_id=schedule_id,
                student_id=student_id
            )
            db.session.add(att)
        
        att.status = status
        att.reason = reason
        att.recorded_by = current_user.id
        att.recorded_at = datetime.utcnow()
        
        # Count stats
        if status == 'present':
            present_count += 1
        elif status == 'absent':
            absent_count += 1
        elif status == 'late':
            late_count += 1
        elif status == 'excused':
            excused_count += 1
    
    # Update or create summary
    summary = AttendanceSummary.query.filter_by(schedule_id=schedule_id).first()
    if not summary:
        summary = AttendanceSummary(
            schedule_id=schedule_id,
            class_id=schedule.class_id
        )
        db.session.add(summary)
    
    summary.present_count = present_count
    summary.absent_count = absent_count
    summary.late_count = late_count
    summary.excused_count = excused_count
    summary.total_enrolled = len(attendance_records)
    
    db.session.commit()

    # Build absent/late student list with names
    student_ids = [r['student_id'] for r in attendance_records if r['status'] in ('absent', 'excused', 'late')]
    students_by_id = {s.id: s for s in Student.query.filter(Student.id.in_(student_ids)).all()}
    absent_students = []
    for record in attendance_records:
        if record['status'] in ('absent', 'excused', 'late'):
            s = students_by_id.get(record['student_id'])
            if s:
                label = {'absent': 'Vắng không phép', 'excused': 'Vắng có phép', 'late': 'Đi trễ'}.get(record['status'], record['status'])
                absent_students.append({'name': s.full_name, 'status': record['status'], 'status_label': label, 'reason': record.get('reason', '')})

    teacher_display = schedule.teacher.display_name if schedule.teacher else ''

    total = len(attendance_records)
    summary_data = {
        'class_name': schedule.class_.name,
        'date': schedule.date.strftime('%d/%m/%Y'),
        'teacher_display': teacher_display,
        'total': total,
        'present': present_count + late_count,
        'excused': excused_count,
        'absent': absent_count,
        'late': late_count,
        'absent_students': absent_students,
        'zalo_sent': False,
    }

    # Option to send to Zalo group
    send_zalo = data.get('send_zalo', False)
    if send_zalo:
        zalo_group = schedule.class_.zalo_group
        zalo_target = zalo_group.zalo_group_id if zalo_group and zalo_group.is_active else schedule.class_.zalo_group_id
        if zalo_target:
            ZaloService.send_attendance_summary_to_group(schedule, summary_data, zalo_target)
            summary.is_sent_zalo = True
            summary.zalo_sent_at = datetime.utcnow()
            db.session.commit()
            summary_data['zalo_sent'] = True
    
    return jsonify({
        'success': True,
        'message': 'Lưu điểm danh thành công',
        'summary': summary_data
    })


# Import to register the teacher-side exam routes (separate screens from admin's,
# sharing only the underlying models + blueprints/exams_shared.py parsing logic)
from blueprints import teacher_exams  # noqa: E402,F401
