"""
Salary Service — tính lương giáo viên is_staff dựa trên check-in.
Công thức: Lương = LuongCoBan * (so_buoi_checkin / tong_buoi) + Thuong - KhauTru
"""
from sqlalchemy import extract
from extensions import db
from models import Schedule, Teacher, Salary


def calculate_salary(teacher_id, month, year):
    """
    Tính lương giáo viên cho một tháng.
    Trả về Salary object (chưa commit).
    """
    teacher = Teacher.query.get(teacher_id)
    if not teacher or not teacher.is_staff:
        return None

    scheduled = Schedule.query.filter(
        Schedule.teacher_id == teacher_id,
        Schedule.is_cancelled == False,
        extract('month', Schedule.date) == month,
        extract('year', Schedule.date) == year,
    ).count()

    checked_in = Schedule.query.filter(
        Schedule.teacher_id == teacher_id,
        Schedule.teacher_checked_in == True,
        Schedule.is_cancelled == False,
        extract('month', Schedule.date) == month,
        extract('year', Schedule.date) == year,
    ).count()

    ratio = (checked_in / scheduled) if scheduled > 0 else 0
    base = teacher.base_salary * ratio

    existing = Salary.query.filter_by(
        teacher_id=teacher_id, month=month, year=year
    ).first()

    if existing and existing.is_finalized:
        return existing  # Đã chốt lương, không tính lại

    if existing:
        existing.base_amount = base
        existing.sessions_scheduled = scheduled
        existing.sessions_checkedin = checked_in
        existing.total = base + existing.bonus - existing.deduction
        return existing

    salary = Salary(
        teacher_id=teacher_id,
        month=month,
        year=year,
        base_amount=base,
        bonus=0,
        deduction=0,
        total=base,
        sessions_scheduled=scheduled,
        sessions_checkedin=checked_in,
    )
    db.session.add(salary)
    return salary


def calculate_all_salaries(month, year):
    """Tính lương tất cả GV is_staff cho tháng/năm."""
    teachers = Teacher.query.filter_by(is_staff=True).all()
    salaries = []
    for t in teachers:
        s = calculate_salary(t.id, month, year)
        if s:
            salaries.append(s)
    db.session.commit()
    return salaries
