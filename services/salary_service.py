"""
Salary Service — tạo bản ghi lương hàng tháng cho mọi giáo viên đang hoạt
động (cả Giáo viên chính và Trợ giảng).

"Tính toán" chỉ TẠO bản ghi cho giáo viên chưa có lương tháng đó — không bao
giờ ghi đè lên bản ghi đã tồn tại, để không mất chỉnh sửa thủ công của admin
trên /admin/salary/detail (lương cơ bản, thưởng, khấu trừ, tạm ứng, ghi chú).
Mỗi tháng độc lập: lương cơ bản mặc định luôn lấy từ Teacher.base_salary
(không lấy từ tháng trước) — chỉnh sửa lương cơ bản của một tháng không ảnh
hưởng đến các tháng khác.
"""
from sqlalchemy import extract
from extensions import db
from models import Schedule, Teacher, Salary


def scheduled_sessions(teacher_id, month, year):
    """Sessions this teacher is regularly assigned to and actually taught
    (excludes sessions they were substituted out of)."""
    return Schedule.query.filter(
        Schedule.teacher_id == teacher_id,
        Schedule.substitute_teacher_id.is_(None),
        Schedule.is_cancelled == False,
        extract('month', Schedule.date) == month,
        extract('year', Schedule.date) == year,
    ).count()


def substituted_sessions(teacher_id, month, year):
    """Sessions this teacher taught as a substitute for another teacher."""
    return Schedule.query.filter(
        Schedule.substitute_teacher_id == teacher_id,
        Schedule.is_cancelled == False,
        extract('month', Schedule.date) == month,
        extract('year', Schedule.date) == year,
    ).count()


def get_or_create_salary(teacher, month, year):
    """Return (salary, created) — the existing row for this teacher/month/year,
    or a freshly created one (base amount from Teacher.base_salary, current
    scheduled-session count). Never overwrites an existing row, and never
    derives its base amount from another month's record."""
    existing = Salary.query.filter_by(teacher_id=teacher.id, month=month, year=year).first()
    if existing:
        return existing, False

    base = teacher.base_salary or 0
    salary = Salary(
        teacher_id=teacher.id,
        month=month,
        year=year,
        base_amount=base,
        bonus=0,
        deduction=0,
        advance=0,
        total=base,
        sessions_scheduled=scheduled_sessions(teacher.id, month, year),
        sessions_substituted=substituted_sessions(teacher.id, month, year),
    )
    db.session.add(salary)
    return salary, True


def calculate_all_salaries(month, year):
    """Create a Salary row for every active teacher (Giáo viên chính and
    Trợ giảng alike) missing one for this month/year. Existing rows are
    left untouched. Returns the newly created rows."""
    teachers = Teacher.query.join(Teacher.user).filter_by(is_deleted=False).all()
    created = []
    for t in teachers:
        salary, is_new = get_or_create_salary(t, month, year)
        if is_new:
            created.append(salary)
    return created
