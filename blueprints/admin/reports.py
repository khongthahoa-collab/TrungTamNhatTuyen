from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required
from datetime import date
from sqlalchemy import func, extract
from extensions import db
from models import TuitionPayment, Expense, ExpenseCategory, Teacher, User, ExpenseForecast
from blueprints.admin import admin_bp, require_admin
from services.tuition_service import forecast_monthly_revenue


@admin_bp.route('/reports')
@login_required
@require_admin
def reports():
    today = date.today()
    month = request.args.get('month', today.month, type=int)
    year = request.args.get('year', today.year, type=int)
    view = request.args.get('view', '')  # '' | 'du_thu' | 'luong' | 'khac'

    # Dự thu — dự báo học phí phải thu tháng này (trước khi lập hoá đơn).
    du_thu, du_thu_detail = forecast_monthly_revenue(month, year)

    # Dự chi = tổng lương cơ bản GV đang hoạt động + chi phí khác dự kiến
    # (admin tự nhập, vì không có định mức tự tính cho khoản này).
    active_teachers = (Teacher.query.join(Teacher.user)
                       .filter(User.is_deleted == False)
                       .order_by(User.full_name).all())
    du_chi_luong = sum(t.base_salary or 0 for t in active_teachers)
    forecast_row = ExpenseForecast.query.filter_by(month=month, year=year).first()
    du_chi_khac = forecast_row.amount if forecast_row else 0
    du_chi = du_chi_luong + du_chi_khac

    # Tổng thu — học phí thực thu tháng này.
    tong_thu = db.session.query(func.sum(TuitionPayment.amount_collected)).filter(
        TuitionPayment.month == month,
        TuitionPayment.year == year,
        TuitionPayment.is_voided == False,
    ).scalar() or 0

    # Tổng chi — chi phí thực tế tháng này, tách Lương GV / Chi phí khác.
    tong_chi_luong = db.session.query(func.sum(Expense.amount)).filter(
        Expense.category == ExpenseCategory.SALARY,
        extract('month', Expense.expense_date) == month,
        extract('year', Expense.expense_date) == year,
    ).scalar() or 0
    tong_chi_khac = db.session.query(func.sum(Expense.amount)).filter(
        Expense.category != ExpenseCategory.SALARY,
        extract('month', Expense.expense_date) == month,
        extract('year', Expense.expense_date) == year,
    ).scalar() or 0
    tong_chi = tong_chi_luong + tong_chi_khac

    # Xem chi tiết theo mục đang chọn.
    detail_rows = None
    if view == 'luong':
        detail_rows = Expense.query.filter(
            Expense.category == ExpenseCategory.SALARY,
            extract('month', Expense.expense_date) == month,
            extract('year', Expense.expense_date) == year,
        ).order_by(Expense.expense_date.desc()).all()
    elif view == 'khac':
        detail_rows = Expense.query.filter(
            Expense.category != ExpenseCategory.SALARY,
            extract('month', Expense.expense_date) == month,
            extract('year', Expense.expense_date) == year,
        ).order_by(Expense.expense_date.desc()).all()

    return render_template('admin/reports/index.html',
                           month=month, year=year, today=today, view=view,
                           du_thu=du_thu, du_thu_detail=du_thu_detail,
                           du_chi=du_chi, du_chi_luong=du_chi_luong, du_chi_khac=du_chi_khac,
                           active_teachers=active_teachers,
                           forecast_note=forecast_row.note if forecast_row else '',
                           tong_thu=tong_thu,
                           tong_chi=tong_chi, tong_chi_luong=tong_chi_luong, tong_chi_khac=tong_chi_khac,
                           detail_rows=detail_rows)


@admin_bp.route('/reports/expense-forecast', methods=['POST'])
@login_required
@require_admin
def reports_expense_forecast_save():
    month = request.form.get('month', type=int)
    year = request.form.get('year', type=int)
    amount = request.form.get('amount', 0, type=float)
    note = request.form.get('note', '').strip()

    row = ExpenseForecast.query.filter_by(month=month, year=year).first()
    if not row:
        row = ExpenseForecast(month=month, year=year)
        db.session.add(row)
    row.amount = amount
    row.note = note
    db.session.commit()
    flash(f'Đã lưu chi phí khác dự kiến tháng {month}/{year}.', 'success')
    return redirect(url_for('admin.reports', month=month, year=year))
