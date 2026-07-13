from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required
from datetime import date, timedelta
from extensions import db
from models import AcademicYear, Semester, SemesterType, Student, GRADE_SEQUENCE, GRADE_TO_LEVEL
from blueprints.admin import admin_bp, require_admin


def current_academic_year_start(today=None):
    """Start-year of the currently active AcademicYear, or — if none is
    marked active — the school year the given/today's date falls in
    (Jul–Jun rule, same convention as classes.py's _current_school_year_range)."""
    active = AcademicYear.query.filter_by(is_active=True).first()
    if active:
        return active.start_date.year
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


@admin_bp.route('/academic-years')
@login_required
@require_admin
def academic_years():
    years = AcademicYear.query.order_by(AcademicYear.start_date.desc()).all()
    return render_template('admin/academic/list.html', years=years,
                           semester_types=SemesterType.LABELS)


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
    """Đồng bộ lớp học cho năm học hiện tại: học sinh chưa từng được gắn mốc
    năm học chỉ được gắn mốc (không lên lớp — không rõ nên lên bao nhiêu bậc);
    học sinh đã có mốc từ năm trước được lên lớp tương ứng số năm đã trôi qua,
    dừng lại ở Lớp 12. Học sinh có current_grade dạng tự do (không nằm trong
    GRADE_SEQUENCE, dữ liệu cũ) bị bỏ qua — cần admin sửa tay một lần.
    Đây là thao tác thủ công (bấm nút), chưa chạy tự động theo cron/queue."""
    current_year = current_academic_year_start()

    baselined = advanced = 0
    students = Student.query.filter(Student.is_active == True, Student.is_deleted == False).all()
    for s in students:
        if s.current_grade not in GRADE_SEQUENCE:
            continue
        if s.grade_year is None:
            s.grade_year = current_year
            baselined += 1
            continue
        if s.grade_year < current_year:
            steps = current_year - s.grade_year
            idx = GRADE_SEQUENCE.index(s.current_grade)
            new_grade = GRADE_SEQUENCE[min(idx + steps, len(GRADE_SEQUENCE) - 1)]
            if new_grade != s.current_grade:
                s.current_grade = new_grade
                s.level = GRADE_TO_LEVEL[new_grade]
                advanced += 1
            s.grade_year = current_year

    db.session.commit()
    flash(f'Đã đồng bộ lớp học theo năm học hiện tại: {advanced} học sinh lên lớp, '
          f'{baselined} học sinh được gắn mốc năm học lần đầu.', 'success')
    return redirect(url_for('admin.academic_years'))
