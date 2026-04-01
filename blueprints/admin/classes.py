from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required
from datetime import date, timedelta
from extensions import db
from models import Class, Course, Teacher, Schedule, Semester, Enrollment, Student
from blueprints.admin import admin_bp, require_admin
import calendar


@admin_bp.route('/lop-hoc')
@login_required
@require_admin
def classes():
    q = request.args.get('q', '').strip()
    active_only = request.args.get('active', '1')
    query = Class.query
    if q:
        query = query.filter(Class.name.ilike(f'%{q}%'))
    if active_only == '1':
        query = query.filter_by(is_active=True)
    classes = query.order_by(Class.name).all()
    return render_template('admin/classes/list.html',
                           classes=classes, q=q, active_only=active_only)


@admin_bp.route('/lop-hoc/them', methods=['GET', 'POST'])
@login_required
@require_admin
def class_add():
    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()
    teachers = Teacher.query.join(Teacher.user).order_by('full_name').all()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        course_id = request.form.get('course_id', type=int)
        grade_level = request.form.get('grade_level', '').strip()
        max_students = request.form.get('max_students', 20, type=int)
        start_str = request.form.get('start_date', '')
        end_str = request.form.get('end_date', '')
        description = request.form.get('description', '').strip()

        if not name or not course_id:
            flash('Vui lòng nhập tên lớp và chọn môn học.', 'danger')
        else:
            cl = Class(
                name=name,
                course_id=course_id,
                grade_level=grade_level,
                max_students=max_students,
                start_date=date.fromisoformat(start_str) if start_str else None,
                end_date=date.fromisoformat(end_str) if end_str else None,
                description=description,
            )
            db.session.add(cl)
            db.session.commit()
            flash(f'Đã tạo lớp {name}.', 'success')
            return redirect(url_for('admin.class_detail', class_id=cl.id))

    return render_template('admin/classes/form.html',
                           action='add', courses=courses, teachers=teachers, form={})


@admin_bp.route('/lop-hoc/<int:class_id>')
@login_required
@require_admin
def class_detail(class_id):
    class_ = Class.query.get_or_404(class_id)
    teachers = Teacher.query.join(Teacher.user).all()
    semesters = Semester.query.order_by(Semester.start_date.desc()).all()
    today = date.today()

    # Upcoming schedules
    upcoming = class_.schedules.filter(
        Schedule.date >= today
    ).order_by(Schedule.date, Schedule.start_time).limit(10).all()

    # Past schedules (last 10)
    past = class_.schedules.filter(
        Schedule.date < today
    ).order_by(Schedule.date.desc()).limit(10).all()

    return render_template('admin/classes/detail.html',
                           class_=class_,
                           teachers=teachers,
                           semesters=semesters,
                           upcoming=upcoming,
                           past=past,
                           today=today)


@admin_bp.route('/lop-hoc/<int:class_id>/sua', methods=['GET', 'POST'])
@login_required
@require_admin
def class_edit(class_id):
    class_ = Class.query.get_or_404(class_id)
    courses = Course.query.filter_by(is_active=True).all()

    if request.method == 'POST':
        class_.name = request.form.get('name', class_.name).strip()
        class_.course_id = request.form.get('course_id', type=int) or class_.course_id
        class_.grade_level = request.form.get('grade_level', '').strip()
        class_.max_students = request.form.get('max_students', type=int) or class_.max_students
        start_str = request.form.get('start_date', '')
        end_str = request.form.get('end_date', '')
        class_.start_date = date.fromisoformat(start_str) if start_str else class_.start_date
        class_.end_date = date.fromisoformat(end_str) if end_str else class_.end_date
        class_.description = request.form.get('description', '').strip()
        class_.is_active = request.form.get('is_active') == '1'
        db.session.commit()
        flash('Đã cập nhật thông tin lớp.', 'success')
        return redirect(url_for('admin.class_detail', class_id=class_id))

    return render_template('admin/classes/form.html',
                           action='edit', class_=class_, courses=courses, form=class_)


@admin_bp.route('/lop-hoc/<int:class_id>/tao-lich', methods=['POST'])
@login_required
@require_admin
def generate_schedule(class_id):
    """Generate recurring schedule for a class within a semester."""
    class_ = Class.query.get_or_404(class_id)

    semester_id = request.form.get('semester_id', type=int)
    teacher_id = request.form.get('teacher_id', type=int)
    days_of_week = request.form.getlist('days_of_week')  # ['0','2','4'] = Mon/Wed/Fri
    start_time_str = request.form.get('start_time', '')
    end_time_str = request.form.get('end_time', '')
    room = request.form.get('room', '').strip()

    if not semester_id or not days_of_week or not start_time_str or not end_time_str:
        flash('Vui lòng điền đầy đủ thông tin lịch học.', 'danger')
        return redirect(url_for('admin.class_detail', class_id=class_id))

    semester = Semester.query.get_or_404(semester_id)

    from datetime import time as time_type
    try:
        start_time = time_type.fromisoformat(start_time_str)
        end_time = time_type.fromisoformat(end_time_str)
    except ValueError:
        flash('Giờ học không hợp lệ.', 'danger')
        return redirect(url_for('admin.class_detail', class_id=class_id))

    target_days = [int(d) for d in days_of_week]
    current = semester.start_date
    count = 0

    while current <= semester.end_date:
        if current.weekday() in target_days:
            # Check if schedule already exists for this date/class/time
            exists = Schedule.query.filter_by(
                class_id=class_id,
                date=current,
                start_time=start_time,
            ).first()
            if not exists:
                s = Schedule(
                    class_id=class_id,
                    teacher_id=teacher_id,
                    date=current,
                    start_time=start_time,
                    end_time=end_time,
                    room=room,
                    schedule_type='regular',
                    semester_id=semester_id,
                )
                db.session.add(s)
                count += 1
        current += timedelta(days=1)

    db.session.commit()
    flash(f'Đã tạo {count} buổi học cho {class_.name}.', 'success')
    return redirect(url_for('admin.class_detail', class_id=class_id))


@admin_bp.route('/lop-hoc/<int:class_id>/them-lich', methods=['POST'])
@login_required
@require_admin
def add_schedule(class_id):
    """Add a single schedule (for intensive or one-off)."""
    class_ = Class.query.get_or_404(class_id)

    teacher_id = request.form.get('teacher_id', type=int)
    date_str = request.form.get('date', '')
    start_str = request.form.get('start_time', '')
    end_str = request.form.get('end_time', '')
    room = request.form.get('room', '').strip()
    topic = request.form.get('topic', '').strip()
    schedule_type = request.form.get('schedule_type', 'regular')
    semester_id = request.form.get('semester_id', type=int)

    from datetime import time as time_type
    try:
        sched_date = date.fromisoformat(date_str)
        start_time = time_type.fromisoformat(start_str)
        end_time = time_type.fromisoformat(end_str)
    except ValueError:
        flash('Ngày hoặc giờ không hợp lệ.', 'danger')
        return redirect(url_for('admin.class_detail', class_id=class_id))

    s = Schedule(
        class_id=class_id,
        teacher_id=teacher_id,
        date=sched_date,
        start_time=start_time,
        end_time=end_time,
        room=room,
        topic=topic,
        schedule_type=schedule_type,
        semester_id=semester_id,
    )
    db.session.add(s)

    # Notify parents of intensive schedule
    if schedule_type == 'intensive':
        from services.zalo_service import ZaloService
        for student in class_.active_students:
            ZaloService.send_intensive_schedule(student, s)

    db.session.commit()
    type_label = 'tăng cường' if schedule_type == 'intensive' else 'thường'
    flash(f'Đã thêm lịch {type_label} ngày {sched_date.strftime("%d/%m/%Y")}.', 'success')
    return redirect(url_for('admin.class_detail', class_id=class_id))


@admin_bp.route('/lich/<int:schedule_id>/huy', methods=['POST'])
@login_required
@require_admin
def cancel_schedule(schedule_id):
    schedule = Schedule.query.get_or_404(schedule_id)
    reason = request.form.get('reason', '').strip()
    schedule.is_cancelled = True
    schedule.cancel_reason = reason

    # Notify parents
    from services.zalo_service import ZaloService
    for student in schedule.class_.active_students:
        ZaloService.send_cancel_notification(student, schedule)

    db.session.commit()
    flash('Đã hủy buổi học và gửi thông báo.', 'success')
    return redirect(request.referrer or url_for('admin.class_detail', class_id=schedule.class_id))


@admin_bp.route('/lich/<int:schedule_id>/xoa', methods=['POST'])
@login_required
@require_admin
def delete_schedule(schedule_id):
    schedule = Schedule.query.get_or_404(schedule_id)
    class_id = schedule.class_id
    db.session.delete(schedule)
    db.session.commit()
    flash('Đã xóa buổi học.', 'success')
    return redirect(request.referrer or url_for('admin.class_detail', class_id=class_id))
