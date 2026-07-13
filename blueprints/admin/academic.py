from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required
from datetime import date, timedelta
from extensions import db
from models import AcademicYear, Semester, SemesterType
from blueprints.admin import admin_bp, require_admin


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
