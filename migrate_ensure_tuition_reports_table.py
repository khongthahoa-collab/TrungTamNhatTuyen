"""Đảm bảo bảng tuition_reports tồn tại (mô hình TuitionReport trong
models.py đã có từ trước nhưng chưa từng được dùng tới — nay dùng làm nơi
lưu trạng thái "Chốt danh sách học phí" theo từng lớp/tháng).

An toàn để chạy lại nhiều lần: db.create_all() chỉ tạo bảng nào CHƯA tồn
tại, không đụng tới bảng/dữ liệu đã có.

Usage:
    python3 migrate_ensure_tuition_reports_table.py                              # dev
    DATABASE_URL=postgresql://... python3 migrate_ensure_tuition_reports_table.py  # production
"""
from app import create_app
from extensions import db
import models  # noqa: F401

app = create_app()
with app.app_context():
    db.create_all()
    print('Đã đảm bảo bảng tuition_reports tồn tại.')
