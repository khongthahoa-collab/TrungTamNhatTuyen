from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import date, datetime
from extensions import db
from models import (TuitionPayment, Student, Class, Salary, Teacher,
                    Expense, ExpenseCategory, TuitionMethod, MonthlyClassFee, Enrollment)
from blueprints.admin import admin_bp, require_admin
from services.salary_service import calculate_all_salaries, calculate_salary
from services.zalo_service import ZaloService


# ────────────────────────────────────────────────────────────────
# Tuition
# ────────────────────────────────────────────────────────────────

@admin_bp.route('/tuition')
@login_required
@require_admin
def tuition():
    today = date.today()
    month = request.args.get('month', today.month, type=int)
    year = request.args.get('year', today.year, type=int)
    class_id = request.args.get('class_id', type=int)

    # Danh sách thanh toán
    query = TuitionPayment.query.filter_by(month=month, year=year)
    if class_id:
        query = query.filter_by(class_id=class_id)
    records = query.order_by(TuitionPayment.student_id).all()

    classes = Class.query.filter_by(is_active=True).order_by(Class.name).all()
    total_collected = sum(r.amount for r in records if r.is_paid)
    total_pending   = sum(r.amount for r in records if not r.is_paid)

    # Nhóm theo lớp để hiển thị bảng tóm tắt
    from collections import defaultdict
    by_class = defaultdict(list)
    for r in records:
        by_class[r.class_id].append(r)

    class_summaries = []
    for cls in classes:
        if class_id and cls.id != class_id:
            continue
        recs = by_class.get(cls.id, [])
        if not recs:
            continue
        class_summaries.append({
            'class':         cls,
            'total':         len(recs),
            'paid_count':    sum(1 for r in recs if r.is_paid),
            'unpaid_count':  sum(1 for r in recs if not r.is_paid),
            'paid_amount':   sum(r.amount for r in recs if r.is_paid),
            'unpaid_amount': sum(r.amount for r in recs if not r.is_paid),
        })

    # Cấu hình học phí theo lớp (MonthlyClassFee)
    existing_fees = {
        f.class_id: f for f in
        MonthlyClassFee.query.filter_by(month=month, year=year).all()
    }
    fee_configs = [
        {'class': cls, 'config': existing_fees.get(cls.id)}
        for cls in (classes if not class_id else [c for c in classes if c.id == class_id])
    ]

    return render_template('admin/finance/tuition.html',
                           records=records,
                           classes=classes,
                           class_summaries=class_summaries,
                           month=month,
                           year=year,
                           selected_class_id=class_id,
                           total_collected=total_collected,
                           total_pending=total_pending,
                           fee_configs=fee_configs,
                           today=today)


@admin_bp.route('/tuition/class/<int:class_id>')
@login_required
@require_admin
def tuition_class_detail(class_id):
    """Chi tiết học phí của một lớp trong một tháng"""
    today = date.today()
    month = request.args.get('month', today.month, type=int)
    year  = request.args.get('year',  today.year,  type=int)

    cls = Class.query.get_or_404(class_id)
    records = TuitionPayment.query.filter_by(
        class_id=class_id, month=month, year=year
    ).order_by(TuitionPayment.is_paid, TuitionPayment.student_id).all()

    unpaid = [r for r in records if not r.is_paid]
    paid   = [r for r in records if r.is_paid]

    return render_template('admin/finance/tuition_class_detail.html',
                           cls=cls, records=records,
                           unpaid=unpaid, paid=paid,
                           month=month, year=year, today=today)


@admin_bp.route('/tuition/add', methods=['POST'])
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


@admin_bp.route('/tuition/<int:payment_id>/mark-paid', methods=['POST'])
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


@admin_bp.route('/tuition/zalo-remind', methods=['POST'])
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


@admin_bp.route('/tuition/bulk-add', methods=['GET', 'POST'])
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

@admin_bp.route('/expenses')
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


@admin_bp.route('/expenses/add', methods=['POST'])
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


@admin_bp.route('/expenses/<int:exp_id>/delete', methods=['POST'])
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

@admin_bp.route('/salary')
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


@admin_bp.route('/salary/calculate', methods=['POST'])
@login_required
@require_admin
def salary_calculate():
    month = request.form.get('month', type=int)
    year = request.form.get('year', type=int)
    salaries = calculate_all_salaries(month, year)
    flash(f'Đã tính lương cho {len(salaries)} giáo viên tháng {month}/{year}.', 'success')
    return redirect(url_for('admin.salary', month=month, year=year))


@admin_bp.route('/salary/<int:salary_id>/adjust', methods=['POST'])
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


@admin_bp.route('/salary/<int:salary_id>/finalize', methods=['POST'])
@login_required
@require_admin
def salary_finalize(salary_id):
    sal = Salary.query.get_or_404(salary_id)
    sal.is_finalized = True
    sal.paid_at = datetime.utcnow()
    db.session.commit()
    flash(f'Đã chốt lương cho {sal.teacher.full_name}.', 'success')
    return redirect(url_for('admin.salary', month=sal.month, year=sal.year))


# ────────────────────────────────────────────────────────────────
# Tuition Calculation & Reports
# ────────────────────────────────────────────────────────────────

@admin_bp.route('/tuition/report')
@login_required
@require_admin
def tuition_report():
    """Tuition statistics by class and month"""
    from models import TuitionReport
    today = date.today()
    month = request.args.get('month', today.month, type=int)
    year = request.args.get('year', today.year, type=int)
    class_id = request.args.get('class_id', type=int)

    query = TuitionReport.query.filter_by(month=month, year=year)
    if class_id:
        query = query.filter_by(class_id=class_id)

    reports = query.all()
    classes = Class.query.filter_by(is_active=True).all()

    # Calculate totals
    total_amount = sum(r.total_amount for r in reports)
    total_fully_paid = sum(r.fully_paid_count for r in reports)
    total_students = sum(r.total_students for r in reports)

    return render_template('admin/finance/tuition_report.html',
                           reports=reports,
                           classes=classes,
                           month=month,
                           year=year,
                           selected_class_id=class_id,
                           total_amount=total_amount,
                           total_fully_paid=total_fully_paid,
                           total_students=total_students)


@admin_bp.route('/tuition/calculate', methods=['POST'])
@login_required
@require_admin
def calculate_tuition():
    """Calculate tuition stages (25%, 50%, 75%, 100%) for a month"""
    from models import TuitionReport
    
    month = request.form.get('month', type=int)
    year = request.form.get('year', type=int)
    class_id = request.form.get('class_id', type=int)

    if not month or not year:
        flash('Vui lòng chọn tháng và năm.', 'danger')
        return redirect(url_for('admin.tuition_report'))

    # Get all tuition payments for the month
    query = TuitionPayment.query.filter_by(month=month, year=year)
    if class_id:
        query = query.filter_by(class_id=class_id)

    payments = query.all()

    # Group by class
    by_class = {}
    for payment in payments:
        if payment.class_id not in by_class:
            by_class[payment.class_id] = []
        by_class[payment.class_id].append(payment)

    # Calculate stages for each class
    for cid, class_payments in by_class.items():
        class_obj = Class.query.get(cid)
        
        # Calculate stage amounts
        total_amount = sum(p.amount for p in class_payments)
        
        for payment in class_payments:
            stage_25 = payment.amount * 0.25
            stage_50 = payment.amount * 0.50
            stage_75 = payment.amount * 0.75
            stage_100 = payment.amount * 1.0
            
            payment.amount_25pct = stage_25
            payment.amount_50pct = stage_50
            payment.amount_75pct = stage_75
            payment.amount_100pct = stage_100
            
            # Set default payment stage
            if not payment.payment_stage or payment.payment_stage == '100':
                payment.payment_stage = '100'
        
        # Create or update report
        report = TuitionReport.query.filter_by(
            class_id=cid,
            month=month,
            year=year
        ).first()
        
        if not report:
            report = TuitionReport(
                class_id=cid,
                month=month,
                year=year
            )
            db.session.add(report)
        
        report.total_students = len(class_payments)
        report.total_amount = total_amount
        report.amount_25pct_total = sum(p.amount_25pct for p in class_payments if p.amount_25pct)
        report.amount_50pct_total = sum(p.amount_50pct for p in class_payments if p.amount_50pct)
        report.amount_75pct_total = sum(p.amount_75pct for p in class_payments if p.amount_75pct)
        report.amount_100pct_total = sum(p.amount_100pct for p in class_payments if p.amount_100pct)
        report.fully_paid_count = sum(1 for p in class_payments if p.is_paid)
        report.partial_paid_count = sum(1 for p in class_payments if p.is_paid and not p.is_finalized)
        report.unpaid_count = sum(1 for p in class_payments if not p.is_paid)

    db.session.commit()
    flash('Tính toán học phí thành công!', 'success')
    
    return redirect(url_for('admin.tuition_report', month=month, year=year, class_id=class_id))


@admin_bp.route('/tuition/<int:payment_id>/update-stage', methods=['POST'])
@login_required
@require_admin
def update_tuition_stage(payment_id):
    """Update payment stage for a tuition payment"""
    payment = TuitionPayment.query.get_or_404(payment_id)
    
    stage = request.form.get('stage', '100')
    school_name = request.form.get('school_name', '').strip()
    note_special = request.form.get('note_special', '').strip()
    
    payment.payment_stage = stage
    payment.school_name = school_name
    payment.note_special = note_special
    
    # Update amount based on stage
    if stage == '25':
        payment.amount = payment.amount_25pct
    elif stage == '50':
        payment.amount = payment.amount_50pct
    elif stage == '75':
        payment.amount = payment.amount_75pct
    else:  # 100
        payment.amount = payment.amount_100pct
    
    db.session.commit()
    flash('Cập nhật giai đoạn học phí thành công!', 'success')
    
    return redirect(url_for('admin.tuition', month=payment.month, year=payment.year))


@admin_bp.route('/tuition/export', methods=['POST'])
@login_required
@require_admin
def export_tuition_report():
    """Export tuition report to Excel"""
    import csv
    from io import StringIO
    from flask import make_response
    from models import TuitionReport
    
    month = request.form.get('month', type=int)
    year = request.form.get('year', type=int)
    
    if not month or not year:
        flash('Vui lòng chọn tháng và năm.', 'danger')
        return redirect(url_for('admin.tuition_report'))
    
    reports = TuitionReport.query.filter_by(month=month, year=year).all()
    
    # Create CSV
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Báo Cáo Học Phí - Tháng {}/{}'.format(month, year), '', '', '', '', ''])
    writer.writerow([''])
    writer.writerow(['Lớp Học', 'Sĩ Số', 'Tổng Học Phí', '25%', '50%', '75%', '100%', 'Tỉ Lệ Thu'])
    
    for report in reports:
        class_obj = Class.query.get(report.class_id)
        writer.writerow([
            class_obj.name if class_obj else 'N/A',
            report.total_students,
            '{:,.0f}'.format(report.total_amount),
            '{:,.0f}'.format(report.amount_25pct_total),
            '{:,.0f}'.format(report.amount_50pct_total),
            '{:,.0f}'.format(report.amount_75pct_total),
            '{:,.0f}'.format(report.amount_100pct_total),
            '{}%'.format(report.collection_rate)
        ])
    
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename="tuition_report_{}_{}.csv"'.format(month, year)
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    return response


# ────────────────────────────────────────────────────────────────
# Monthly Class Fee Management (học phí theo tháng)
# ────────────────────────────────────────────────────────────────

@admin_bp.route('/tuition/monthly')
@login_required
@require_admin
def monthly_fees():
    """Redirect về trang học phí gộp"""
    month = request.args.get('month', date.today().month, type=int)
    year  = request.args.get('year',  date.today().year,  type=int)
    return redirect(url_for('admin.tuition', month=month, year=year))


@admin_bp.route('/tuition/monthly/update', methods=['POST'])
@login_required
@require_admin
def monthly_fee_update():
    """Cập nhật cấu hình học phí (số tuần) cho một lớp trong một tháng"""
    class_id = request.form.get('class_id', type=int)
    month = request.form.get('month', type=int)
    year = request.form.get('year', type=int)
    standard_weeks = request.form.get('standard_weeks', 4, type=int)
    weeks_billed = request.form.get('weeks_billed', type=float)
    note = request.form.get('note', '').strip()

    cls = Class.query.get_or_404(class_id)

    cfg = MonthlyClassFee.query.filter_by(
        class_id=class_id, month=month, year=year
    ).first()
    if not cfg:
        cfg = MonthlyClassFee(
            class_id=class_id, month=month, year=year,
            created_by=current_user.id
        )
        db.session.add(cfg)

    cfg.standard_weeks = standard_weeks
    cfg.weeks_billed = weeks_billed if weeks_billed is not None else standard_weeks
    cfg.base_fee = cls.monthly_fee
    cfg.note = note
    cfg.recalculate()
    db.session.commit()

    flash(f'Đã cập nhật học phí lớp {cls.name} tháng {month}/{year}: '
          f'{int(cfg.adjusted_fee):,}₫ ({cfg.weeks_billed}/{cfg.standard_weeks} tuần).', 'success')
    return redirect(url_for('admin.monthly_fees', month=month, year=year))


@admin_bp.route('/tuition/monthly/generate', methods=['POST'])
@login_required
@require_admin
def monthly_fee_generate():
    """Tạo hàng loạt TuitionPayment cho tất cả học sinh đang học trong tháng"""
    month = request.form.get('month', type=int)
    year = request.form.get('year', type=int)
    class_id = request.form.get('class_id', type=int)  # None = tất cả lớp

    configs_q = MonthlyClassFee.query.filter_by(month=month, year=year)
    if class_id:
        configs_q = configs_q.filter_by(class_id=class_id)
    configs = configs_q.all()

    if not configs:
        flash('Chưa có cấu hình học phí tháng này. Hãy thiết lập số tuần cho từng lớp trước.', 'warning')
        return redirect(url_for('admin.monthly_fees', month=month, year=year))

    created = updated = 0
    for cfg in configs:
        enrollments = Enrollment.query.filter_by(
            class_id=cfg.class_id, is_active=True
        ).all()
        for enr in enrollments:
            existing = TuitionPayment.query.filter_by(
                student_id=enr.student_id, class_id=cfg.class_id,
                month=month, year=year
            ).first()
            if existing:
                # Chỉ cập nhật nếu chưa thanh toán
                if not existing.is_paid:
                    existing.amount = cfg.adjusted_fee
                    existing.amount_100pct = cfg.base_fee
                    updated += 1
            else:
                tp = TuitionPayment(
                    student_id=enr.student_id,
                    class_id=cfg.class_id,
                    amount=cfg.adjusted_fee,
                    amount_100pct=cfg.base_fee,
                    month=month, year=year,
                    is_paid=False,
                    note=f'Tự động tạo: {cfg.weeks_billed}/{cfg.standard_weeks} tuần',
                )
                db.session.add(tp)
                created += 1

    db.session.commit()
    flash(f'Đã tạo {created} học phí mới, cập nhật {updated} học phí cũ cho tháng {month}/{year}.', 'success')
    return redirect(url_for('admin.tuition', month=month, year=year))


@admin_bp.route('/tuition/<int:payment_id>/adjust-amount', methods=['POST'])
@login_required
@require_admin
def tuition_adjust_amount(payment_id):
    """Admin điều chỉnh số tiền học phí cho từng học sinh cụ thể"""
    tp = TuitionPayment.query.get_or_404(payment_id)
    if tp.is_paid:
        flash('Học phí đã được thanh toán, không thể chỉnh sửa số tiền.', 'danger')
        return redirect(url_for('admin.tuition', month=tp.month, year=tp.year))

    new_amount = request.form.get('amount', type=float)
    note = request.form.get('note', '').strip()
    if new_amount is not None and new_amount >= 0:
        tp.amount = new_amount
        if note:
            tp.note = note
        db.session.commit()
        flash(f'Đã cập nhật học phí {tp.student.full_name}: {int(new_amount):,}₫.', 'success')
    return redirect(request.referrer or url_for('admin.tuition', month=tp.month, year=tp.year))
