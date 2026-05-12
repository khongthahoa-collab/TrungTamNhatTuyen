"""
Migration: Add attendance and tuition features
- Zalo group integration for classes
- Tuition payment stages (25%, 50%, 75%, 100%)
- Teacher Zalo notification preferences
Run: python migrate_attendance_tuition.py
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
            # 1. Add zalo_group_id to classes table (for class-specific Zalo group)
            result = conn.execute(sa.text("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = 'classes'
                  AND column_name = 'zalo_group_id'
            """))
            if result.scalar() == 0:
                conn.execute(sa.text("""
                    ALTER TABLE classes
                    ADD COLUMN zalo_group_id VARCHAR(100) COMMENT 'Zalo group ID for class notifications'
                """))
                print("✓ Cột 'zalo_group_id' đã thêm vào bảng 'classes'")
            else:
                print("✓ Cột 'zalo_group_id' đã tồn tại")

            # 2. Add percentage fields to tuition_payments table
            result = conn.execute(sa.text("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = 'tuition_payments'
                  AND column_name = 'payment_stage'
            """))
            if result.scalar() == 0:
                conn.execute(sa.text("""
                    ALTER TABLE tuition_payments
                    ADD COLUMN payment_stage VARCHAR(50) DEFAULT '100' COMMENT 'Giai đoạn: 25, 50, 75, 100',
                    ADD COLUMN amount_25pct FLOAT DEFAULT 0,
                    ADD COLUMN amount_50pct FLOAT DEFAULT 0,
                    ADD COLUMN amount_75pct FLOAT DEFAULT 0,
                    ADD COLUMN amount_100pct FLOAT DEFAULT 0,
                    ADD COLUMN is_finalized BOOLEAN DEFAULT FALSE COMMENT 'Đã tính toán cuối kỳ',
                    ADD COLUMN note_special VARCHAR(500) COMMENT 'Ghi chú đặc biệt'
                """))
                print("✓ Các cột tính học phí đã thêm vào bảng 'tuition_payments'")
            else:
                print("✓ Các cột tính học phí đã tồn tại")

            # 3. Create class_zalo_groups table for managing Zalo groups per class
            conn.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS class_zalo_groups (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    class_id INT NOT NULL,
                    zalo_group_id VARCHAR(100) UNIQUE,
                    zalo_group_name VARCHAR(255),
                    zalo_group_link VARCHAR(500),
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE
                )
            """))
            print("✓ Bảng 'class_zalo_groups' sẵn sàng")

            # 4. Add fields to attendance for better tracking
            result = conn.execute(sa.text("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = 'attendances'
                  AND column_name = 'reason'
            """))
            if result.scalar() == 0:
                conn.execute(sa.text("""
                    ALTER TABLE attendances
                    ADD COLUMN reason VARCHAR(255) COMMENT 'Lý do vắng (có phép)',
                    ADD COLUMN is_late_approval BOOLEAN DEFAULT FALSE COMMENT 'Phê duyệt trễ'
                """))
                print("✓ Cột 'reason' và 'is_late_approval' đã thêm vào bảng 'attendances'")
            else:
                print("✓ Cột 'reason' đã tồn tại")

            # 5. Add school info fields to tuition_payments
            result = conn.execute(sa.text("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = 'tuition_payments'
                  AND column_name = 'school_name'
            """))
            if result.scalar() == 0:
                conn.execute(sa.text("""
                    ALTER TABLE tuition_payments
                    ADD COLUMN school_name VARCHAR(200) COMMENT 'Tên trường học của học sinh'
                """))
                print("✓ Cột 'school_name' đã thêm vào bảng 'tuition_payments'")
            else:
                print("✓ Cột 'school_name' đã tồn tại")

            # 6. Create attendance_summary table for tracking attendance stats per session
            conn.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS attendance_summaries (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    schedule_id INT NOT NULL,
                    class_id INT NOT NULL,
                    total_enrolled INT DEFAULT 0,
                    present_count INT DEFAULT 0,
                    absent_count INT DEFAULT 0,
                    late_count INT DEFAULT 0,
                    excused_count INT DEFAULT 0,
                    is_sent_zalo BOOLEAN DEFAULT FALSE COMMENT 'Đã gửi Zalo',
                    zalo_sent_at DATETIME,
                    summary_note TEXT COMMENT 'Tóm tắt sau điểm danh',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE CASCADE,
                    FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE,
                    UNIQUE KEY unique_schedule (schedule_id)
                )
            """))
            print("✓ Bảng 'attendance_summaries' sẵn sàng")

            # 7. Create tuition_reports table for monthly tuition summary
            conn.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS tuition_reports (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    class_id INT NOT NULL,
                    month INT NOT NULL,
                    year INT NOT NULL,
                    total_students INT DEFAULT 0,
                    total_amount FLOAT DEFAULT 0,
                    amount_25pct_total FLOAT DEFAULT 0,
                    amount_50pct_total FLOAT DEFAULT 0,
                    amount_75pct_total FLOAT DEFAULT 0,
                    amount_100pct_total FLOAT DEFAULT 0,
                    fully_paid_count INT DEFAULT 0,
                    partial_paid_count INT DEFAULT 0,
                    unpaid_count INT DEFAULT 0,
                    is_finalized BOOLEAN DEFAULT FALSE,
                    finalized_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE,
                    UNIQUE KEY unique_report (class_id, month, year)
                )
            """))
            print("✓ Bảng 'tuition_reports' sẵn sàng")

            trans.commit()
            print("\n✅ Migration hoàn tất!")
        except Exception as e:
            trans.rollback()
            print(f"❌ Lỗi: {e}")
            raise

if __name__ == '__main__':
    migrate()
