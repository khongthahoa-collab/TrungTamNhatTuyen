"""Add salaries.advance (Tạm ứng) column.

Usage:
    python3 migrate_salary_advance.py          # local dev (instance/nhat_tuyen_dev.db)
    DATABASE_URL=postgresql://... python3 migrate_salary_advance.py   # production
"""
import os

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, Float, create_engine

from config import _fix_db_url, BASE_DIR

uri = os.environ.get('DATABASE_URL', 'sqlite:///nhat_tuyen_dev.db')
uri = _fix_db_url(uri)
if uri.startswith('sqlite:///') and not uri.startswith('sqlite:////'):
    rel_path = uri[len('sqlite:///'):]
    uri = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', rel_path)

engine = create_engine(uri)
with engine.connect() as conn:
    ctx = MigrationContext.configure(conn)
    op = Operations(ctx)
    with op.batch_alter_table('salaries') as batch_op:
        batch_op.add_column(Column('advance', Float, server_default='0'))
    conn.commit()

print(f'Done. salaries.advance added at {uri}')
