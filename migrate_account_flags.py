"""Add is_master / must_change_password / is_deleted columns to users, and
flag the seeded 'nhattuyen' account as the admin master.

Usage:
    python3 migrate_account_flags.py          # local dev (instance/nhat_tuyen_dev.db)
    DATABASE_URL=postgresql://... python3 migrate_account_flags.py   # production
"""
import os

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Boolean, Column, create_engine, false, text

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
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(Column('is_master', Boolean, nullable=False, server_default=false()))
        batch_op.add_column(Column('must_change_password', Boolean, nullable=False, server_default=false()))
        batch_op.add_column(Column('is_deleted', Boolean, nullable=False, server_default=false()))
    conn.execute(text("UPDATE users SET is_master = true WHERE username = 'nhattuyen'"))
    conn.commit()

print(f'Done. users.is_master/must_change_password/is_deleted added at {uri}; nhattuyen flagged as master.')
