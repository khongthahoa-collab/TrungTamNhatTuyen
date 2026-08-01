"""Thêm index cho classes.course_id và classes.grade_level trên DB hiện có —
2 cột này nằm trong WHERE của bộ lọc/tìm kiếm trang /admin/classes nhưng
thiếu index, khiến các truy vấn đó phải quét toàn bảng. models.py đã khai
báo index=True cho 2 cột, nhưng db.create_all() không thêm index cho bảng
đã tồn tại, nên cần CREATE INDEX thủ công ở đây.

An toàn để chạy lại nhiều lần: dùng CREATE INDEX IF NOT EXISTS.

Usage:
    python3 migrate_add_class_indexes.py                              # dev
    DATABASE_URL=postgresql://... python3 migrate_add_class_indexes.py  # production
"""
from sqlalchemy import text
from app import create_app
from extensions import db
import models  # noqa: F401

app = create_app()
with app.app_context():
    with db.engine.connect() as conn:
        conn.execute(text(
            'CREATE INDEX IF NOT EXISTS ix_classes_course_id ON classes (course_id)'
        ))
        conn.execute(text(
            'CREATE INDEX IF NOT EXISTS ix_classes_grade_level ON classes (grade_level)'
        ))
        conn.commit()
    print('Đã đảm bảo index tồn tại trên classes.course_id và classes.grade_level.')
