"""Tạo bảng bank_accounts (mô hình BankAccount trong models.py) — hỗ trợ
nhiều tài khoản ngân hàng để tạo mã VietQR trên thông báo học phí.

An toàn để chạy lại nhiều lần: db.create_all() chỉ tạo bảng nào CHƯA tồn
tại, không đụng tới bảng/dữ liệu đã có.

Usage:
    python3 migrate_add_bank_accounts_table.py                              # dev
    DATABASE_URL=postgresql://... python3 migrate_add_bank_accounts_table.py  # production
"""
from app import create_app
from extensions import db
import models  # noqa: F401  — đăng ký hết model trước khi create_all()

app = create_app()
with app.app_context():
    db.create_all()
    print('Đã đảm bảo bảng bank_accounts tồn tại.')
