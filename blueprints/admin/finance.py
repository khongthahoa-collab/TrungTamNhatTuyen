from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from datetime import date, datetime
from extensions import db
from models import (TuitionPayment, Student, Class, Salary, Teacher,
                    Expense, ExpenseCategory, TuitionMethod)
from blueprints.admin import admin_bp, require_admin
from services.salary_service import calculate_all_salaries, calculate_salary
from services.zalo_service import ZaloService


# ────────────────────────────────────────────────────────────────
# Tuition
# ────────────────────────────────────────────────────────────────

@admin_bp.route('/hoc-phi')
@login_required
@require_admin
def tuition():
    today = date.today()
    month = request.args.get('month', today.month, type=int)
    year = request.args.get('year', today.year, type=int)
    class_id = request.args.get('class_id', type=int)

    query = TuitionPayment.query.filter_by(month=month, year=year)
    if class_id:
        query = query.filter_by(class_id=class_id)

    records = query.order_by(TuitionPayment.is_paid, TuitionPayment.student_id).all()
    classes = Class.query.filter_by(is_active=True).all()

    total_collected = sum(r.amount for r in records if r.is_paid)
    total_pending = sum(r.amount for r in records if not r.is_paid)

    return render_template('admin/finance/tuition.html',
                           records=records,
                           classes=classes,
                           month=month,
                           year=year,
                           selected_class_id=class_id,
                           total_collected=total_collected,
                           total_pending=total_pending,
                           today=today)


@admin_bp.route('/hoc-phi/them', methods=['POST'])
@login_required
@require_admin
def tuition_add():
    student_id = request.form.get('student_id', type=int)
    class_id = request.form.get('class_id', type=int)
    amount = request.form.get('amount', type=float)
    month = request.form.get('month', type=int)
    year = request.form.get('year', type=int)
    note = request.form.get('note', '').strip()

    if not all([student_id, class_id, amount, month, year]):
        flash('Vui lòng điền đầy đủ thông tin.', 'danger')
        return redirect(url_for('admin.tuition'))

    existing = TuitionPayment.query.filter_by(
        student_id=student_id, class_id=class_id, month=month, year=year
    ).first()
    if existing:
        flash('Đã có bản ghi học phí tháng này rồi.', 'warning')
        return redirect(url_for('admin.tuition'))

    tp = TuitionPayment(
        student_id=student_id,
        class_id=class_id,
        amount=amount,
        month=month,
        year=year,
        is_paid=False,
        note=note,
        created_at=datetime.utcnow(),
    )
    db.session.add(tp)
    db.session.commit()
    flash('Đã thêm bản ghi học phí.', 'success')
    return redirect(url_for('admin.tuition', month=month, year=year))


@admin_bp.route('/hoc-phi/<int:payment_id>/thanh-toan', methods=['POST'])
@login_required
@require_admin
def tuition_mark_paid(payment_id):
    tp = TuitionPayment.query.get_or_404(payment_id)
    method = request.form.get('method', 'cash')
    tp.is_paid = True
    tp.method = method
    tp.paid_at = datetime.utcnow()
    tp.received_by = current_user.id
    db.session.commit()
    flash(f'Đã ghi nhận thanh toán học phí cho {tp.student.full_name}.', 'success')
    return redirect(request.referrer or url_for('admin.tuition', month=tp.month, year=tp.year))


@admin_bp.route('/hoc-phi/nhac-zalo', methods=['POST'])
@login_required
@require_admin
def tuition_remind_zalo():
    month = request.form.get('month', type=int)
    year = request.form.get('year', type=int)
    class_id = request.form.get('class_id', type=int)

    from models import SystemConfig
    bank_info = SystemConfig.get('bank_account', '')

    query = TuitionPayment.query.filter_by(month=month, year=year, is_paid=False)
    if class_id:
        query = query.filter_by(class_id=class_id)

    records = query.all()
    sent = 0
    for tp in records:
        ZaloService.send_tuition_reminder(tp.student, tp.class_, month, year, tp.amount, bank_info)
        sent += 1

    flash(f'Đã gửi {sent} thông báo nhắc học phí.', 'success')
    return redirect(url_for('admin.tuition', month=month, year=year))


@admin_bp.route('/hoc-phi/them-hang-loat', methods=['GET', 'POST'])
@login_required
@require_admin
def tuition_bulk_add():
    """Thêm học phí hàng loạt cho một lớp trong một tháng."""
    if request.method == 'POST':
        class_id = request.form.get('class_id', type=int)
        month = request.form.get('month', type=int)
        year = request.form.get('year', type=int)
        amount = request.form.get('amount', type=float)

        if not all([class_id, month, year, amount]):
            flash('Vui lòng điền đầy đủ.', 'danger')
        else:
            class_ = Class.query.get_or_404(class_id)
            added = 0
            for student in class_.active_students:
                exists = TuitionPayment.query.filter_by(
                    student_id=student.id, class_id=class_id, month=month, year=year
                ).first()
                if not exists:
                    tp = TuitionPayment(
                        student_id=student.id,
                        class_id=class_id,
                        amount=amount,
                        month=month,
                        year=year,
                        is_paid=False,
                    )
                    db.session.add(tp)
                    added += 1
            db.session.commit()
            flash(f'Đã thêm {added} bản ghi học phí cho lớp {class_.name}.', 'success')
            return redirect(url_for('admin.tuition', month=month, year=year, class_id=class_id))

    today = date.today()
    classes = Class.query.filter_by(is_active=True).all()
    return render_template('admin/finance/tuition_bulk.html',
                           classes=classes, today=today)


# ────────────────────────────────────────────────────────────────
# Expenses
# ────────────────────────────────────────────────────────────────

@admin_bp.route('/chi-phi')
@login_required
@require_admin
def expenses():
    today = date.today()
    month = request.args.get('month', today.month, type=int)
    year = request.args.get('year', today.year, type=int)
    category = request.args.get('category', '')

    query = Expense.query.filter(
        db.extract('month', Expense.expense_date) == month,
        db.extract('year', Expense.expense_date) == year,
    )
    if category:
        query = query.filter_by(category=category)

    records = query.order_by(Expense.expense_date.desc()).all()
    total = sum(r.amount for r in records)
    tax_deductible = sum(r.amount for r in records if r.is_tax_deductible)

    return render_template('admin/finance/expenses.html',
                           records=records,
                           month=month,
                           year=year,
                           selected_category=category,
                           total=total,
                           tax_deductible=tax_deductible,
                           categories=ExpenseCategory.LABELS,
                           today=today)


@admin_bp.route('/chi-phi/them', methods=['POST'])
@login_required
@require_admin
def expense_add():
    category = request.form.get('category', '')
    amount = request.form.get('amount', type=float)
    description = request.form.get('description', '').strip()
    date_str = request.form.get('expense_date', '')
    is_tax = request.form.get('is_tax_deductible') == '1'
    receipt_no = request.form.get('receipt_no', '').strip()

    if not category or not amount:
        flash('Vui lòng nhập danh mục và số tiền.', 'danger')
        return redirect(url_for('admin.expenses'))

    today = date.today()
    try:
        expense_date = date.fromisoformat(date_str) if date_str else today
    except ValueError:
        expense_date = today

    exp = Expense(
        category=category,
        amount=amount,
        description=description,
        expense_date=expense_date,
        fiscal_year=expense_date.year,
        is_tax_deductible=is_tax,
        receipt_no=receipt_no,
        created_by=current_user.id,
    )
    db.session.add(exp)
    db.session.commit()
    flash('Đã ghi chi phí.', 'success')
    return redirect(url_for('admin.expenses',
                            month=expense_date.month, year=expense_date.year))


@admin_bp.route('/chi-phi/<int:exp_id>/xoa', methods=['POST'])
@login_required
@require_admin
def expense_delete(exp_id):
    exp = Expense.query.get_or_404(exp_id)
    db.session.delete(exp)
    db.session.commit()
    flash('Đã xóa chi phí.', 'success')
    return redirect(request.referrer or url_for('admin.expenses'))


# ────────────────────────────────────────────────────────────────
# Salary
# ────────────────────────────────────────────────────────────────

@admin_bp.route('/luong')
@login_required
@require_admin
def salary():
    today = date.today()
    month = request.args.get('month', today.month, type=int)
    year = request.args.get('year', today.year, type=int)

    salaries = Salary.query.filter_by(month=month, year=year).all()
    staff_teachers = Teacher.query.filter_by(is_staff=True).all()

    return render_template('admin/finance/salary.html',
                           salaries=salaries,
                           staff_teachers=staff_teachers,
                           month=month,
                           year=year,
                           today=today)


@admin_bp.route('/luong/tinh', methods=['POST'])
@login_required
@require_admin
def salary_calculate():
    month = request.form.get('month', type=int)
    year = request.form.get('year', type=int)
    salaries = calculate_all_salaries(month, year)
    flash(f'Đã tính lương cho {len(salaries)} giáo viên tháng {month}/{year}.', 'success')
    return redirect(url_for('admin.salary', month=month, year=year))


@admin_bp.route('/luong/<int:salary_id>/chinh-sua', methods=['POST'])
@login_required
@require_admin
def salary_adjust(salary_id):
    sal = Salary.query.get_or_404(salary_id)
    if sal.is_finalized:
        flash('Lương đã chốt, không thể chỉnh sửa.', 'danger')
        return redirect(url_for('admin.salary', month=sal.month, year=sal.year))

    sal.bonus = request.form.get('bonus', 0, type=float)
    sal.deduction = request.form.get('deduction', 0, type=float)
    sal.note = request.form.get('note', '').strip()
    sal.total = sal.base_amount + sal.bonus - sal.deduction
    db.session.commit()
    flash('Đã cập nhật lương.', 'success')
    return redirect(url_for('admin.salary', month=sal.month, year=sal.year))


@admin_bp.route('/luong/<int:salary_id>/chot', methods=['POST'])
@login_required
@require_admin
def salary_finalize(salary_id):
    sal = Salary.query.get_or_404(salary_id)
    sal.is_finalized = True
    sal.paid_at = datetime.utcnow()
    db.session.commit()
    flash(f'Đã chốt lương cho {sal.teacher.full_name}.', 'success')
    return redirect(url_for('admin.salary', month=sal.month, year=sal.year))
