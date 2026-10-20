"""Add per-exam scoring mode to online exams.

Usage:
    python3 migrate_add_exam_scoring_mode.py
    DATABASE_URL=postgresql://... python3 migrate_add_exam_scoring_mode.py
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
            "ALTER TABLE exams ADD COLUMN IF NOT EXISTS scoring_mode "
            "VARCHAR(20) NOT NULL DEFAULT 'question'"
        ))
    else:
        columns = {row[1] for row in conn.execute(text('PRAGMA table_info(exams)'))}
        if 'scoring_mode' not in columns:
            conn.execute(text(
                "ALTER TABLE exams ADD COLUMN scoring_mode "
                "VARCHAR(20) NOT NULL DEFAULT 'question'"
            ))

print('Đã đảm bảo cài đặt cách tính điểm cho đề thi tồn tại.')
