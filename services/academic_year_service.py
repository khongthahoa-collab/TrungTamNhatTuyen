"""Academic-year write boundary — shared by every financial write path
(tuition create/pay/adjust in services/tuition_service.py, and the
"Cuộn năm học" rollover in blueprints/admin/academic.py) so a (month,
year) outside the currently active academic year can never be written
to, while reads (dashboards, class-detail history) stay fully open for
any archived year — financial history must remain visible, just frozen.
"""
from datetime import date
from models import AcademicYear


class FrozenPeriodError(Exception):
    """(month, year) belongs to an archived/inactive academic year, or no
    academic year covers it at all — writes are refused either way."""


def get_active_academic_year():
    return AcademicYear.query.filter_by(is_active=True).first()


def is_period_writable(month, year):
    """True only if (month, year) falls within the currently active
    AcademicYear's date range. No active year at all -> not writable
    (a school with no configured current year has nothing to write to)."""
    ay = get_active_academic_year()
    if not ay:
        return False
    target = date(year, month, 1)
    return ay.start_date <= target <= ay.end_date


def assert_period_writable(month, year):
    if not is_period_writable(month, year):
        raise FrozenPeriodError('Không thể sửa đổi dữ liệu tài chính của năm học đã đóng băng')


def list_academic_year_months():
    """Every (year, month) pair covered by some registered AcademicYear
    (active or archived), newest first — bounds the tuition overview's
    month/year picker to periods that actually mean something instead of
    an unconditional +/- 3 year range, and lets it include read-only
    access to any archived year."""
    months = set()
    for ay in AcademicYear.query.all():
        y, m = ay.start_date.year, ay.start_date.month
        while (y, m) <= (ay.end_date.year, ay.end_date.month):
            months.add((y, m))
            m += 1
            if m > 12:
                m = 1
                y += 1
    return sorted(months, reverse=True)
