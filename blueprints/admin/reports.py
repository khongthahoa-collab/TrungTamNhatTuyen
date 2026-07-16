from flask import render_template, request
from flask_login import login_required
from datetime import date
from sqlalchemy import func, extract
from extensions import db
from models import TuitionPayment, Expense, Student, Class, Attendance, Schedule, Enrollment
from blueprints.admin import admin_bp, require_admin


@admin_bp.route('/reports')
@login_required
@require_admin
def reports():
    today = date.today()
    year = request.args.get('year', today.year, type=int)

    # Monthly revenue
    monthly_revenue = []
    monthly_expenses = []
    for m in range(1, 13):
        # amount_collected (not amount) — a paid/partial row may include
        # collected debt carried over from a previous month, and amount
        # alone is only the current month's fee.
        rev = db.session.query(func.sum(TuitionPayment.amount_collected)).filter(
            TuitionPayment.month == m,
            TuitionPayment.year == year,
        ).scalar() or 0

        exp = db.session.query(func.sum(Expense.amount)).filter(
            extract('month', Expense.expense_date) == m,
            extract('year', Expense.expense_date) == year,
        ).scalar() or 0

        monthly_revenue.append(rev)
        monthly_expenses.append(exp)

    total_revenue = sum(monthly_revenue)
    total_expenses = sum(monthly_expenses)
    profit = total_revenue - total_expenses

    # Student statistics
    total_students = Student.query.filter_by(is_active=True, is_deleted=False).count()
    new_this_year = Student.query.filter(
        extract('year', Student.created_at) == year, Student.is_deleted == False
    ).count()

    # Class efficiency (current active classes) — batched into grouped
    # queries instead of 3-4 queries per class (was 1 + 4N).
    active_classes = Class.query.filter_by(is_active=True).all()
    class_ids = [cl.id for cl in active_classes]

    session_counts, enrollment_counts, att_counts, absent_counts = {}, {}, {}, {}
    if class_ids:
        session_counts = dict(
            db.session.query(Schedule.class_id, func.count(Schedule.id))
            .filter(Schedule.class_id.in_(class_ids), Schedule.is_cancelled == False,
                   extract('year', Schedule.date) == year)
            .group_by(Schedule.class_id).all()
        )
        enrollment_counts = dict(
            db.session.query(Enrollment.class_id, func.count(Enrollment.id))
            .filter(Enrollment.class_id.in_(class_ids), Enrollment.is_active == True)
            .group_by(Enrollment.class_id).all()
        )
        att_counts = dict(
            db.session.query(Schedule.class_id, func.count(Attendance.id))
            .join(Attendance, Attendance.schedule_id == Schedule.id)
            .filter(Schedule.class_id.in_(class_ids), extract('year', Schedule.date) == year)
            .group_by(Schedule.class_id).all()
        )
        absent_counts = dict(
            db.session.query(Schedule.class_id, func.count(Attendance.id))
            .join(Attendance, Attendance.schedule_id == Schedule.id)
            .filter(Schedule.class_id.in_(class_ids), Attendance.status == 'absent',
                   extract('year', Schedule.date) == year)
            .group_by(Schedule.class_id).all()
        )

    class_stats = []
    for cl in active_classes:
        total_att = att_counts.get(cl.id, 0)
        absent_count = absent_counts.get(cl.id, 0)
        absence_rate = (absent_count / total_att * 100) if total_att > 0 else 0
        class_stats.append({
            'class': cl,
            'enrollment': enrollment_counts.get(cl.id, 0),
            'total_sessions': session_counts.get(cl.id, 0),
            'absence_rate': round(absence_rate, 1),
        })

    # Tax deductible expenses
    tax_expenses = db.session.query(func.sum(Expense.amount)).filter(
        Expense.is_tax_deductible == True,
        extract('year', Expense.expense_date) == year,
    ).scalar() or 0

    return render_template('admin/reports/index.html',
                           year=year,
                           today=today,
                           monthly_revenue=monthly_revenue,
                           monthly_expenses=monthly_expenses,
                           total_revenue=total_revenue,
                           total_expenses=total_expenses,
                           profit=profit,
                           total_students=total_students,
                           new_this_year=new_this_year,
                           class_stats=class_stats,
                           tax_expenses=tax_expenses)
