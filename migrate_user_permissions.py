"""
Migration: Add permissions column to users table
Run locally: python migrate_user_permissions.py
Run on production (Supabase): set DATABASE_URL / FLASK_ENV=production before running,
or run the equivalent ALTER TABLE manually against the Supabase database.
"""
import os
import sqlalchemy as sa
from config import config as config_map


def migrate():
    env = os.environ.get('FLASK_ENV', 'development')
    # Connect directly (bypassing create_app) since app.py's dev auto-seed
    # queries users via the ORM, which already expects this column to exist.
    uri = config_map[env].SQLALCHEMY_DATABASE_URI
    if uri.startswith('sqlite:///') and not uri.startswith('sqlite:////'):
        # Flask-SQLAlchemy resolves relative sqlite paths against the instance folder
        rel_path = uri[len('sqlite:///'):]
        base_dir = os.path.dirname(os.path.abspath(__file__))
        uri = 'sqlite:///' + os.path.join(base_dir, 'instance', rel_path)
    engine = sa.create_engine(uri)
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            dialect = engine.dialect.name  # 'sqlite' or 'postgresql'

            if dialect == 'sqlite':
                result = conn.execute(sa.text("PRAGMA table_info(users)"))
                columns = [row[1] for row in result.fetchall()]
                if 'permissions' not in columns:
                    conn.execute(sa.text("ALTER TABLE users ADD COLUMN permissions TEXT"))
                    print("✓ Cột 'permissions' đã thêm vào bảng 'users' (SQLite)")
                else:
                    print("✓ Cột 'permissions' đã tồn tại (SQLite)")

            else:
                result = conn.execute(sa.text("""
                    SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'users'
                      AND column_name = 'permissions'
                """))
                if result.scalar() == 0:
                    conn.execute(sa.text("ALTER TABLE users ADD COLUMN permissions TEXT"))
                    print("✓ Cột 'permissions' đã thêm vào bảng 'users' (PostgreSQL)")
                else:
                    print("✓ Cột 'permissions' đã tồn tại (PostgreSQL)")

            trans.commit()
            print("\n✅ Migration hoàn tất!")
        except Exception as e:
            trans.rollback()
            print(f"❌ Lỗi: {e}")
            raise


if __name__ == '__main__':
    migrate()
