from flask import render_template, request
from flask_login import login_required
from datetime import date
from sqlalchemy import func, extract
from extensions import db
from models import TuitionPayment, Expense, Student, Class, Attendance, Schedule
from blueprints.admin import admin_bp, require_admin


@admin_bp.route('/bao-cao')
@login_required
@require_admin
def reports():
    today = date.today()
    year = request.args.get('year', today.year, type=int)

    # Monthly revenue
    monthly_revenue = []
    monthly_expenses = []
    for m in range(1, 13):
        rev = db.session.query(func.sum(TuitionPayment.amount)).filter(
            TuitionPayment.is_paid == True,
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
    total_students = Student.query.filter_by(is_active=True).count()
    new_this_year = Student.query.filter(
        extract('year', Student.created_at) == year
    ).count()

    # Class efficiency (current active classes)
    class_stats = []
    for cl in Class.query.filter_by(is_active=True).all():
        total_sessions = cl.schedules.filter(
            Schedule.is_cancelled == False,
            extract('year', Schedule.date) == year,
        ).count()
        total_att = Attendance.query.join(Attendance.schedule).filter(
            Schedule.class_id == cl.id,
            extract('year', Schedule.date) == year,
        ).count()
        absent_count = Attendance.query.join(Attendance.schedule).filter(
            Schedule.class_id == cl.id,
            Attendance.status == 'absent',
            extract('year', Schedule.date) == year,
        ).count()
        absence_rate = (absent_count / total_att * 100) if total_att > 0 else 0
        class_stats.append({
            'class': cl,
            'enrollment': cl.current_enrollment,
            'total_sessions': total_sessions,
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
