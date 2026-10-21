"""Cấp hàng loạt tài khoản đăng nhập cho học sinh đang học từ lớp 6 trở lên —
thay cho việc bấm "Tạo tài khoản học sinh" từng người trong trang chi tiết.

Điều kiện được cấp: hồ sơ đang hoạt động (is_active, chưa xoá, chưa tốt
nghiệp), cấp 2/cấp 3 (Lớp 6 trở lên), đang có ít nhất 1 lớp học còn hoạt động
và CHƯA có tài khoản. Một học sinh học nhiều môn/nhiều lớp vẫn chỉ là một hồ
sơ Student nên chỉ được cấp đúng 1 tài khoản (students.user_id là unique).
Hồ sơ nghi trùng (cùng tên + cùng SĐT phụ huynh hoặc cùng ngày sinh) chỉ cấp
cho hồ sơ có ID nhỏ nhất, các hồ sơ còn lại được liệt kê để admin tự kiểm tra.

Tên đăng nhập và mật khẩu mặc định dùng đúng quy ước của nút tạo tài khoản
(next_student_username / DEFAULT_STUDENT_TEMP_PASSWORD); học sinh phải đổi
mật khẩu khi đăng nhập lần đầu. Danh sách tài khoản được ghi ra file CSV để
gửi cho học sinh.

Mặc định chạy DRY-RUN — chỉ in ra danh sách sẽ cấp, KHÔNG ghi gì vào DB.
Chỉ khi thêm --apply mới thực sự commit.

Usage:
    python3 create_student_accounts.py                         # xem trước trên dev
    python3 create_student_accounts.py --apply                  # áp dụng thật trên dev
    DATABASE_URL=postgresql://... python3 create_student_accounts.py            # xem trước trên production
    DATABASE_URL=postgresql://... python3 create_student_accounts.py --apply    # áp dụng thật trên production
"""
import csv
import re
import sys
import unicodedata
from datetime import datetime

from app import create_app
from extensions import db
from models import Class, Enrollment, Student, StudentLevel, User, UserRole
from blueprints.admin.account_utils import DEFAULT_STUDENT_TEMP_PASSWORD, next_student_username

ELIGIBLE_LEVELS = (StudentLevel.SECONDARY, StudentLevel.HIGH_SCHOOL)


def _grade_number(current_grade):
    match = re.search(r'\d+', current_grade or '')
    return int(match.group()) if match else None


def _name_key(name):
    name = unicodedata.normalize('NFC', re.sub(r'\s+', ' ', (name or '').strip())).lower()
    return name


def _eligible_students():
    active_class_student_ids = (
        db.session.query(Enrollment.student_id)
        .join(Class, Class.id == Enrollment.class_id)
        .filter(Enrollment.is_active.is_(True), Class.is_active.is_(True))
    )
    students = (
        Student.query
        .filter(Student.is_active.is_(True),
                Student.is_deleted.isnot(True),
                db.or_(Student.status.is_(None), Student.status != 'graduated'),
                Student.level.in_(ELIGIBLE_LEVELS),
                Student.id.in_(active_class_student_ids))
        .order_by(Student.id)
        .all()
    )
    # current_grade là nguồn chính xác hơn level nếu đã được điền.
    return [s for s in students if (_grade_number(s.current_grade) or 6) >= 6]


def _split_duplicates(students):
    keep, duplicates, seen = [], [], {}
    for s in students:
        keys = []
        if s.parent_phone and s.parent_phone.strip():
            keys.append(('phone', _name_key(s.full_name), s.parent_phone.strip()))
        if s.date_of_birth:
            keys.append(('dob', _name_key(s.full_name), s.date_of_birth))
        original = next((seen[k] for k in keys if k in seen), None)
        if original:
            duplicates.append((s, original))
            continue
        for k in keys:
            seen[k] = s
        keep.append(s)
    return keep, duplicates


def main(argv):
    apply = '--apply' in argv
    app = create_app()
    with app.app_context():
        # So trùng trên cả những hồ sơ đã có tài khoản, để chạy lại script
        # không cấp thêm tài khoản cho bản trùng của một học sinh đã được cấp.
        unique_students, duplicates = _split_duplicates(_eligible_students())
        to_create = [s for s in unique_students if not s.user_id]
        duplicates = [(dup, original) for dup, original in duplicates if not dup.user_id]

        print(f'Học sinh đủ điều kiện chưa có tài khoản: {len(to_create) + len(duplicates)}')
        if duplicates:
            print(f'\nBỏ qua {len(duplicates)} hồ sơ nghi trùng (kiểm tra và gộp thủ công):')
            for dup, original in duplicates:
                print(f'  #{dup.id} {dup.full_name} ({dup.current_grade or "?"}) '
                      f'trùng với #{original.id} {original.full_name}')

        rows = []
        for s in to_create:
            username = next_student_username(s.full_name, s.current_grade)
            account = User(
                full_name=s.full_name,
                username=username,
                role=UserRole.STUDENT,
                is_active=True,
                must_change_password=True,
            )
            account.set_password(DEFAULT_STUDENT_TEMP_PASSWORD)
            db.session.add(account)
            # flush để next_student_username của học sinh kế tiếp thấy username
            # vừa cấp và tự thêm hậu tố khi trùng tên.
            db.session.flush()
            s.user_id = account.id
            classes = ', '.join(sorted({
                e.class_.name for e in s.enrollments.filter_by(is_active=True).all()
                if e.class_ and e.class_.is_active
            }))
            rows.append([s.id, s.full_name, s.current_grade or '', classes,
                         username, DEFAULT_STUDENT_TEMP_PASSWORD])

        print(f'\nSẽ cấp {len(rows)} tài khoản:')
        for row in rows:
            print(f'  #{row[0]} {row[1]} ({row[2]}) — {row[4]}')

        if not apply:
            db.session.rollback()
            print('\nDRY-RUN: chưa ghi gì vào DB. Thêm --apply để cấp thật.')
            return

        db.session.commit()
        out_path = f'student_accounts_{datetime.now():%Y%m%d_%H%M%S}.csv'
        with open(out_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['ID', 'Họ tên', 'Khối', 'Lớp đang học', 'Tên đăng nhập', 'Mật khẩu tạm'])
            writer.writerows(rows)
        print(f'\nĐã cấp {len(rows)} tài khoản. Danh sách lưu tại {out_path}')


if __name__ == '__main__':
    main(sys.argv[1:])
