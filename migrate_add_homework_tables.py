"""Tạo bảng homeworks + homework_records (mô hình Homework / HomeworkRecord
trong models.py) — theo dõi tình hình làm bài tập về nhà của học sinh.

Bài tập về nhà KHÔNG chấm điểm: mỗi học sinh chỉ được ghi nhận có làm /
không làm, phần chi tiết ("thiếu bài 3, 4") nằm ở cột note. Vì vậy dữ liệu
cố ý không nằm trong bảng scores — mọi dòng ở đó bắt buộc có score_value,
nên "có làm bài" sẽ bị cộng vào điểm trung bình và số Đạt/Không đạt của
trang Chi tiết điểm, làm sai lệch đánh giá học lực.

An toàn để chạy lại nhiều lần.

Ngoài create_all(), script còn dọn một ràng buộc sai của bản dựng thử ban
đầu: UNIQUE(class_id, assigned_date) — ràng buộc đó chặn việc một lớp giao
nhiều lần bài tập khác nhau trong cùng một ngày, là điều có thật. Chỉ dựng
lại bảng khi bảng đang RỖNG, nên không có rủi ro mất dữ liệu.

Usage:
    python3 migrate_add_homework_tables.py                              # dev
    DATABASE_URL=postgresql://... python3 migrate_add_homework_tables.py  # production
"""
from sqlalchemy import text, inspect
from app import create_app
from extensions import db
import models  # noqa: F401  — đăng ký hết model trước khi create_all()

app = create_app()
with app.app_context():
    insp = inspect(db.engine)
    dialect = db.engine.dialect.name

    if 'homeworks' in insp.get_table_names():
        cols = {c['name'] for c in insp.get_columns('homeworks')}

        # 1) Cột đánh số lần giao trong ngày (thêm sau bản dựng thử đầu).
        if 'assignment_round' not in cols:
            if dialect == 'postgresql':
                db.session.execute(text(
                    'ALTER TABLE homeworks ADD COLUMN IF NOT EXISTS assignment_round INTEGER DEFAULT 1'))
            else:
                db.session.execute(text(
                    'ALTER TABLE homeworks ADD COLUMN assignment_round INTEGER DEFAULT 1'))
            db.session.commit()
            print('Đã thêm cột assignment_round vào bảng homeworks.')

        # 2) Gỡ ràng buộc duy nhất (class_id, assigned_date) nếu còn.
        has_obsolete_uq = any(
            set(uc.get('column_names') or []) == {'class_id', 'assigned_date'}
            for uc in insp.get_unique_constraints('homeworks')
        )
        if has_obsolete_uq:
            if dialect == 'postgresql':
                db.session.execute(text(
                    'ALTER TABLE homeworks DROP CONSTRAINT IF EXISTS uq_homework_class_date'))
                db.session.commit()
                print('Đã gỡ ràng buộc uq_homework_class_date.')
            else:
                # SQLite không gỡ được ràng buộc tại chỗ — phải dựng lại bảng.
                # Chỉ làm khi bảng rỗng để không thể mất dữ liệu.
                n = db.session.execute(text('SELECT COUNT(*) FROM homeworks')).scalar()
                if n:
                    print(f'BỎ QUA: bảng homeworks còn {n} dòng — dựng lại bảng sẽ '
                          'mất dữ liệu. Cần xử lý thủ công.')
                else:
                    db.session.execute(text('DROP TABLE IF EXISTS homework_records'))
                    db.session.execute(text('DROP TABLE homeworks'))
                    db.session.commit()
                    print('Đã dựng lại bảng homeworks (bảng rỗng, gỡ ràng buộc cũ).')

    db.create_all()
    print('Đã đảm bảo bảng homeworks và homework_records tồn tại.')
