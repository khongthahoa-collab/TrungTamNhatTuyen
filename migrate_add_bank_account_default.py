"""Thêm cột is_default vào bảng bank_accounts hiện có — đánh dấu tài khoản
dùng làm lựa chọn ban đầu (QR/nội dung nhắc Zalo) khi chưa chủ động chọn
tài khoản khác. db.create_all() không thêm cột cho bảng đã tồn tại, nên
cần ALTER TABLE thủ công ở đây.

An toàn để chạy lại nhiều lần: kiểm tra cột đã tồn tại chưa trước khi thêm.

Usage:
    python3 migrate_add_bank_account_default.py                              # dev
    DATABASE_URL=postgresql://... python3 migrate_add_bank_account_default.py  # production
"""
from sqlalchemy import text
from app import create_app
from extensions import db
import models  # noqa: F401

app = create_app()
with app.app_context():
    dialect = db.engine.dialect.name
    with db.engine.connect() as conn:
        if dialect == 'postgresql':
            conn.execute(text(
                'ALTER TABLE bank_accounts ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT FALSE'
            ))
        else:
            existing_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(bank_accounts)"))]
            if 'is_default' not in existing_cols:
                conn.execute(text(
                    'ALTER TABLE bank_accounts ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT 0'
                ))
        conn.commit()
    print('Đã đảm bảo cột is_default tồn tại trên bảng bank_accounts.')
