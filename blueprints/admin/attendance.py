from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import date, datetime, timedelta
from sqlalchemy.orm import joinedload
from extensions import db
from models import Schedule, Attendance, AttendanceSummary, Class, Enrollment, Student
from blueprints.admin import admin_bp, require_admin
from services.zalo_service import ZaloService


@admin_bp.route('/attendance')
@login_required
@require_admin
def attendance_list():
    """Admin: list of upcoming and recent class sessions with attendance
    status. Pending/done are split at the SQL level (Schedule.attendances.any())
    and paginated independently — the 60-day-back + 7-day-forward window
    across every class could otherwise return hundreds of rows in one shot.

    view=day is a parallel, opt-in mode for browsing a single day's full
    schedule (with a date switcher) — kept separate from the default
    status-split view above so the "which sessions still need attendance"
    workflow isn't lost."""
    today = date.today()
    class_id = request.args.get('class_id', type=int)
    view_mode = request.args.get('view', 'day')
    if view_mode not in ('status', 'day'):
        view_mode = 'day'

    classes = Class.query.filter_by(is_active=True).order_by(Class.name).all()

    if view_mode == 'day':
        date_str = request.args.get('date', '')
        try:
            target_date = date.fromisoformat(date_str) if date_str else today
        except ValueError:
            target_date = today

        day_query = Schedule.query.join(Class, Schedule.class_id == Class.id).options(
            joinedload(Schedule.class_)
        ).filter(
            Schedule.date == target_date,
            Schedule.is_cancelled == False,
            Class.is_active == True,
        )
        if class_id:
            day_query = day_query.filter(Schedule.class_id == class_id)
        day_schedules = day_query.order_by(Schedule.start_time).all()

        summaries = AttendanceSummary.query.filter(
            AttendanceSummary.schedule_id.in_([s.id for s in day_schedules])
        ).all()
        summary_dict = {s.schedule_id: s for s in summaries}

        class_ids = {s.class_id for s in day_schedules}
        enrollment_counts = dict(
            db.session.query(Enrollment.class_id, db.func.count(Enrollment.id))
            .filter(Enrollment.class_id.in_(class_ids), Enrollment.is_active == True)
            .group_by(Enrollment.class_id)
            .all()
        ) if class_ids else {}

        return render_template('admin/classes/attendance_list.html',
                               view_mode=view_mode,
                               day_schedules=day_schedules,
                               target_date=target_date,
                               prev_date=target_date - timedelta(days=1),
                               next_date=target_date + timedelta(days=1),
                               prev_week_date=target_date - timedelta(days=7),
                               next_week_date=target_date + timedelta(days=7),
                               summaries=summary_dict,
                               enrollment_counts=enrollment_counts,
                               classes=classes,
                               selected_class_id=class_id,
                               is_filtered=bool(class_id),
                               today=today)

    pending_page = request.args.get('pending_page', 1, type=int)
    done_page = request.args.get('done_page', 1, type=int)

    base_query = Schedule.query.filter_by(is_cancelled=False)
    if class_id:
        base_query = base_query.filter_by(class_id=class_id)
    base_query = base_query.filter(
        Schedule.date >= today - timedelta(days=60),
        Schedule.date <= today + timedelta(days=7),
    )

    pending_pagination = (
        base_query.filter(~Schedule.attendances.any())
        .order_by(Schedule.date.desc(), Schedule.start_time)
        .paginate(page=pending_page, per_page=10, error_out=False)
    )
    done_pagination = (
        base_query.filter(Schedule.attendances.any())
        .order_by(Schedule.date.desc(), Schedule.start_time)
        .paginate(page=done_page, per_page=10, error_out=False)
    )

    page_schedules = pending_pagination.items + done_pagination.items
    summaries = AttendanceSummary.query.filter(
        AttendanceSummary.schedule_id.in_([s.id for s in page_schedules])
    ).all()
    summary_dict = {s.schedule_id: s for s in summaries}

    # Batch enrollment counts for the classes shown on this page instead of
    # the per-row Class.current_enrollment property (1 COUNT query/row).
    class_ids = {s.class_id for s in page_schedules}
    enrollment_counts = dict(
        db.session.query(Enrollment.class_id, db.func.count(Enrollment.id))
        .filter(Enrollment.class_id.in_(class_ids), Enrollment.is_active == True)
        .group_by(Enrollment.class_id)
        .all()
    ) if class_ids else {}

    return render_template('admin/classes/attendance_list.html',
                           view_mode=view_mode,
                           pending_list=pending_pagination.items,
                           done_list=done_pagination.items,
                           pending_pagination=pending_pagination,
                           done_pagination=done_pagination,
                           summaries=summary_dict,
                           enrollment_counts=enrollment_counts,
                           classes=classes,
                           selected_class_id=class_id,
                           is_filtered=bool(class_id),
                           today=today)


@admin_bp.route('/attendance/<int:schedule_id>')
@login_required
@require_admin
def attendance_session(schedule_id):
    """Admin: attendance form for a specific session"""
    schedule = Schedule.query.get_or_404(schedule_id)
    enrollments = Enrollment.query.filter_by(
        class_id=schedule.class_id, is_active=True
    ).all()
    attendances = Attendance.query.filter_by(schedule_id=schedule_id).all()
    attendance_dict = {a.student_id: a for a in attendances}

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

    return render_template('admin/classes/attendance_session.html',
                           schedule=schedule,
                           enrollments=enrollments,
                           attendance_dict=attendance_dict,
                           summary=summary,
                           center_name=center_name,
                           center_phone=center_phone)


@admin_bp.route('/api/attendance/<int:schedule_id>/save', methods=['POST'])
@login_required
@require_admin
def save_attendance(schedule_id):
    """Admin: save attendance records for a session"""
    schedule = Schedule.query.get_or_404(schedule_id)
    data = request.get_json()
    attendance_records = data.get('attendance', [])

    present_count = absent_count = late_count = excused_count = 0

    for record in attendance_records:
        student_id = record['student_id']
        status = record['status']
        reason = record.get('reason', '')

        att = Attendance.query.filter_by(
            schedule_id=schedule_id, student_id=student_id
        ).first()
        if not att:
            att = Attendance(schedule_id=schedule_id, student_id=student_id)
            db.session.add(att)

        att.status = status
        att.reason = reason
        att.recorded_by = current_user.id
        att.recorded_at = datetime.utcnow()

        if status == 'present':
            present_count += 1
        elif status == 'absent':
            absent_count += 1
        elif status == 'late':
            late_count += 1
        elif status == 'excused':
            excused_count += 1

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

    return jsonify({'success': True, 'message': 'Lưu điểm danh thành công', 'summary': summary_data})
