"""Tuition Service — debt carryover, the payment ledger / fee-edit audit
log, and the academic-year write boundary.

Debt carryover: when a student's tuition row for month N is unpaid, the
unpaid total_due rolls forward into debt_carried_over on their month N+1
row. This is the single place that computation happens, so every code
path that creates a TuitionPayment row (manual add, bulk add, monthly
auto-generate, class-roster add-student) applies it the same way. It also
follows a student across a year-rollover class swap (see
get_previous_month_debt's rolled_over_from_id fallback) — rollover
creates a new Class row for the new year, so without this a student's
last unpaid balance on the old class would otherwise be silently orphaned.

Payment recording writes an immutable TuitionTransaction row (the real
accounting ledger — a correction never overwrites history, it's always a
new row) and recomputes TuitionPayment.amount_collected as a cache from
SUM(transactions) in the same DB transaction. It's a real money-changing
operation, so it locks the row (on Postgres — SQLite has no row-level
locking, acceptable for dev-only single-writer usage since production
runs Postgres) and re-reads the remaining balance under that lock before
writing, closing the race where two concurrent "Thu tiền" clicks on the
same row could both succeed. record_fee_adjustment() locks the same way —
without it, two concurrent fee edits can both read the same stale
old_amount and write an internally-inconsistent TuitionFeeAuditLog trail.

Every write path (create/pay/adjust) refuses to touch a (month, year)
that isn't the active academic year — see assert_period_writable().
Reads are never restricted; historical years stay fully viewable.
"""
from datetime import datetime, date
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from extensions import db
from models import TuitionPayment, TuitionTransaction, TuitionFeeAuditLog, Class
from services.academic_year_service import assert_period_writable, is_period_writable


def get_previous_month_debt(student_id, class_id, month, year):
    """Unpaid total_due from the immediately preceding month's row for
    this student+class. 0 if that row doesn't exist or was fully paid.

    If this class was created by rolling over a previous year's class
    (Class.rolled_over_from_id) and this is that class's own first
    billed month, falls back to the *source* class's last unpaid balance
    for this student — otherwise a student's final unpaid month on the
    old class would vanish at the year boundary instead of carrying
    forward, since rollover creates a brand new class_id."""
    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    prev = TuitionPayment.query.filter_by(
        student_id=student_id, class_id=class_id, month=prev_month, year=prev_year
    ).first()
    if prev:
        return max(0, prev.total_due - (prev.amount_collected or 0))

    cls = Class.query.get(class_id)
    if cls and cls.rolled_over_from_id:
        source_prev = TuitionPayment.query.filter_by(
            student_id=student_id, class_id=cls.rolled_over_from_id
        ).order_by(TuitionPayment.year.desc(), TuitionPayment.month.desc()).first()
        if source_prev:
            return max(0, source_prev.total_due - (source_prev.amount_collected or 0))

    return 0


def batch_previous_month_debts(student_ids, class_id, month, year):
    """Same lookup as get_previous_month_debt(), batched for a whole
    class's roster in 1-2 queries instead of one SELECT per student —
    monthly_fee_generate() was issuing a separate get_previous_month_debt
    call per enrolled student, which at real scale (hundreds of students)
    is exactly the N+1 pattern that already caused a 502 once this
    session in a different route. Returns {student_id: debt}."""
    if not student_ids:
        return {}
    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    debts = {sid: 0 for sid in student_ids}

    rows = TuitionPayment.query.filter(
        TuitionPayment.student_id.in_(student_ids),
        TuitionPayment.class_id == class_id,
        TuitionPayment.month == prev_month, TuitionPayment.year == prev_year,
    ).all()
    found = {r.student_id for r in rows}
    for r in rows:
        debts[r.student_id] = max(0, r.total_due - (r.amount_collected or 0))

    missing = [sid for sid in student_ids if sid not in found]
    cls = Class.query.get(class_id)
    if missing and cls and cls.rolled_over_from_id:
        source_rows = (
            TuitionPayment.query
            .filter(TuitionPayment.student_id.in_(missing), TuitionPayment.class_id == cls.rolled_over_from_id)
            .order_by(TuitionPayment.year.desc(), TuitionPayment.month.desc())
            .all()
        )
        latest_by_student = {}
        for r in source_rows:
            latest_by_student.setdefault(r.student_id, r)
        for sid, r in latest_by_student.items():
            debts[sid] = max(0, r.total_due - (r.amount_collected or 0))

    return debts


def create_tuition_payment(student_id, class_id, month, year, amount, debt_override=None,
                           skip_period_check=False, **extra):
    """Create a TuitionPayment row with debt_carried_over computed from
    the previous month (or debt_override, if the caller already batched
    it — see batch_previous_month_debts). Race-safe: the DB-level unique
    index on (student_id, class_id, month, year) is the actual guarantee;
    a SAVEPOINT per attempt means a duplicate-key hit from a concurrent
    request only unwinds this one insert, not a whole batch.

    skip_period_check=True lets a caller that's already validated
    is_period_writable(month, year) once for a whole batch (see
    monthly_fee_generate()) skip re-running that same query on every
    single student — otherwise this function's own boundary check would
    silently cancel out the N+1 fix batch_previous_month_debts() exists
    to provide. Every other caller should leave this False; the check
    stays mandatory by default.

    Raises FrozenPeriodError if (month, year) isn't the active academic
    year (unless skipped), ValueError if amount is negative.

    Returns (payment, created) — created=False means a row already
    existed (race lost, or a genuine pre-existing duplicate) and the
    existing row is returned instead.
    """
    if amount < 0:
        raise ValueError("Số tiền học phí không được nhỏ hơn 0.")
    if not skip_period_check:
        assert_period_writable(month, year)

    debt = debt_override if debt_override is not None else get_previous_month_debt(student_id, class_id, month, year)
    tp = TuitionPayment(
        student_id=student_id, class_id=class_id, month=month, year=year,
        amount=amount, debt_carried_over=debt, **extra,
    )
    try:
        with db.session.begin_nested():
            db.session.add(tp)
            db.session.flush()
        return tp, True
    except IntegrityError:
        db.session.rollback()
        existing = TuitionPayment.query.filter_by(
            student_id=student_id, class_id=class_id, month=month, year=year
        ).first()
        return existing, False


def record_payment(payment_id, amount, method, received_by, note=None):
    """Record a payment (full or partial) against a TuitionPayment row by
    inserting an immutable TuitionTransaction and recomputing the cached
    amount_collected from the ledger — never written directly otherwise.
    amount=None (or 0) collects the full remaining balance — preserves
    the existing one-click "Thu tiền" behavior. Amounts are rounded to
    whole VND before comparing, since these are integer-currency amounts
    and float accumulation can otherwise leave a few-đồng residue that
    never quite reaches "fully paid".

    Raises FrozenPeriodError if the row's (month, year) isn't the active
    academic year."""
    query = TuitionPayment.query.filter_by(id=payment_id)
    if db.engine.dialect.name == 'postgresql':
        query = query.with_for_update()
    tp = query.first()
    if not tp:
        return None

    assert_period_writable(tp.month, tp.year)

    remaining = round(tp.total_due - (tp.amount_collected or 0))
    collect = round(amount) if amount else remaining
    collect = max(0, min(collect, remaining))
    if collect <= 0:
        return tp

    db.session.add(TuitionTransaction(
        tuition_payment_id=tp.id, amount=collect, method=method,
        received_by=received_by, note=note,
    ))
    db.session.flush()

    tp.amount_collected = db.session.query(
        func.coalesce(func.sum(TuitionTransaction.amount), 0)
    ).filter_by(tuition_payment_id=tp.id).scalar()
    tp.method = method
    tp.received_by = received_by
    if note:
        # Mirrors the latest transaction's note onto the bill for the
        # existing "Ghi chú" display spot — full payment-by-payment history
        # always remains in the ledger regardless of what this shows.
        tp.note = note
    if round(tp.total_due - tp.amount_collected) <= 0:
        tp.is_paid = True
        tp.paid_at = datetime.utcnow()

    db.session.commit()
    return tp


def reverse_payment(payment_id, reason, reversed_by):
    """Undo a payment that was collected in error (wrong amount, wrong
    student, double-entry) — distinct from void_tuition_payment(), which
    cancels a bill *before* any money changes hands. This is the opposite
    case: money WAS recorded, and that recording needs to be undone.

    Never overwrites amount_collected directly — inserts a compensating
    negative TuitionTransaction (amount = -amount_collected) so the
    ledger stays append-only and the reversal itself is auditable (who,
    when, why) via that same transaction row, then recomputes
    amount_collected from SUM(transactions) exactly like record_payment()
    does. Resets is_paid/paid_at so the bill returns to its unpaid/partial
    state ready to be re-collected correctly.

    Raises ValueError if the reason is blank, the bill has nothing
    collected against it, or the bill is voided (unvoid first). Raises
    FrozenPeriodError if the row's (month, year) isn't the active academic
    year. Returns None if no such row exists."""
    reason = (reason or '').strip()
    if not reason:
        raise ValueError("Vui lòng nhập lý do hoàn tác thanh toán.")

    query = TuitionPayment.query.filter_by(id=payment_id)
    if db.engine.dialect.name == 'postgresql':
        query = query.with_for_update()
    tp = query.first()
    if not tp:
        return None

    assert_period_writable(tp.month, tp.year)

    if tp.is_voided:
        raise ValueError("Học phí này đã bị hủy — hãy khôi phục trước khi hoàn tác thanh toán.")
    collected = round(tp.amount_collected or 0)
    if collected <= 0:
        raise ValueError("Học phí này chưa có khoản thu nào để hoàn tác.")

    db.session.add(TuitionTransaction(
        tuition_payment_id=tp.id, amount=-collected, method=tp.method,
        received_by=reversed_by, note=f'Hoàn tác thanh toán: {reason}',
    ))
    db.session.flush()

    tp.amount_collected = db.session.query(
        func.coalesce(func.sum(TuitionTransaction.amount), 0)
    ).filter_by(tuition_payment_id=tp.id).scalar()
    tp.is_paid = False
    tp.paid_at = None
    tp.note = reason

    db.session.commit()
    return tp


def record_fee_adjustment(payment_id, new_amount, changed_by, note=None):
    """Change a TuitionPayment's current-month fee (the admin "Sửa" action),
    writing a TuitionFeeAuditLog row in the same locked transaction so the
    change is always attributable and the audit trail can't be corrupted
    by a concurrent edit reading the same stale old_amount. Returns the
    updated payment, or None if no such row exists.

    Raises FrozenPeriodError if the row's (month, year) isn't the active
    academic year, ValueError if new_amount is negative."""
    if new_amount < 0:
        raise ValueError("Số tiền học phí không được nhỏ hơn 0.")

    query = TuitionPayment.query.filter_by(id=payment_id)
    if db.engine.dialect.name == 'postgresql':
        query = query.with_for_update()
    tp = query.first()
    if not tp:
        return None

    assert_period_writable(tp.month, tp.year)

    old_amount = tp.amount
    if round(old_amount) == round(new_amount):
        return tp  # no-op, don't log a null change

    db.session.add(TuitionFeeAuditLog(
        tuition_payment_id=tp.id, old_amount=old_amount, new_amount=new_amount,
        changed_by=changed_by, note=note,
    ))
    tp.amount = new_amount
    tp.has_custom_fee = True
    if note:
        tp.note = note
    db.session.commit()
    return tp


def void_tuition_payment(payment_id, reason, voided_by):
    """Soft-delete a mistakenly-created bill (the "Hủy" admin action) —
    excluded from revenue/KPI aggregates going forward, but the row (and
    any TuitionTransaction ledger entries already recorded against it)
    stays for audit purposes; use unvoid_tuition_payment() to reverse.

    Mirrors tuition_adjust_amount()'s existing precedent of refusing to
    touch a fully-paid bill — voiding retracts a bill before money
    changes hands, not after. Raises ValueError if the reason is blank,
    the bill is already voided, or is_paid. Raises FrozenPeriodError if
    the row's (month, year) isn't the active academic year. Returns None
    if no such row exists."""
    reason = (reason or '').strip()
    if not reason:
        raise ValueError("Vui lòng nhập lý do hủy.")

    query = TuitionPayment.query.filter_by(id=payment_id)
    if db.engine.dialect.name == 'postgresql':
        query = query.with_for_update()
    tp = query.first()
    if not tp:
        return None

    assert_period_writable(tp.month, tp.year)

    if tp.is_voided:
        raise ValueError("Học phí này đã bị hủy trước đó.")
    if tp.is_paid:
        raise ValueError("Học phí đã được thanh toán đủ, không thể hủy.")

    tp.is_voided = True
    tp.void_reason = reason
    tp.voided_by = voided_by
    tp.voided_at = datetime.utcnow()
    db.session.commit()
    return tp


def unvoid_tuition_payment(payment_id):
    """Reverse void_tuition_payment(). Raises ValueError if the row isn't
    currently voided. Raises FrozenPeriodError if the row's (month, year)
    isn't the active academic year. Returns None if no such row exists."""
    query = TuitionPayment.query.filter_by(id=payment_id)
    if db.engine.dialect.name == 'postgresql':
        query = query.with_for_update()
    tp = query.first()
    if not tp:
        return None

    assert_period_writable(tp.month, tp.year)

    if not tp.is_voided:
        raise ValueError("Học phí này chưa bị hủy.")

    tp.is_voided = False
    tp.void_reason = None
    tp.voided_by = None
    tp.voided_at = None
    db.session.commit()
    return tp


def cascade_class_fee_update(class_id, old_fee, new_fee, changed_by):
    """When a Class's monthly_fee changes, push the new rate onto this
    month's still-open bills for that class. Skips PAID bills, PARTIAL
    bills (amount_collected > 0), voided bills, and bills with
    has_custom_fee=True (a student-specific override from the "Sửa"
    action) — only a strictly-unpaid, never-manually-edited bill picks up
    the new class rate. If every bill this month is already settled, this
    is a no-op and the new rate simply applies starting next month's
    generation.

    Does not commit — the caller (class_edit() / classes_update()) commits
    once, so the Class.monthly_fee change and this cascade land in the
    same transaction. Returns the count of bills updated."""
    if old_fee == new_fee:
        return 0
    today = date.today()
    if not is_period_writable(today.month, today.year):
        return 0

    candidates = TuitionPayment.query.filter_by(
        class_id=class_id, month=today.month, year=today.year,
        is_paid=False, is_voided=False, has_custom_fee=False,
    ).filter(TuitionPayment.amount_collected == 0).all()

    for tp in candidates:
        db.session.add(TuitionFeeAuditLog(
            tuition_payment_id=tp.id, old_amount=tp.amount, new_amount=new_fee,
            changed_by=changed_by, note='Cập nhật theo học phí lớp mới',
        ))
        tp.amount = new_fee

    return len(candidates)
