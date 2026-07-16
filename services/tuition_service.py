"""Tuition Service — debt carryover, and the payment ledger / fee-edit
audit log.

Debt carryover: when a student's tuition row for month N is unpaid, the
unpaid total_due rolls forward into debt_carried_over on their month N+1
row. This is the single place that computation happens, so every code
path that creates a TuitionPayment row (manual add, bulk add, monthly
auto-generate, class-roster add-student) applies it the same way.

Payment recording writes an immutable TuitionTransaction row (the real
accounting ledger — a correction never overwrites history, it's always a
new row) and recomputes TuitionPayment.amount_collected as a cache from
SUM(transactions) in the same DB transaction. It's a real money-changing
operation, so it locks the row (on Postgres — SQLite has no row-level
locking, acceptable for dev-only single-writer usage since production
runs Postgres) and re-reads the remaining balance under that lock before
writing, closing the race where two concurrent "Thu tiền" clicks on the
same row could both succeed.

Fee edits (record_fee_adjustment) write a TuitionFeeAuditLog row in the
same transaction as the amount change, so "who changed this student's fee
and from what to what" is always answerable.
"""
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from extensions import db
from models import TuitionPayment, TuitionTransaction, TuitionFeeAuditLog


def get_previous_month_debt(student_id, class_id, month, year):
    """Unpaid total_due from the immediately preceding month's row for
    this student+class. 0 if that row doesn't exist or was fully paid."""
    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    prev = TuitionPayment.query.filter_by(
        student_id=student_id, class_id=class_id, month=prev_month, year=prev_year
    ).first()
    if not prev:
        return 0
    return max(0, prev.total_due - (prev.amount_collected or 0))


def create_tuition_payment(student_id, class_id, month, year, amount, **extra):
    """Create a TuitionPayment row with debt_carried_over computed from
    the previous month. Race-safe: the DB-level unique index on
    (student_id, class_id, month, year) is the actual guarantee; a
    SAVEPOINT per attempt means a duplicate-key hit from a concurrent
    request only unwinds this one insert, not a whole batch.

    Returns (payment, created) — created=False means a row already
    existed (race lost, or a genuine pre-existing duplicate) and the
    existing row is returned instead.
    """
    debt = get_previous_month_debt(student_id, class_id, month, year)
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
    never quite reaches "fully paid"."""
    query = TuitionPayment.query.filter_by(id=payment_id)
    if db.engine.dialect.name == 'postgresql':
        query = query.with_for_update()
    tp = query.first()
    if not tp:
        return None

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


def record_fee_adjustment(payment_id, new_amount, changed_by, note=None):
    """Change a TuitionPayment's current-month fee (the admin "Sửa" action),
    writing a TuitionFeeAuditLog row in the same transaction so the change
    is always attributable. Returns the updated payment, or None if no
    such row exists."""
    tp = TuitionPayment.query.get(payment_id)
    if not tp:
        return None

    old_amount = tp.amount
    if round(old_amount) == round(new_amount):
        return tp  # no-op, don't log a null change

    db.session.add(TuitionFeeAuditLog(
        tuition_payment_id=tp.id, old_amount=old_amount, new_amount=new_amount,
        changed_by=changed_by, note=note,
    ))
    tp.amount = new_amount
    if note:
        tp.note = note
    db.session.commit()
    return tp
