"""
Migration: Add rooms and contact_inquiries tables, and additional columns
Run: python migrate_rooms_and_inquiries.py
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
            # 1. Create rooms table
            conn.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS rooms (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    branch VARCHAR(200),
                    floor VARCHAR(20),
                    room_number VARCHAR(20),
                    capacity INT DEFAULT 20,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("✓ Bảng 'rooms' sẵn sàng")

            # 2. Create contact_inquiries table
            conn.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS contact_inquiries (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    student_name VARCHAR(100) NOT NULL,
                    grade VARCHAR(50),
                    subject VARCHAR(100),
                    school VARCHAR(150),
                    parent_phone VARCHAR(20) NOT NULL,
                    note TEXT,
                    confirm_tuition BOOLEAN DEFAULT FALSE,
                    is_read BOOLEAN DEFAULT FALSE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("✓ Bảng 'contact_inquiries' sẵn sàng")

            # 3. Add status column to students if not exists
            result = conn.execute(sa.text("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = 'students'
                  AND column_name = 'status'
            """))
            if result.scalar() == 0:
                conn.execute(sa.text("""
                    ALTER TABLE students
                    ADD COLUMN status VARCHAR(20) DEFAULT 'active'
                """))
                print("✓ Cột 'status' đã thêm vào bảng 'students'")
            else:
                print("✓ Cột 'status' đã tồn tại")

            # 4. Add photo_path column to students if not exists
            result = conn.execute(sa.text("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = 'students'
                  AND column_name = 'photo_path'
            """))
            if result.scalar() == 0:
                conn.execute(sa.text("""
                    ALTER TABLE students
                    ADD COLUMN photo_path VARCHAR(255)
                """))
                print("✓ Cột 'photo_path' đã thêm vào bảng 'students'")
            else:
                print("✓ Cột 'photo_path' đã tồn tại")

            # 5. Add primary_teacher_id and assistant_teacher_id to classes if not exist
            result = conn.execute(sa.text("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = 'classes'
                  AND column_name = 'primary_teacher_id'
            """))
            if result.scalar() == 0:
                conn.execute(sa.text("""
                    ALTER TABLE classes
                    ADD COLUMN primary_teacher_id INT,
                    ADD COLUMN assistant_teacher_id INT,
                    ADD CONSTRAINT fk_classes_primary_teacher
                        FOREIGN KEY (primary_teacher_id) REFERENCES teachers(id)
                        ON DELETE SET NULL,
                    ADD CONSTRAINT fk_classes_assistant_teacher
                        FOREIGN KEY (assistant_teacher_id) REFERENCES teachers(id)
                        ON DELETE SET NULL
                """))
                print("✓ Cột 'primary_teacher_id' và 'assistant_teacher_id' đã thêm vào bảng 'classes'")
            else:
                print("✓ Cột teacher_id đã tồn tại trong bảng 'classes'")

            # 6. Create notifications table if not exists
            conn.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    message TEXT,
                    is_read BOOLEAN DEFAULT FALSE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """))
            print("✓ Bảng 'notifications' sẵn sàng")

            # 7. Create class_documents table if not exists
            conn.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS class_documents (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    class_id INT NOT NULL,
                    uploaded_by INT NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    description VARCHAR(500),
                    original_filename VARCHAR(255),
                    stored_filename VARCHAR(255),
                    file_size INT,
                    file_type VARCHAR(20),
                    is_active BOOLEAN DEFAULT TRUE,
                    uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE,
                    FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE CASCADE
                )
            """))
            print("✓ Bảng 'class_documents' sẵn sàng")

            trans.commit()
            print("\n✅ Migration hoàn tất!")
        except Exception as e:
            trans.rollback()
            print(f"❌ Lỗi: {e}")
            raise

if __name__ == '__main__':
    migrate()
