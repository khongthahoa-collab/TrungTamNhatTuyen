"""Create the shared exam content library (safe to run repeatedly).

Usage:
    python3 migrate_add_exam_content_templates.py
    DATABASE_URL=postgresql://... python3 migrate_add_exam_content_templates.py

The application also ensures this table exists at startup, including production.
"""
import os

from sqlalchemy import create_engine

from config import BASE_DIR, _fix_db_url
from models import ExamContentTemplate


def migrate():
    database_url = os.environ.get('DATABASE_URL')
    uri = _fix_db_url(database_url) if database_url else (
        'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'nhat_tuyen_dev.db')
    )
    engine = create_engine(uri)
    try:
        ExamContentTemplate.__table__.create(bind=engine, checkfirst=True)
    finally:
        engine.dispose()
    print('Đã đảm bảo bảng mẫu nội dung đề thi dùng chung tồn tại.')


if __name__ == '__main__':
    migrate()
