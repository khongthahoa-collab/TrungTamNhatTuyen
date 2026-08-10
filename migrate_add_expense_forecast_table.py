"""Tạo bảng expense_forecasts (mô hình ExpenseForecast trong models.py) —
lưu khoản "Chi phí khác dự kiến" admin tự nhập cho từng tháng, dùng trong
trang Thống kê (/admin/reports) để tính "Dự chi".

An toàn để chạy lại nhiều lần: db.create_all() chỉ tạo bảng nào CHƯA tồn
tại, không đụng tới bảng/dữ liệu đã có.

Usage:
    python3 migrate_add_expense_forecast_table.py                              # dev
    DATABASE_URL=postgresql://... python3 migrate_add_expense_forecast_table.py  # production
"""
from app import create_app
from extensions import db
import models  # noqa: F401  — đăng ký hết model trước khi create_all()

app = create_app()
with app.app_context():
    db.create_all()
    print('Đã đảm bảo bảng expense_forecasts tồn tại.')
