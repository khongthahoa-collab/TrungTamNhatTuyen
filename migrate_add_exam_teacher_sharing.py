"""Add admin-controlled sharing status to online exams.

Usage:
    python3 migrate_add_exam_teacher_sharing.py
    DATABASE_URL=postgresql://... python3 migrate_add_exam_teacher_sharing.py
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
            'ALTER TABLE exams ADD COLUMN IF NOT EXISTS is_shared_with_teachers '
            'BOOLEAN NOT NULL DEFAULT FALSE'
        ))
    else:
        columns = {row[1] for row in conn.execute(text('PRAGMA table_info(exams)'))}
        if 'is_shared_with_teachers' not in columns:
            conn.execute(text(
                'ALTER TABLE exams ADD COLUMN is_shared_with_teachers '
                'BOOLEAN NOT NULL DEFAULT 0'
            ))

print('Đã đảm bảo trạng thái chia sẻ đề với giáo viên tồn tại.')
