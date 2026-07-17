from datetime import datetime

from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from sqlalchemy import or_
from extensions import db
from models import LeaveRequest, Student, Schedule, Class, Enrollment, Teacher, LeaveRequestStatus
from blueprints.admin import admin_bp, require_admin
from services.zalo_service import ZaloService


@admin_bp.route('/leave-requests', methods=['GET', 'POST'])
@login_required
@require_admin
def manage_leave_requests():
    """Admin/staff-with-attendance-write registers a student's leave of
    absence on the parent's behalf (over phone/Zalo). Read access needs
    'attendance' read, creating one needs 'attendance' write — enforced by
    the standard check_module_permission before_request hook via
    ADMIN_ENDPOINT_MODULES, same as every other admin route."""
    if request.method == 'POST':
        student_id_raw = request.form.get('student_id')
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        reason = request.form.get('reason', '').strip()

        if not all([student_id_raw, start_date_str, end_date_str]):
            flash('Vui lòng điền đầy đủ thông tin học sinh và thời gian xin nghỉ!', 'danger')
            return redirect(url_for('admin.manage_leave_requests'))

        try:
            student_id = int(student_id_raw)
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Định dạng ngày tháng hoặc mã học sinh không hợp lệ.', 'danger')
            return redirect(url_for('admin.manage_leave_requests'))

        if start_date > end_date:
            flash('Ngày bắt đầu nghỉ không được lớn hơn ngày kết thúc phép!', 'danger')
            return redirect(url_for('admin.manage_leave_requests'))

        student = Student.query.get_or_404(student_id)

        new_request = LeaveRequest(
            student_id=student_id,
            parent_id=student.parent_user_id,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            status=LeaveRequestStatus.APPROVED,
            approved_by=current_user.id,
            approved_at=datetime.utcnow(),
        )
        db.session.add(new_request)

        # Only scan the classes this student is actually enrolled in — not
        # every Schedule in the center — then find the teachers affected.
        active_class_ids = [e.class_id for e in
                            Enrollment.query.filter_by(student_id=student.id, is_active=True).all()]

        teacher_ids = set()
        class_names = set()
        if active_class_ids:
            affected_schedules = Schedule.query.join(Class, Schedule.class_id == Class.id).filter(
                Schedule.class_id.in_(active_class_ids),
                Schedule.date >= start_date,
                Schedule.date <= end_date,
                Class.is_active == True,
            ).all()
            for sched in affected_schedules:
                active_teacher_id = sched.substitute_teacher_id or sched.teacher_id
                if active_teacher_id:
                    teacher_ids.add(active_teacher_id)
                if sched.class_:
                    class_names.add(sched.class_.public_name)

        db.session.commit()

        # PII-safe notification: never forward the raw `reason` text (may
        # contain medical/personal detail) to teachers — just the
        # standardized line the spec calls for.
        if teacher_ids:
            teachers = Teacher.query.filter(Teacher.id.in_(teacher_ids)).all()
            phones_names = [(t.phone, t.full_name) for t in teachers if t.phone]
            if phones_names:
                message = (
                    f"Học sinh {student.full_name} lớp {', '.join(sorted(class_names)) or '—'} "
                    f"đăng ký nghỉ học phép từ ngày {start_date.strftime('%d/%m/%Y')} đến hết ngày "
                    f"{end_date.strftime('%d/%m/%Y')} (Nghỉ phép đã được duyệt)."
                )
                ZaloService.send_bulk(message, phones_names)

        flash(f'Đã đăng ký nghỉ phép cho học sinh {student.full_name} và thông báo cho giáo viên liên quan.',
              'success')
        return redirect(url_for('admin.manage_leave_requests'))

    page = request.args.get('page', 1, type=int)
    pagination = (
        LeaveRequest.query.order_by(LeaveRequest.created_at.desc())
        .paginate(page=page, per_page=10, error_out=False)
    )

    return render_template('admin/leave_requests.html', requests=pagination.items, pagination=pagination)


@admin_bp.route('/leave-requests/<int:request_id>/edit', methods=['POST'])
@login_required
@require_admin
def leave_request_edit(request_id):
    leave_request = LeaveRequest.query.get_or_404(request_id)

    start_date_str = request.form.get('start_date')
    end_date_str = request.form.get('end_date')
    reason = request.form.get('reason', '').strip()

    if not all([start_date_str, end_date_str]):
        flash('Vui lòng điền đầy đủ thời gian nghỉ.', 'danger')
        return redirect(url_for('admin.manage_leave_requests'))

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Định dạng ngày tháng không hợp lệ.', 'danger')
        return redirect(url_for('admin.manage_leave_requests'))

    if start_date > end_date:
        flash('Ngày bắt đầu nghỉ không được lớn hơn ngày kết thúc phép!', 'danger')
        return redirect(url_for('admin.manage_leave_requests'))

    leave_request.start_date = start_date
    leave_request.end_date = end_date
    leave_request.reason = reason
    db.session.commit()

    flash(f'Đã cập nhật đơn nghỉ phép của {leave_request.student.full_name if leave_request.student else "học sinh"}.',
          'success')
    return redirect(url_for('admin.manage_leave_requests', page=request.args.get('page', 1)))


@admin_bp.route('/leave-requests/<int:request_id>/cancel', methods=['POST'])
@login_required
@require_admin
def leave_request_cancel(request_id):
    """Cancel a leave request — keeps the record (audit trail) but flips it
    off APPROVED, which immediately un-locks the excused status on the
    teacher's attendance pages since that lookup filters on
    status == APPROVED."""
    leave_request = LeaveRequest.query.get_or_404(request_id)
    leave_request.status = LeaveRequestStatus.REJECTED
    db.session.commit()
    flash(f'Đã hủy đơn nghỉ phép của {leave_request.student.full_name if leave_request.student else "học sinh"}.',
          'success')
    return redirect(url_for('admin.manage_leave_requests', page=request.args.get('page', 1)))


@admin_bp.route('/leave-requests/student-search')
@login_required
@require_admin
def leave_request_student_search():
    """Lightweight AJAX search backing the leave-request form's student
    picker — with 500+ active students, preloading all of them into a
    <select> was slow and unusable, so the form now searches on demand."""
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify([])

    students = Student.query.filter(
        Student.is_active == True,
        Student.is_deleted == False,
        or_(Student.full_name.ilike(f'%{q}%'), Student.parent_phone.ilike(f'%{q}%')),
    ).order_by(Student.full_name).limit(10).all()

    return jsonify([
        {'id': s.id, 'full_name': s.full_name, 'parent_phone': s.parent_phone or ''}
        for s in students
    ])
