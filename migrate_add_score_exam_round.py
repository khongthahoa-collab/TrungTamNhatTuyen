"""Thêm cột exam_round vào bảng scores hiện có — số thứ tự lần thi của cùng
một loại điểm (Thường xuyên lần 1, lần 2...), đánh số theo lớp + loại điểm +
năm. db.create_all() không thêm cột cho bảng đã tồn tại nên cần ALTER TABLE
thủ công ở đây.

Kết nối thẳng tới DB thay vì dùng create_app(): app.py có bước auto-seed tài
khoản admin ở dev mode, tự query DB ngay khi khởi tạo app — né hẳn cho chắc,
giống migrate_add_token_expires_at.py.

Cột để nullable: điểm nhập trước khi có tính năng này không có số lần, và
không được đoán bừa số lần cho chúng.

An toàn để chạy lại nhiều lần: kiểm tra cột đã tồn tại chưa trước khi thêm.

Usage:
    python3 migrate_add_score_exam_round.py                              # dev
    DATABASE_URL=postgresql://... python3 migrate_add_score_exam_round.py  # production
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
            'ALTER TABLE scores ADD COLUMN IF NOT EXISTS exam_round INTEGER'
        ))
    else:
        existing_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(scores)"))]
        if 'exam_round' not in existing_cols:
            conn.execute(text('ALTER TABLE scores ADD COLUMN exam_round INTEGER'))
    conn.commit()
print('Đã đảm bảo cột exam_round tồn tại trên bảng scores.')
