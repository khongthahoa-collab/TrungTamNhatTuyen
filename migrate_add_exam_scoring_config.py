"""Add per-exam point and true/false scoring configuration.

Usage:
    python3 migrate_add_exam_scoring_config.py
    DATABASE_URL=postgresql://... python3 migrate_add_exam_scoring_config.py
"""
import os

from sqlalchemy import create_engine, text

from config import BASE_DIR, _fix_db_url

database_url = os.environ.get('DATABASE_URL')
if database_url:
    uri = _fix_db_url(database_url)
else:
    uri = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'nhat_tuyen_dev.db')

engine = create_engine(uri)
with engine.begin() as conn:
    if engine.dialect.name == 'postgresql':
        conn.execute(text(
            "ALTER TABLE exams ADD COLUMN IF NOT EXISTS scoring_config_json "
            "TEXT NOT NULL DEFAULT '{}'"
        ))
    else:
        columns = {row[1] for row in conn.execute(text('PRAGMA table_info(exams)'))}
        if 'scoring_config_json' not in columns:
            conn.execute(text(
                "ALTER TABLE exams ADD COLUMN scoring_config_json "
                "TEXT NOT NULL DEFAULT '{}'"
            ))

print('Đã đảm bảo cài đặt điểm theo câu/phần và trọng số đúng/sai tồn tại.')
