from datetime import date
from flask import render_template
from flask_login import login_required
from sqlalchemy import case, func
from sqlalchemy.orm import joinedload
from extensions import db
from models import Student, TuitionPayment, Reward, Schedule, Class, Attendance
from blueprints.admin import admin_bp, require_admin


@admin_bp.route('/')
@login_required
@require_admin
def dashboard():
    """Trang Tổng quan — chỉ số thật (tiền, việc cần làm hôm nay), không có
    thẻ tĩnh vô nghĩa hay danh sách log nặng. Mỗi số liệu là 1 truy vấn SQL
    tổng hợp (SUM/COUNT), không tải nguyên danh sách bản ghi về Python rồi
    cộng tay — tránh đúng kiểu N+1/O(N) từng gây 502 trong hệ thống này."""
    today = date.today()

    students_count = Student.query.filter_by(is_active=True, is_deleted=False).count()
    pending_rewards = Reward.query.filter_by(is_suggested=True, is_confirmed=False).count()
    pending_students = Student.query.filter_by(status='pending_confirmation', is_deleted=False).count()

    # Doanh thu tháng này — 1 câu SQL tổng hợp duy nhất, không JOIN, dùng
    # đúng index (year, month) sẵn có. "Còn nợ" chỉ cộng dồn cho hoá đơn
    # CHƯA đóng đủ — khớp đúng công thức đang dùng ở trang Học phí
    # (_tuition_overview_aggregate) để 2 trang không bao giờ lệch số.
    # is_voided loại hoá đơn đã hủy khỏi mọi báo cáo doanh thu.
    total_due_expr = TuitionPayment.amount + TuitionPayment.debt_carried_over
    collected, outstanding = db.session.query(
        func.coalesce(func.sum(TuitionPayment.amount_collected), 0),
        func.coalesce(func.sum(case(
            (TuitionPayment.is_paid == False, total_due_expr - TuitionPayment.amount_collected),
            else_=0,
        )), 0),
    ).filter(
        TuitionPayment.month == today.month,
        TuitionPayment.year == today.year,
        TuitionPayment.is_voided == False,
    ).first()

    # Lịch học hôm nay + đã điểm danh hay chưa — joinedload gộp tên lớp vào
    # cùng 1 câu SELECT (không N+1 khi template đọc s.class_.name), và 1
    # câu query gộp riêng để biết buổi nào đã có điểm danh, thay vì hỏi
    # từng buổi một.
    today_schedules = (
        Schedule.query
        .join(Class, Schedule.class_id == Class.id)
        .options(joinedload(Schedule.class_))
        .filter(Schedule.date == today, Schedule.is_cancelled == False, Class.is_active == True)
        .order_by(Schedule.start_time)
        .all()
    )
    attended_schedule_ids = set()
    if today_schedules:
        schedule_ids = [s.id for s in today_schedules]
        attended_schedule_ids = {
            row[0] for row in
            db.session.query(Attendance.schedule_id)
            .filter(Attendance.schedule_id.in_(schedule_ids))
            .distinct().all()
        }

    return render_template('admin/dashboard.html',
                           today=today,
                           students_count=students_count,
                           pending_rewards=pending_rewards,
                           pending_students=pending_students,
                           collected=collected,
                           outstanding=outstanding,
                           today_schedules=today_schedules,
                           attended_schedule_ids=attended_schedule_ids)
