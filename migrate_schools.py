"""
Migration: Add schools table and school_id column to students.
Run once on existing databases: python migrate_schools.py
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
            # 1. Create schools table if not exists
            conn.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS schools (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(200) NOT NULL UNIQUE,
                    grade_from INT,
                    grade_to INT,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("✓ Bảng 'schools' sẵn sàng")

            # 2. Add school_id column to students if not exists
            result = conn.execute(sa.text("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = 'students'
                  AND column_name = 'school_id'
            """))
            if result.scalar() == 0:
                conn.execute(sa.text("""
                    ALTER TABLE students
                    ADD COLUMN school_id INT,
                    ADD CONSTRAINT fk_students_school
                        FOREIGN KEY (school_id) REFERENCES schools(id)
                        ON DELETE SET NULL
                """))
                print("✓ Cột 'school_id' đã thêm vào bảng 'students'")
            else:
                print("✓ Cột 'school_id' đã tồn tại, bỏ qua")

            # 3. Widen current_school column if needed (from 100 → 200)
            conn.execute(sa.text("""
                ALTER TABLE students MODIFY COLUMN current_school VARCHAR(200)
            """))
            print("✓ Cột 'current_school' đã mở rộng lên 200 ký tự")

            trans.commit()
            print("\n✅ Migration hoàn tất!")
        except Exception as e:
            trans.rollback()
            print(f"❌ Lỗi: {e}")
            raise

if __name__ == '__main__':
    migrate()
