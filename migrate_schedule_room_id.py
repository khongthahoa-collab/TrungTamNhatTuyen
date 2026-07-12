"""Restore schedules.room_id (FK to rooms.id) — the column was dropped from the
model at some point but blueprints/admin/classes.py, blueprints/teacher.py and
blueprints/admin/rooms.py all still assumed it exists (room-conflict checks,
schedule generation), causing 500 errors on class/schedule creation with a
room selected.

Usage:
    python3 migrate_schedule_room_id.py          # local dev (instance/nhat_tuyen_dev.db)
    DATABASE_URL=postgresql://... python3 migrate_schedule_room_id.py   # production
"""
import os

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, ForeignKey, Integer, create_engine

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
    with op.batch_alter_table('schedules') as batch_op:
        batch_op.add_column(Column('room_id', Integer,
                                    ForeignKey('rooms.id', name='fk_schedules_room_id'),
                                    nullable=True))
    conn.commit()

print(f'Done. schedules.room_id added at {uri}')
