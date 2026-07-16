"""Tuition Service — debt carryover and race-safe payment recording.

Debt carryover: when a student's tuition row for month N is unpaid, the
unpaid total_due rolls forward into debt_carried_over on their month N+1
row. This is the single place that computation happens, so every code
path that creates a TuitionPayment row (manual add, bulk add, monthly
auto-generate, class-roster add-student) applies it the same way.

Payment recording is a real money-changing operation, so it locks the row
(on Postgres — SQLite has no row-level locking, acceptable for dev-only
single-writer usage since production runs Postgres) and re-reads the
remaining balance under that lock before writing, closing the race where
two concurrent "Thu tiền" clicks on the same row could both succeed.
"""
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from extensions import db
from models import TuitionPayment


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


def record_payment(payment_id, amount, method, received_by):
    """Record a payment (full or partial) against a TuitionPayment row.
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

    tp.amount_collected = (tp.amount_collected or 0) + collect
    tp.method = method
    tp.received_by = received_by
    if round(tp.total_due - tp.amount_collected) <= 0:
        tp.is_paid = True
        tp.paid_at = datetime.utcnow()

    db.session.commit()
    return tp
