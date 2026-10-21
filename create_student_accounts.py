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

Chạy theo từng lớp và commit sau mỗi lớp: nếu bị ngắt giữa chừng, các lớp đã
xong vẫn được giữ, chạy lại sẽ tiếp tục với những học sinh còn lại.

Mặc định chạy DRY-RUN — chỉ in ra danh sách sẽ cấp, KHÔNG ghi gì vào DB.
Chỉ khi thêm --apply mới thực sự commit.

Usage:
    python3 create_student_accounts.py                         # xem trước trên dev
    python3 create_student_accounts.py --apply                  # áp dụng thật trên dev
    python3 create_student_accounts.py --class-id 12 --apply    # chỉ cấp cho học sinh của lớp #12
    DATABASE_URL=postgresql://... python3 create_student_accounts.py            # xem trước trên production
    DATABASE_URL=postgresql://... python3 create_student_accounts.py --apply    # áp dụng thật trên production
"""
import csv
import re
import sys
import unicodedata
from datetime import datetime

from werkzeug.security import generate_password_hash

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


def _parse_class_id(argv):
    for i, arg in enumerate(argv):
        if arg.startswith('--class-id='):
            return int(arg.split('=', 1)[1])
        if arg == '--class-id' and i + 1 < len(argv):
            return int(argv[i + 1])
    return None


def _active_classes_by_student():
    """{student_id: [(class_id, class_name), ...]} in one query."""
    result = {}
    rows = (
        db.session.query(Enrollment.student_id, Class.id, Class.name)
        .join(Class, Class.id == Enrollment.class_id)
        .filter(Enrollment.is_active.is_(True), Class.is_active.is_(True))
        .order_by(Class.name)
        .all()
    )
    for student_id, class_id, class_name in rows:
        result.setdefault(student_id, []).append((class_id, class_name))
    return result


def main(argv):
    apply = '--apply' in argv
    only_class_id = _parse_class_id(argv)
    app = create_app()
    with app.app_context():
        # So trùng trên cả những hồ sơ đã có tài khoản, để chạy lại script
        # không cấp thêm tài khoản cho bản trùng của một học sinh đã được cấp.
        unique_students, duplicates = _split_duplicates(_eligible_students())
        to_create = [s for s in unique_students if not s.user_id]
        duplicates = [(dup, original) for dup, original in duplicates if not dup.user_id]
        classes_by_student = _active_classes_by_student()

        print(f'Học sinh đủ điều kiện chưa có tài khoản: {len(to_create) + len(duplicates)}', flush=True)
        if duplicates:
            print(f'\nBỏ qua {len(duplicates)} hồ sơ nghi trùng (kiểm tra và gộp thủ công):')
            for dup, original in duplicates:
                print(f'  #{dup.id} {dup.full_name} ({dup.current_grade or "?"}) '
                      f'trùng với #{original.id} {original.full_name}')

        # Mỗi học sinh chỉ thuộc đúng 1 nhóm (lớp đầu tiên theo tên), nên học
        # nhiều lớp cũng chỉ được cấp 1 tài khoản.
        batches = {}
        for s in to_create:
            student_classes = classes_by_student.get(s.id, [])
            if only_class_id is not None:
                if only_class_id not in {cid for cid, _ in student_classes}:
                    continue
                key = next((c for c in student_classes if c[0] == only_class_id))
            else:
                key = student_classes[0]
            batches.setdefault(key, []).append(s)

        # Tải trước toàn bộ username (1 query) và băm mật khẩu 1 lần thay vì
        # mỗi học sinh vài lượt gọi DB — chạy từ xa qua mạng sẽ nhanh hơn hẳn.
        taken = {u.lower() for (u,) in db.session.query(User.username).all()}
        password_hash = generate_password_hash(DEFAULT_STUDENT_TEMP_PASSWORD)

        out_path = f'student_accounts_{datetime.now():%Y%m%d_%H%M%S}.csv'
        csv_file = None
        writer = None
        if apply:
            csv_file = open(out_path, 'w', newline='', encoding='utf-8-sig')
            writer = csv.writer(csv_file)
            writer.writerow(['ID', 'Họ tên', 'Khối', 'Lớp đang học', 'Tên đăng nhập', 'Mật khẩu tạm'])

        total = 0
        try:
            for index, ((class_id, class_name), students) in enumerate(sorted(batches.items(), key=lambda b: b[0][1]), start=1):
                print(f'\n[{index}/{len(batches)}] Lớp {class_name} (#{class_id}) — {len(students)} học sinh', flush=True)
                rows = []
                for s in students:
                    username = next_student_username(s.full_name, s.current_grade, taken=taken)
                    if apply:
                        account = User(
                            full_name=s.full_name,
                            username=username,
                            role=UserRole.STUDENT,
                            is_active=True,
                            must_change_password=True,
                        )
                        account.password_hash = password_hash
                        db.session.add(account)
                        s.student_user = account
                    classes = ', '.join(name for _, name in classes_by_student.get(s.id, []))
                    rows.append([s.id, s.full_name, s.current_grade or '', classes,
                                 username, DEFAULT_STUDENT_TEMP_PASSWORD])
                    print(f'  #{s.id} {s.full_name} ({s.current_grade or "?"}) — {username}')
                if apply:
                    db.session.commit()
                    writer.writerows(rows)
                    csv_file.flush()
                    print(f'  ✓ Đã lưu {len(rows)} tài khoản của lớp {class_name}', flush=True)
                total += len(rows)
        finally:
            if csv_file:
                csv_file.close()

        if not apply:
            db.session.rollback()
            print(f'\nDRY-RUN: sẽ cấp {total} tài khoản, chưa ghi gì vào DB. Thêm --apply để cấp thật.')
            return
        print(f'\nĐã cấp {total} tài khoản. Danh sách lưu tại {out_path}')


if __name__ == '__main__':
    main(sys.argv[1:])
