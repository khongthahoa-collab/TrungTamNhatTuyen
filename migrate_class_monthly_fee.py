"""
Migration: Add monthly_fee + sessions_per_week to classes; create monthly_class_fees table
Run: python migrate_class_monthly_fee.py
"""
from app import create_app
from extensions import db
import sqlalchemy as sa


def col_exists(conn, table, column, dialect):
    if dialect == 'sqlite':
        result = conn.execute(sa.text(f"PRAGMA table_info({table})"))
        return any(row[1] == column for row in result.fetchall())
    else:
        result = conn.execute(sa.text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema=DATABASE() AND table_name=:t AND column_name=:c"
        ), {'t': table, 'c': column})
        return result.scalar() > 0


def migrate():
    app = create_app('development')
    with app.app_context():
        conn = db.engine.connect()
        trans = conn.begin()
        dialect = db.engine.dialect.name
        try:
            # 1. classes.monthly_fee
            if not col_exists(conn, 'classes', 'monthly_fee', dialect):
                conn.execute(sa.text(
                    "ALTER TABLE classes ADD COLUMN monthly_fee FLOAT DEFAULT 0"
                ))
                print("✓ Thêm cột 'monthly_fee' vào bảng 'classes'")
            else:
                print("✓ 'classes.monthly_fee' đã tồn tại")

            # 2. classes.sessions_per_week
            if not col_exists(conn, 'classes', 'sessions_per_week', dialect):
                conn.execute(sa.text(
                    "ALTER TABLE classes ADD COLUMN sessions_per_week INTEGER DEFAULT 1"
                ))
                print("✓ Thêm cột 'sessions_per_week' vào bảng 'classes'")
            else:
                print("✓ 'classes.sessions_per_week' đã tồn tại")

            # 3. monthly_class_fees table
            if dialect == 'sqlite':
                conn.execute(sa.text("""
                    CREATE TABLE IF NOT EXISTS monthly_class_fees (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
                        month INTEGER NOT NULL,
                        year INTEGER NOT NULL,
                        standard_weeks INTEGER DEFAULT 4,
                        weeks_billed REAL DEFAULT 4.0,
                        base_fee REAL DEFAULT 0,
                        adjusted_fee REAL DEFAULT 0,
                        note VARCHAR(255),
                        created_by INTEGER REFERENCES users(id),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (class_id, month, year)
                    )
                """))
            else:
                conn.execute(sa.text("""
                    CREATE TABLE IF NOT EXISTS monthly_class_fees (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        class_id INT NOT NULL,
                        month INT NOT NULL,
                        year INT NOT NULL,
                        standard_weeks INT DEFAULT 4,
                        weeks_billed FLOAT DEFAULT 4.0,
                        base_fee FLOAT DEFAULT 0,
                        adjusted_fee FLOAT DEFAULT 0,
                        note VARCHAR(255),
                        created_by INT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE,
                        FOREIGN KEY (created_by) REFERENCES users(id),
                        UNIQUE KEY uq_monthly_class_fee (class_id, month, year)
                    )
                """))
            print("✓ Bảng 'monthly_class_fees' sẵn sàng")

            trans.commit()
            print("\n✅ Migration hoàn tất!")
        except Exception as e:
            trans.rollback()
            print(f"❌ Lỗi: {e}")
            raise


if __name__ == '__main__':
    migrate()
