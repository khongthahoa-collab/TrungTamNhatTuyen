"""
Salary Service — tạo bản ghi lương hàng tháng cho giáo viên chính (is_staff).

"Tính toán" chỉ TẠO bản ghi cho giáo viên chưa có lương tháng đó — không bao
giờ ghi đè lên bản ghi đã tồn tại, để không mất chỉnh sửa thủ công của admin
trên /admin/salary/detail (lương cơ bản, thưởng, khấu trừ, tạm ứng, ghi chú).
Lương cơ bản mặc định lấy từ tháng gần nhất đã có của chính giáo viên đó,
nếu chưa từng có thì lấy Teacher.base_salary, cuối cùng mới là 0.
"""
from sqlalchemy import extract
from extensions import db
from models import Schedule, Teacher, Salary


def _scheduled_sessions(teacher_id, month, year):
    return Schedule.query.filter(
        Schedule.teacher_id == teacher_id,
        Schedule.is_cancelled == False,
        extract('month', Schedule.date) == month,
        extract('year', Schedule.date) == year,
    ).count()


def _carry_forward_base(teacher):
    prev = (Salary.query.filter_by(teacher_id=teacher.id)
            .order_by(Salary.year.desc(), Salary.month.desc()).first())
    if prev:
        return prev.base_amount
    return teacher.base_salary or 0


def get_or_create_salary(teacher, month, year):
    """Return (salary, created) — the existing row for this teacher/month/year,
    or a freshly created one (carried-forward base amount, current scheduled-
    session count). Never overwrites an existing row."""
    existing = Salary.query.filter_by(teacher_id=teacher.id, month=month, year=year).first()
    if existing:
        return existing, False

    base = _carry_forward_base(teacher)
    salary = Salary(
        teacher_id=teacher.id,
        month=month,
        year=year,
        base_amount=base,
        bonus=0,
        deduction=0,
        advance=0,
        total=base,
        sessions_scheduled=_scheduled_sessions(teacher.id, month, year),
    )
    db.session.add(salary)
    return salary, True


def calculate_all_salaries(month, year):
    """Create a Salary row for every active is_staff teacher missing one for
    this month/year. Existing rows are left untouched. Returns the newly
    created rows."""
    teachers = (Teacher.query.filter_by(is_staff=True)
                .join(Teacher.user).filter_by(is_deleted=False).all())
    created = []
    for t in teachers:
        salary, is_new = get_or_create_salary(t, month, year)
        if is_new:
            created.append(salary)
    return created
