from flask import abort, current_app, render_template, redirect, url_for, flash, request
from flask_login import current_user, login_required
from datetime import date, timedelta
from extensions import db
from models import AcademicYear, Semester, SemesterType
from blueprints.admin import admin_bp, require_admin
from services.academic_rollover import build_rollover_plan, RolloverError
from models import AcademicRollover
from sqlalchemy.exc import IntegrityError


def current_academic_year_start(today=None):
    """Start-year of the currently active AcademicYear, or — if none is
    marked active — the school year the given/today's date falls in
    (Jul–Jun rule, same convention as classes.py's _current_school_year_range)."""
    active = AcademicYear.query.filter_by(is_active=True).first()
    if active:
        return active.start_date.year
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


def _next_rollover_window_start(today=None):
    """The date rollover/sync next become available. If the active
    AcademicYear starts 01/07/Y (e.g. just rolled into 2026-2027), the
    *next* window doesn't open until 01/07/(Y+1) — not just "any month
    from July", which would otherwise leave the buttons clickable for
    the rest of the very year just rolled into (Aug-Dec 2026), a full
    year before they're meant to be usable again. Falls back to the
    plain 01/07 calendar rule if no AcademicYear is configured yet
    (fresh install, nothing to roll from)."""
    today = today or date.today()
    active = AcademicYear.query.filter_by(is_active=True).first()
    if active:
        return date(active.start_date.year + 1, 7, 1)
    return date(today.year, 7, 1) if today.month < 7 else date(today.year + 1, 7, 1)


def _rollover_window_open(today=None):
    """Both grade-advancement actions ('Cuộn năm học' and 'Đồng bộ lớp học')
    only make sense once the *next* school year is actually due to start.
    Tied to the active AcademicYear's own boundary (_next_rollover_window_start)
    so the window automatically re-locks itself the moment a rollover
    succeeds, instead of staying open for the rest of the calendar year
    it was just rolled into."""
    today = today or date.today()
    return today >= _next_rollover_window_start(today)


@admin_bp.route('/academic-years')
@login_required
@require_admin
def academic_years():
    years = AcademicYear.query.order_by(AcademicYear.start_date.desc()).all()
    return render_template('admin/academic/list.html', years=years,
                           rollover_enabled=current_app.config['ACADEMIC_ROLLOVER_ENABLED'],
                           rollover_jobs=AcademicRollover.query.order_by(AcademicRollover.id.desc()).limit(5).all(),
                           semester_types=SemesterType.LABELS,
                           rollover_window_open=_rollover_window_open(),
                           next_rollover_window_start=_next_rollover_window_start())


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


@admin_bp.route('/academic-years/sync-grades', methods=['POST'])
@login_required
@require_admin
def academic_sync_grades():
    """Compatibility endpoint: all advancement now goes through validated rollover."""
    flash('Tăng khối đã được gộp vào quy trình cuộn năm có kiểm tra và xem trước; không đồng bộ riêng để tránh lệch lớp.', 'warning')
    return redirect(url_for('admin.academic_year_rollover_preview'))


@admin_bp.route('/academic-years/rollover')
@login_required
@require_admin
def academic_year_rollover_preview():
    if not current_app.config['ACADEMIC_ROLLOVER_ENABLED']:
        flash('Chức năng cuộn năm đang tắt. Hiện chỉ chuẩn bị cấu hình, chưa chuyển dữ liệu.', 'warning')
        return redirect(url_for('admin.academic_years'))
    if not _rollover_window_open():
        flash(f'Chỉ có thể cuộn năm học từ ngày {_next_rollover_window_start().strftime("%d/%m/%Y")}.', 'danger')
        return redirect(url_for('admin.academic_years'))
    try:
        plan = build_rollover_plan()
    except RolloverError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('admin.academic_years'))
    rolling_info = [
        (item['class'], item['grade'], item['name'], len(item['roster']))
        for item in plan['rolling']
    ]
    job = AcademicRollover.query.filter_by(target_year=plan['next_year']).first()
    if job and job.status == 'pending':
        return redirect(url_for('admin.academic_rollover_status', job_id=job.id))
    return render_template('admin/academic/rollover_preview.html', plan=plan, rolling_info=rolling_info)


@admin_bp.route('/academic-years/rollover', methods=['POST'])
@login_required
@require_admin
def academic_year_rollover_execute():
    if not current_app.config['ACADEMIC_ROLLOVER_ENABLED']:
        flash('Chức năng cuộn năm đang tắt. Không có dữ liệu nào được chuyển.', 'danger')
        return redirect(url_for('admin.academic_years'))
    if not _rollover_window_open():
        flash(f'Chỉ có thể cuộn năm học từ ngày {_next_rollover_window_start().strftime("%d/%m/%Y")}.', 'danger')
        return redirect(url_for('admin.academic_years'))

    try:
        plan = build_rollover_plan()
        if plan['errors']:
            raise RolloverError('Còn lỗi dữ liệu. Hãy xem trước và xử lý toàn bộ trước khi xác nhận.')
        if request.form.get('fingerprint') != plan['fingerprint']:
            raise RolloverError('Dữ liệu đã thay đổi hoặc chưa xem trước. Hãy kiểm tra và xác nhận lại.')
        job = AcademicRollover.query.filter_by(target_year=plan['next_year']).with_for_update().first()
        if job is None:
            job = AcademicRollover(target_year=plan['next_year'])
            db.session.add(job)
        elif job.status != 'failed':
            return redirect(url_for('admin.academic_rollover_status', job_id=job.id))
        job.source_year_id = plan['source'].id
        job.requested_by = current_user.id
        job.fingerprint = plan['fingerprint']
        job.status = 'pending'
        job.error = job.result_json = job.finished_at = None
        db.session.commit()
        return redirect(url_for('admin.academic_rollover_status', job_id=job.id))
    except RolloverError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
        return redirect(url_for('admin.academic_year_rollover_preview'))
    except IntegrityError:
        db.session.rollback()
        current_app.logger.exception('Concurrent academic rollover request')
        flash('Yêu cầu chuyển năm đã thay đổi. Hãy kiểm tra trạng thái trước khi thử lại.', 'warning')
        return redirect(url_for('admin.academic_years'))


@admin_bp.get('/academic-rollovers/<int:job_id>')
@login_required
@require_admin
def academic_rollover_status(job_id):
    job = db.session.get(AcademicRollover, job_id)
    if job is None:
        abort(404)
    return render_template('admin/academic/rollover_status.html', job=job)
