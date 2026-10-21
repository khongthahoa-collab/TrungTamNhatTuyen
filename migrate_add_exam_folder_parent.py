"""Add parent-child relationships to exam folders.

This migration is safe to run more than once and runs before the web workers
start so existing folders remain at the root of the folder tree.
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
            'ALTER TABLE exam_folders ADD COLUMN IF NOT EXISTS '
            'parent_id INTEGER REFERENCES exam_folders(id)'
        ))
        conn.execute(text(
            'CREATE INDEX IF NOT EXISTS ix_exam_folders_parent_id '
            'ON exam_folders (parent_id)'
        ))
    else:
        columns = {row[1] for row in conn.execute(text('PRAGMA table_info(exam_folders)'))}
        if 'parent_id' not in columns:
            conn.execute(text(
                'ALTER TABLE exam_folders ADD COLUMN parent_id INTEGER '
                'REFERENCES exam_folders(id)'
            ))
        conn.execute(text(
            'CREATE INDEX IF NOT EXISTS ix_exam_folders_parent_id '
            'ON exam_folders (parent_id)'
        ))

print('Đã đảm bảo cấu trúc thư mục đề thi phân cấp tồn tại.')
