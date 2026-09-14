"""Tổng hợp tình hình làm bài tập về nhà.

Mọi màn hình (giáo viên, admin, phụ huynh và cổng học sinh sau này) phải
lấy số liệu từ đây, không tự đếm lại — nếu mỗi nơi tự tính thì chỉ cần một
chỗ quên loại "chưa ghi nhận" ra khỏi mẫu số là phụ huynh và giáo viên nhìn
thấy hai tỉ lệ khác nhau cho cùng một học sinh.

Bài tập về nhà KHÔNG chấm điểm: chỉ có làm / không làm, phần chi tiết nằm
ở ghi chú của từng bản ghi.
"""
from sqlalchemy import extract
from sqlalchemy.orm import joinedload

from extensions import db
from models import Homework, HomeworkRecord, HomeworkStatus


def _apply_scope(query, class_ids=None, year=None, semester=None):
    """Giới hạn theo lớp / năm / kỳ. Bộ lọc nào để None thì không giới hạn."""
    if class_ids is not None:
        # Danh sách lớp rỗng nghĩa là "không lớp nào", không phải "mọi lớp".
        query = query.filter(Homework.class_id.in_(class_ids or [-1]))
    if year is not None:
        query = query.filter(extract('year', Homework.assigned_date) == year)
    if semester is not None:
        query = query.filter(Homework.semester == semester)
    return query


def summarize(done, not_done):
    """Gói số liệu về một dạng duy nhất cho mọi template.

    rate = None khi chưa ghi nhận lần nào — "chưa ghi nhận" khác hẳn "không
    làm bài lần nào", hiển thị 0% cho em chưa từng được ghi nhận là sai.
    """
    total = done + not_done
    return {
        'done': done,
        'not_done': not_done,
        'total': total,
        'rate': round(done / total * 100) if total else None,
    }


def student_summary(student_id, class_ids=None, year=None, semester=None):
    """Tổng hợp của MỘT học sinh: làm bài mấy lần trên tổng số lần đã ghi nhận."""
    q = _apply_scope(
        db.session.query(HomeworkRecord.status, db.func.count(HomeworkRecord.id))
        .join(Homework, HomeworkRecord.homework_id == Homework.id)
        .filter(HomeworkRecord.student_id == student_id),
        class_ids, year, semester,
    ).group_by(HomeworkRecord.status)
    by_status = dict(q.all())
    return summarize(by_status.get(HomeworkStatus.DONE, 0),
                     by_status.get(HomeworkStatus.NOT_DONE, 0))


def students_summary(student_ids, class_ids=None, year=None, semester=None):
    """Tổng hợp của NHIỀU học sinh trong một truy vấn — dùng cho bảng danh
    sách cả lớp, thay vì gọi student_summary() cho từng em (N+1)."""
    if not student_ids:
        return {}
    q = _apply_scope(
        db.session.query(HomeworkRecord.student_id, HomeworkRecord.status,
                         db.func.count(HomeworkRecord.id))
        .join(Homework, HomeworkRecord.homework_id == Homework.id)
        .filter(HomeworkRecord.student_id.in_(student_ids)),
        class_ids, year, semester,
    ).group_by(HomeworkRecord.student_id, HomeworkRecord.status)

    by_student = {}
    for st_id, status, n in q.all():
        by_student.setdefault(st_id, {})[status] = n
    return {
        st_id: summarize(by_student.get(st_id, {}).get(HomeworkStatus.DONE, 0),
                         by_student.get(st_id, {}).get(HomeworkStatus.NOT_DONE, 0))
        for st_id in student_ids
    }


def recent_records(student_id, limit=20, class_ids=None, year=None, semester=None):
    """Các lần giao bài gần nhất của một học sinh, mới nhất trước.

    joinedload sẵn Homework và Class: template nào cũng hiện ngày + tên lớp,
    để lazy sẽ thành một truy vấn cho mỗi dòng.
    """
    q = _apply_scope(
        HomeworkRecord.query
        .join(Homework, HomeworkRecord.homework_id == Homework.id)
        .options(joinedload(HomeworkRecord.homework).joinedload(Homework.class_))
        .filter(HomeworkRecord.student_id == student_id),
        class_ids, year, semester,
    )
    return (q.order_by(Homework.assigned_date.desc(),
                       Homework.assignment_round.desc(),
                       HomeworkRecord.id.desc())
             .limit(limit).all())


def recent_missed_streak(student_id, lookback=5, class_ids=None):
    """Số lần KHÔNG làm bài liên tiếp gần đây nhất.

    Đây là tín hiệu đáng báo động thật sự — "3 lần liên tiếp không làm bài"
    hữu ích hơn nhiều so với một tỉ lệ phần trăm cộng dồn cả kỳ.
    """
    recs = recent_records(student_id, limit=lookback, class_ids=class_ids)
    streak = 0
    for r in recs:
        if r.status == HomeworkStatus.NOT_DONE:
            streak += 1
        else:
            break
    return streak
