#!/usr/bin/env python3
"""
Import toàn bộ dữ liệu từ SQLite (nhat_tuyen.db) vào Supabase PostgreSQL.

Cách chạy:
    FLASK_ENV=production DATABASE_URL="postgresql+psycopg://..." python seed_supabase.py

Hoặc set DATABASE_URL trong .env rồi chạy:
    python seed_supabase.py
"""
import os
import sqlite3
from app import create_app
from extensions import db

SQLITE_PATH = os.path.join(os.path.dirname(__file__), 'nhat_tuyen.db')


BOOL_COLS = {
    'is_active', 'is_staff', 'is_cancelled', 'teacher_checked_in',
    'reward_suggested', 'is_paid', 'is_finalized', 'is_suggested',
    'is_confirmed', 'is_late_approval', 'zalo_notified', 'is_read',
    'is_tax_deductible', 'is_sent_zalo', 'confirm_tuition',
}


def rows_to_dicts(cursor, table):
    cursor.execute(f'SELECT * FROM {table}')
    cols = [d[0] for d in cursor.description]
    rows = []
    for row in cursor.fetchall():
        d = dict(zip(cols, row))
        # SQLite stores booleans as 0/1 integers — PostgreSQL needs True/False
        for k in BOOL_COLS:
            if k in d and d[k] is not None:
                d[k] = bool(d[k])
        rows.append(d)
    return rows


def migrate():
    if not os.path.exists(SQLITE_PATH):
        print(f'Không tìm thấy {SQLITE_PATH}')
        return

    env = os.environ.get('FLASK_ENV', 'production')
    app = create_app(env)

    with app.app_context():
        print('Tạo bảng (nếu chưa có)...')
        db.create_all()

        conn = sqlite3.connect(SQLITE_PATH)
        cur = conn.cursor()

        print('Xoá dữ liệu cũ (nếu có)...')
        # Xoá theo thứ tự ngược để tránh lỗi FK
        for tbl in [
            'rewards', 'tuition_payments', 'scores', 'attendances',
            'schedules', 'enrollments', 'students', 'classes',
            'teachers', 'courses', 'semesters', 'academic_years',
            'users', 'system_config',
        ]:
            db.session.execute(db.text(f'DELETE FROM {tbl}'))
        db.session.commit()

        # ── 1. system_config
        rows = rows_to_dicts(cur, 'system_config')
        for r in rows:
            db.session.execute(db.text(
                'INSERT INTO system_config (id, key, value, description, updated_at) '
                'VALUES (:id, :key, :value, :description, :updated_at)'
            ), r)
        print(f'  system_config: {len(rows)} dòng')

        # ── 2. academic_years
        rows = rows_to_dicts(cur, 'academic_years')
        for r in rows:
            db.session.execute(db.text(
                'INSERT INTO academic_years (id, name, start_date, end_date, is_active, created_at) '
                'VALUES (:id, :name, :start_date, :end_date, :is_active, :created_at)'
            ), r)
        print(f'  academic_years: {len(rows)} dòng')

        # ── 3. semesters
        rows = rows_to_dicts(cur, 'semesters')
        for r in rows:
            db.session.execute(db.text(
                'INSERT INTO semesters (id, academic_year_id, name, semester_type, start_date, end_date) '
                'VALUES (:id, :academic_year_id, :name, :semester_type, :start_date, :end_date)'
            ), r)
        print(f'  semesters: {len(rows)} dòng')

        # ── 4. users (bỏ cột gender nếu không có trong SQLite)
        rows = rows_to_dicts(cur, 'users')
        for r in rows:
            r.setdefault('gender', None)
            db.session.execute(db.text(
                'INSERT INTO users (id, full_name, username, phone, password_hash, role, gender, is_active, created_at, last_login) '
                'VALUES (:id, :full_name, :username, :phone, :password_hash, :role, :gender, :is_active, :created_at, :last_login)'
            ), r)
        print(f'  users: {len(rows)} dòng')

        # ── 5. courses
        rows = rows_to_dicts(cur, 'courses')
        for r in rows:
            db.session.execute(db.text(
                'INSERT INTO courses (id, name, level, description, is_active, created_at) '
                'VALUES (:id, :name, :level, :description, :is_active, :created_at)'
            ), r)
        print(f'  courses: {len(rows)} dòng')

        # ── 6. teachers (bỏ cột specialty không có trong model mới)
        rows = rows_to_dicts(cur, 'teachers')
        for r in rows:
            r.setdefault('base_salary', 0)
            db.session.execute(db.text(
                'INSERT INTO teachers (id, user_id, is_staff, base_salary, note) '
                'VALUES (:id, :user_id, :is_staff, :base_salary, :note)'
            ), r)
        print(f'  teachers: {len(rows)} dòng')

        # ── 7. classes (thêm các cột mới với giá trị mặc định)
        rows = rows_to_dicts(cur, 'classes')
        assistant_pairs = []  # (class_id, assistant_teacher_id) — nguồn SQLite cũ chỉ có 1 trợ giảng/lớp
        for r in rows:
            r.setdefault('monthly_fee', 0)
            r.setdefault('sessions_per_week', 1)
            r.setdefault('primary_teacher_id', None)
            r.setdefault('zalo_group_id', None)
            old_assistant_id = r.pop('assistant_teacher_id', None)
            if old_assistant_id:
                assistant_pairs.append((r['id'], old_assistant_id))
            db.session.execute(db.text(
                'INSERT INTO classes (id, name, course_id, grade_level, max_students, monthly_fee, '
                'sessions_per_week, start_date, end_date, is_active, description, '
                'primary_teacher_id, zalo_group_id, created_at) '
                'VALUES (:id, :name, :course_id, :grade_level, :max_students, :monthly_fee, '
                ':sessions_per_week, :start_date, :end_date, :is_active, :description, '
                ':primary_teacher_id, :zalo_group_id, :created_at)'
            ), r)
        for class_id, teacher_id in assistant_pairs:
            db.session.execute(db.text(
                'INSERT INTO class_assistant_teachers (class_id, teacher_id) VALUES (:class_id, :teacher_id)'
            ), {'class_id': class_id, 'teacher_id': teacher_id})
        print(f'  classes: {len(rows)} dòng ({len(assistant_pairs)} trợ giảng)')

        # ── 8. students (thêm cột mới)
        rows = rows_to_dicts(cur, 'students')
        for r in rows:
            r.setdefault('school_id', None)
            r.setdefault('photo_path', None)
            r.setdefault('status', 'active')
            db.session.execute(db.text(
                'INSERT INTO students (id, full_name, date_of_birth, gender, current_school, '
                'school_id, current_grade, level, parent_name, parent_phone, parent_user_id, '
                'note, photo_path, is_active, status, created_at) '
                'VALUES (:id, :full_name, :date_of_birth, :gender, :current_school, '
                ':school_id, :current_grade, :level, :parent_name, :parent_phone, :parent_user_id, '
                ':note, :photo_path, :is_active, :status, :created_at)'
            ), r)
        print(f'  students: {len(rows)} dòng')

        # ── 9. enrollments
        rows = rows_to_dicts(cur, 'enrollments')
        for r in rows:
            db.session.execute(db.text(
                'INSERT INTO enrollments (id, student_id, class_id, enrolled_at, is_active, discount_pct, note) '
                'VALUES (:id, :student_id, :class_id, :enrolled_at, :is_active, :discount_pct, :note)'
            ), r)
        print(f'  enrollments: {len(rows)} dòng')

        # ── 10. schedules
        rows = rows_to_dicts(cur, 'schedules')
        for r in rows:
            db.session.execute(db.text(
                'INSERT INTO schedules (id, class_id, teacher_id, date, start_time, end_time, '
                'room, topic, schedule_type, semester_id, is_cancelled, cancel_reason, '
                'teacher_checked_in, teacher_check_in_time, created_at) '
                'VALUES (:id, :class_id, :teacher_id, :date, :start_time, :end_time, '
                ':room, :topic, :schedule_type, :semester_id, :is_cancelled, :cancel_reason, '
                ':teacher_checked_in, :teacher_check_in_time, :created_at)'
            ), r)
        print(f'  schedules: {len(rows)} dòng')

        # ── 11. scores
        rows = rows_to_dicts(cur, 'scores')
        for r in rows:
            r.setdefault('reward_suggested', False)
            db.session.execute(db.text(
                'INSERT INTO scores (id, student_id, class_id, score_source, score_type, '
                'score_value, max_score, exam_date, school_name, note, entered_by, reward_suggested, created_at) '
                'VALUES (:id, :student_id, :class_id, :score_source, :score_type, '
                ':score_value, :max_score, :exam_date, :school_name, :note, :entered_by, :reward_suggested, :created_at)'
            ), r)
        print(f'  scores: {len(rows)} dòng')

        # ── 12. tuition_payments (thêm cột mới)
        rows = rows_to_dicts(cur, 'tuition_payments')
        for r in rows:
            r.setdefault('payment_stage', '100')
            r.setdefault('amount_25pct', 0)
            r.setdefault('amount_50pct', 0)
            r.setdefault('amount_75pct', 0)
            r.setdefault('amount_100pct', r.get('amount', 0))
            r.setdefault('school_name', None)
            r.setdefault('note_special', None)
            r.setdefault('is_finalized', False)
            db.session.execute(db.text(
                'INSERT INTO tuition_payments (id, student_id, class_id, amount, payment_stage, '
                'amount_25pct, amount_50pct, amount_75pct, amount_100pct, '
                'month, year, school_name, note_special, paid_at, method, received_by, note, is_paid, is_finalized, created_at) '
                'VALUES (:id, :student_id, :class_id, :amount, :payment_stage, '
                ':amount_25pct, :amount_50pct, :amount_75pct, :amount_100pct, '
                ':month, :year, :school_name, :note_special, :paid_at, :method, :received_by, :note, :is_paid, :is_finalized, :created_at)'
            ), r)
        print(f'  tuition_payments: {len(rows)} dòng')

        # ── 13. rewards
        rows = rows_to_dicts(cur, 'rewards')
        for r in rows:
            db.session.execute(db.text(
                'INSERT INTO rewards (id, student_id, reason, amount, reward_type, reward_date, '
                'note, is_suggested, is_confirmed, score_id, created_by, confirmed_by, confirmed_at) '
                'VALUES (:id, :student_id, :reason, :amount, :reward_type, :reward_date, '
                ':note, :is_suggested, :is_confirmed, :score_id, :created_by, :confirmed_by, :confirmed_at)'
            ), r)
        print(f'  rewards: {len(rows)} dòng')

        db.session.commit()
        conn.close()

        # Reset sequences PostgreSQL để auto-increment không bị conflict
        tables_with_id = [
            'system_config', 'academic_years', 'semesters', 'users', 'courses',
            'teachers', 'classes', 'students', 'enrollments', 'schedules',
            'scores', 'tuition_payments', 'rewards',
        ]
        for tbl in tables_with_id:
            db.session.execute(db.text(
                f"SELECT setval(pg_get_serial_sequence('{tbl}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {tbl}), 1))"
            ))
        db.session.commit()
        print('\nReset sequences PostgreSQL xong.')
        print('\n✓ Import hoàn tất!')


if __name__ == '__main__':
    migrate()
