"""Add school and individual-student targeting to exams.

Usage:
    python3 migrate_add_exam_school_student_targets.py
    DATABASE_URL=postgresql://... python3 migrate_add_exam_school_student_targets.py
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
            "ALTER TABLE exams ADD COLUMN IF NOT EXISTS school_ids "
            "TEXT NOT NULL DEFAULT ''"
        ))
        conn.execute(text(
            "ALTER TABLE exams ADD COLUMN IF NOT EXISTS student_ids "
            "TEXT NOT NULL DEFAULT ''"
        ))
    else:
        columns = {row[1] for row in conn.execute(text('PRAGMA table_info(exams)'))}
        if 'school_ids' not in columns:
            conn.execute(text(
                "ALTER TABLE exams ADD COLUMN school_ids TEXT NOT NULL DEFAULT ''"
            ))
        if 'student_ids' not in columns:
            conn.execute(text(
                "ALTER TABLE exams ADD COLUMN student_ids TEXT NOT NULL DEFAULT ''"
            ))

print('Đã đảm bảo phạm vi giao đề theo trường và học sinh tồn tại.')
