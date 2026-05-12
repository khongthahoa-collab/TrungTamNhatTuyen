"""
Migration: Add gender column to users table
Run: python migrate_user_gender.py
"""
from app import create_app
from extensions import db
import sqlalchemy as sa


def migrate():
    app = create_app('development')
    with app.app_context():
        conn = db.engine.connect()
        trans = conn.begin()
        try:
            dialect = db.engine.dialect.name  # 'sqlite' or 'mysql'

            if dialect == 'sqlite':
                # SQLite: PRAGMA to check columns
                result = conn.execute(sa.text("PRAGMA table_info(users)"))
                columns = [row[1] for row in result.fetchall()]
                if 'gender' not in columns:
                    conn.execute(sa.text("ALTER TABLE users ADD COLUMN gender VARCHAR(10)"))
                    print("✓ Cột 'gender' đã thêm vào bảng 'users' (SQLite)")
                else:
                    print("✓ Cột 'gender' đã tồn tại (SQLite)")

            else:
                # MySQL: information_schema check
                result = conn.execute(sa.text("""
                    SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_schema = DATABASE()
                      AND table_name = 'users'
                      AND column_name = 'gender'
                """))
                if result.scalar() == 0:
                    conn.execute(sa.text(
                        "ALTER TABLE users ADD COLUMN gender VARCHAR(10) COMMENT 'male/female'"
                    ))
                    print("✓ Cột 'gender' đã thêm vào bảng 'users' (MySQL)")
                else:
                    print("✓ Cột 'gender' đã tồn tại (MySQL)")

            trans.commit()
            print("\n✅ Migration hoàn tất!")
        except Exception as e:
            trans.rollback()
            print(f"❌ Lỗi: {e}")
            raise


if __name__ == '__main__':
    migrate()
