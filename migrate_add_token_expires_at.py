"""Thêm cột token_expires_at vào bảng users hiện có — cho phép API token
(Bearer, dùng bởi /api/v1) có hạn dùng thay vì sống vĩnh viễn cho đến khi
logout. db.create_all() không thêm cột cho bảng đã tồn tại, nên cần
ALTER TABLE thủ công ở đây.

Không dùng create_app() như các script migrate_add_* khác: app.py có bước
auto-seed tài khoản admin ở dev mode, tự query bảng users ngay khi khởi tạo
app — bảng đó chưa có cột mới này nên sẽ crash trước khi kịp ALTER. Script
này tự kết nối thẳng tới DB, né hoàn toàn việc khởi tạo Flask app.

An toàn để chạy lại nhiều lần: kiểm tra cột đã tồn tại chưa trước khi thêm.

Usage:
    python3 migrate_add_token_expires_at.py                              # dev
    DATABASE_URL=postgresql://... python3 migrate_add_token_expires_at.py  # production
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
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMP'
        ))
    else:
        existing_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(users)"))]
        if 'token_expires_at' not in existing_cols:
            conn.execute(text(
                'ALTER TABLE users ADD COLUMN token_expires_at DATETIME'
            ))
    conn.commit()
print('Đã đảm bảo cột token_expires_at tồn tại trên bảng users.')
