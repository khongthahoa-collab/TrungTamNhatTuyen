"""Make users.full_name and users.phone nullable so account creation only requires a username.

Usage:
    python3 migrate_user_optional_fields.py          # local dev (instance/nhat_tuyen_dev.db)
    DATABASE_URL=postgresql://... python3 migrate_user_optional_fields.py   # production
"""
import os

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine

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
        batch_op.alter_column('full_name', nullable=True)
        batch_op.alter_column('phone', nullable=True)
    conn.commit()

print(f'Done. users.full_name and users.phone are now nullable at {uri}')
