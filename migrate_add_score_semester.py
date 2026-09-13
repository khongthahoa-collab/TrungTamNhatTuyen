"""Thêm cột semester vào bảng scores hiện có — kỳ học do giáo viên tự chọn
khi nhập điểm (semester_1/semester_2/summer theo SemesterType).

Không suy ra kỳ từ exam_date + bảng semesters: ranh giới kỳ ở đó đang được
chia cơ học thành 3 phần bằng nhau của năm học (xem admin/academic.py), nên
"Kỳ 1" ở đó không khớp kỳ 1 thực tế của trường. Để giáo viên khai báo thẳng
là chính xác nhất.

Cột để nullable: điểm nhập trước khi có tính năng này không có kỳ, và không
được đoán bừa kỳ cho chúng.

An toàn để chạy lại nhiều lần: kiểm tra cột đã tồn tại chưa trước khi thêm.

Usage:
    python3 migrate_add_score_semester.py                              # dev
    DATABASE_URL=postgresql://... python3 migrate_add_score_semester.py  # production
"""
import os
from sqlalchemy import create_engine, text
from config import BASE_DIR, _fix_db_url

database_url = os.environ.get('DATABASE_URL')
if database_url:
    uri = _fix_db_url(database_url)
else:
    # Khớp cách Flask-SQLAlchemy resolve URI sqlite tương đối: nằm trong
    # instance/, không phải thư mục gốc dự án.
    uri = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'nhat_tuyen_dev.db')

engine = create_engine(uri)
dialect = engine.dialect.name
with engine.connect() as conn:
    if dialect == 'postgresql':
        conn.execute(text(
            'ALTER TABLE scores ADD COLUMN IF NOT EXISTS semester VARCHAR(20)'
        ))
    else:
        existing_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(scores)"))]
        if 'semester' not in existing_cols:
            conn.execute(text('ALTER TABLE scores ADD COLUMN semester VARCHAR(20)'))
    conn.commit()
print('Đã đảm bảo cột semester tồn tại trên bảng scores.')
