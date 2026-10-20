"""Add an optional, one-to-one user account link to student profiles.

Usage:
    python3 migrate_add_student_login.py
    DATABASE_URL=postgresql://... python3 migrate_add_student_login.py
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
            'ALTER TABLE students ADD COLUMN IF NOT EXISTS user_id INTEGER '
            'REFERENCES users(id)'
        ))
    else:
        columns = {row[1] for row in conn.execute(text('PRAGMA table_info(students)'))}
        if 'user_id' not in columns:
            conn.execute(text(
                'ALTER TABLE students ADD COLUMN user_id INTEGER REFERENCES users(id)'
            ))
    conn.execute(text(
        'CREATE UNIQUE INDEX IF NOT EXISTS ix_students_user_id ON students(user_id)'
    ))

print('Đã đảm bảo liên kết tài khoản đăng nhập học sinh tồn tại.')
