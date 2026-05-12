from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required
from extensions import db
from models import School, Student
from blueprints.admin import admin_bp, require_admin

GRADE_CHOICES = [
    (0,  'Tiền tiểu học'),
    (1,  'Lớp 1'), (2,  'Lớp 2'), (3,  'Lớp 3'), (4,  'Lớp 4'), (5,  'Lớp 5'),
    (6,  'Lớp 6'), (7,  'Lớp 7'), (8,  'Lớp 8'), (9,  'Lớp 9'),
    (10, 'Lớp 10'), (11, 'Lớp 11'), (12, 'Lớp 12'),
]


@admin_bp.route('/schools')
@login_required
@require_admin
def schools():
    items = School.query.order_by(School.name).all()
    student_counts = {}
    if items:
        from sqlalchemy import func
        rows = (db.session.query(Student.school_id, func.count(Student.id))
                .filter(Student.school_id.isnot(None), Student.is_active == True)
                .group_by(Student.school_id).all())
        student_counts = dict(rows)
    return render_template('admin/schools/list.html',
                           schools=items,
                           student_counts=student_counts,
                           grade_choices=GRADE_CHOICES)


@admin_bp.route('/schools/add', methods=['POST'])
@login_required
@require_admin
def school_add():
    name = request.form.get('name', '').strip()
    grade_from = request.form.get('grade_from', type=int)
    grade_to = request.form.get('grade_to', type=int)

    if not name:
        flash('Vui lòng nhập tên trường.', 'danger')
        return redirect(url_for('admin.schools'))
    if School.query.filter(db.func.lower(School.name) == name.lower()).first():
        flash(f'Trường "{name}" đã tồn tại.', 'warning')
        return redirect(url_for('admin.schools'))
    if grade_from is not None and grade_to is not None and grade_from > grade_to:
        flash('Lớp bắt đầu không thể lớn hơn lớp kết thúc.', 'danger')
        return redirect(url_for('admin.schools'))

    school = School(name=name, grade_from=grade_from, grade_to=grade_to)
    db.session.add(school)
    db.session.commit()
    flash(f'Đã thêm trường "{name}".', 'success')
    return redirect(url_for('admin.schools'))


@admin_bp.route('/schools/<int:school_id>/edit', methods=['POST'])
@login_required
@require_admin
def school_edit(school_id):
    school = School.query.get_or_404(school_id)
    name = request.form.get('name', '').strip()
    grade_from_raw = request.form.get('grade_from', '')
    grade_to_raw = request.form.get('grade_to', '')
    grade_from = int(grade_from_raw) if grade_from_raw != '' else None
    grade_to = int(grade_to_raw) if grade_to_raw != '' else None
    is_active = request.form.get('is_active') == '1'

    if not name:
        flash('Tên trường không được để trống.', 'danger')
        return redirect(url_for('admin.schools'))

    dup = School.query.filter(db.func.lower(School.name) == name.lower(),
                               School.id != school_id).first()
    if dup:
        flash(f'Trường "{name}" đã tồn tại.', 'warning')
        return redirect(url_for('admin.schools'))
    if grade_from is not None and grade_to is not None and grade_from > grade_to:
        flash('Lớp bắt đầu không thể lớn hơn lớp kết thúc.', 'danger')
        return redirect(url_for('admin.schools'))

    school.name = name
    school.grade_from = grade_from
    school.grade_to = grade_to
    school.is_active = is_active

    # Sync current_school text for students linked to this school
    Student.query.filter_by(school_id=school_id).update({'current_school': name})

    db.session.commit()
    flash('Đã cập nhật thông tin trường.', 'success')
    return redirect(url_for('admin.schools'))


@admin_bp.route('/schools/<int:school_id>/delete', methods=['POST'])
@login_required
@require_admin
def school_delete(school_id):
    school = School.query.get_or_404(school_id)
    count = Student.query.filter_by(school_id=school_id, is_active=True).count()
    if count:
        flash(f'Không thể xóa — có {count} học sinh đang liên kết với trường này.', 'danger')
        return redirect(url_for('admin.schools'))
    # Unlink inactive students
    Student.query.filter_by(school_id=school_id).update({'school_id': None})
    db.session.delete(school)
    db.session.commit()
    flash(f'Đã xóa trường "{school.name}".', 'success')
    return redirect(url_for('admin.schools'))
