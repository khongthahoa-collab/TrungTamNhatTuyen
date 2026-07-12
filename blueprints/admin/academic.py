from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required
from datetime import date
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

    ay = AcademicYear(
        name=name,
        start_date=date.fromisoformat(start_str),
        end_date=date.fromisoformat(end_str),
    )
    db.session.add(ay)
    db.session.commit()
    flash(f'Đã tạo năm học {name}.', 'success')
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
