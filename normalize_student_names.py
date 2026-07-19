"""Chuẩn hoá viết hoa tên học sinh về dạng "Phương Khanh" (hoa chữ cái đầu
mỗi từ, còn lại thường) — dùng str.upper()/lower() của Python, xử lý Unicode
tiếng Việt đúng (Ư, Ơ, Ă, Đ...) chứ không dựa vào LOWER()/INITCAP() của DB,
vốn phụ thuộc locale và có thể không hạ/nâng đúng chữ có dấu. Đồng thời gộp
khoảng trắng thừa.

Mặc định chạy DRY-RUN — chỉ in ra tên nào sẽ đổi, KHÔNG ghi gì vào DB.
Chỉ khi thêm --apply mới thực sự commit.

Usage:
    python3 normalize_student_names.py                        # xem trước trên dev
    python3 normalize_student_names.py --apply                 # áp dụng thật trên dev
    python3 normalize_student_names.py --exclude 98,582,591    # bỏ qua các ID này (xem trước hoặc --apply)
    DATABASE_URL=postgresql://... python3 normalize_student_names.py            # xem trước trên production
    DATABASE_URL=postgresql://... python3 normalize_student_names.py --apply    # áp dụng thật trên production
"""
import re
import sys

from app import create_app
from extensions import db
from models import Student


def to_title_case(name):
    name = re.sub(r'\s+', ' ', (name or '').strip())
    return ' '.join(w[:1].upper() + w[1:].lower() for w in name.split(' '))


def _parse_exclude(argv):
    for arg in argv:
        if arg.startswith('--exclude='):
            return {int(x) for x in arg.split('=', 1)[1].split(',') if x}
    if '--exclude' in argv:
        idx = argv.index('--exclude')
        if idx + 1 < len(argv):
            return {int(x) for x in argv[idx + 1].split(',') if x}
    return set()


def main():
    apply_changes = '--apply' in sys.argv
    exclude_ids = _parse_exclude(sys.argv)
    app = create_app()
    with app.app_context():
        students = Student.query.filter_by(is_deleted=False).order_by(Student.full_name).all()
        changes = [(s, to_title_case(s.full_name)) for s in students]
        changes = [(s, new) for s, new in changes if new != s.full_name and s.id not in exclude_ids]

        if exclude_ids:
            print(f'Bỏ qua {len(exclude_ids)} ID: {sorted(exclude_ids)}\n')

        if not changes:
            print('Không có tên nào cần đổi định dạng.')
            return

        print(f'{len(changes)} học sinh sẽ đổi tên:\n')
        for s, new_name in changes:
            print(f'  #{s.id}: {s.full_name!r}  ->  {new_name!r}')

        if not apply_changes:
            print(f'\n[DRY-RUN] Chưa ghi gì vào DB. Chạy lại kèm --apply để áp dụng thật.')
            return

        for s, new_name in changes:
            s.full_name = new_name
        db.session.commit()
        print(f'\nĐã cập nhật {len(changes)} học sinh.')


if __name__ == '__main__':
    main()
