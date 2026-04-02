"""
Initialize database and seed sample data for Nhat Tuyen tutoring center.
Run: python init_db.py
"""
from app import create_app
from extensions import db
from models import (
    User, Teacher, Course, Class, Student, Enrollment,
    AcademicYear, Semester, Schedule, SystemConfig, School,
    Score, Reward, TuitionPayment,
    UserRole, StudentLevel, ScheduleType, ScoreSource, ScoreType, SemesterType, TuitionMethod
)
from datetime import date, time, timedelta, datetime


def seed():
    app = create_app('development')
    with app.app_context():
        db.drop_all()
        db.create_all()
        print("✓ Database schema created")

        # ── System configuration
        configs = [
            ('center_name', 'Học thêm Nhật Tuyền', 'Center name'),
            ('center_address', '159 Lê Hồng Phong, Phường Kon Tum, Quảng Ngãi', 'Center address'),
            ('center_phone', '0901901891', 'Center phone number'),
            ('zalo_link', 'https://zalo.me/0901901891', 'Zalo chat link'),
            ('messenger_link', 'https://m.me/nhattuyenedu', 'Messenger link'),
            ('bank_account', '1234567890 - Vietcombank - Nguyen Trinh Thu Phuong', 'Bank account'),
            ('hall_of_fame_min_score', '8', 'Minimum score for hall of fame'),
            ('hero_bg',         '#f8fdf9',                                      'Hero background color'),
            ('hero_badge',      'TRUNG TÂM DẠY THÊM UY TÍN',                   'Hero badge text'),
            ('hero_headline1',  'Học Thêm Chất Lượng',                          'Hero headline line 1'),
            ('hero_headline2',  'Tại Nhật Tuyền',                               'Hero headline line 2 (gradient)'),
            ('hero_sub',        'Lớp học sĩ số nhỏ, giáo viên tâm huyết — đồng hành cùng học sinh Tiểu học, THCS và THPT trên con đường học vấn.', 'Hero subtitle'),
            ('hero_note',       'Tư vấn miễn phí – Liên hệ ngay hôm nay',       'Hero note below CTA button'),
        ]
        for key, val, desc in configs:
            db.session.add(SystemConfig(key=key, value=val, description=desc))

        # ── Admin account
        admin = User(
            full_name='Nguyen Thi Nhat Tuyen',
            username='admin',
            phone='0901234567',
            role=UserRole.ADMIN
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.flush()

        # ── Courses (fixed list, no level field)
        course_names_list = [
            'Toán', 'Tiếng Việt', 'Ngữ Văn', 'Anh Văn',
            'Lịch Sử', 'Địa Lý', 'KHTN',
            'Vật lý', 'Hóa học', 'Sinh học', 'Tiếng Trung',
        ]
        courses = {}
        for cname in course_names_list:
            c = Course(name=cname)
            db.session.add(c)
            db.session.flush()
            courses[cname] = c
        print(f"✓ {len(courses)} môn học đã được thêm")

        # ── Teachers
        teacher_data = [
            # (full_name, username, phone, is_staff, base_salary)
            ('Trần Văn An', 'gvtoan', '0912345678', True, 8000000),
            ('Lê Thị Bình', 'gvly', '0923456789', True, 7000000),
            ('Phạm Quốc Cường', 'gvhoa', '0934567890', True, 7500000),
            ('Nguyễn Minh Dũng', 'gvvan', '0945678901', False, 0),
        ]
        teachers = []
        for fname, uname, phone, is_staff, salary in teacher_data:
            u = User(full_name=fname, username=uname, phone=phone, role=UserRole.TEACHER)
            u.set_password('teacher123')
            db.session.add(u)
            db.session.flush()
            t = Teacher(user_id=u.id, is_staff=is_staff, base_salary=salary)
            db.session.add(t)
            db.session.flush()
            teachers.append(t)

        db.session.flush()

        # ── Academic year
        ay = AcademicYear(
            name='2025-2026',
            start_date=date(2025, 6, 1),
            end_date=date(2026, 5, 31),
            is_active=True
        )
        db.session.add(ay)
        db.session.flush()

        # ── Semesters
        sem_summer = Semester(
            academic_year_id=ay.id,
            name='Học hè 2025',
            semester_type=SemesterType.SUMMER,
            start_date=date(2025, 6, 1),
            end_date=date(2025, 8, 31)
        )
        sem_1 = Semester(
            academic_year_id=ay.id,
            name='Học kỳ 1 (2025-2026)',
            semester_type=SemesterType.SEMESTER_1,
            start_date=date(2025, 9, 1),
            end_date=date(2026, 1, 31)
        )
        sem_2 = Semester(
            academic_year_id=ay.id,
            name='Học kỳ 2 (2025-2026)',
            semester_type=SemesterType.SEMESTER_2,
            start_date=date(2026, 2, 1),
            end_date=date(2026, 5, 31)
        )
        db.session.add_all([sem_summer, sem_1, sem_2])
        db.session.flush()

        # ── Classes
        class_data = [
            # (name, course_key, grade_level, primary_teacher_idx, max_students)
            ('Lớp 8A - Toán',     'Toán',    'Lớp 8',  0, 15),
            ('Lớp 10A - Toán',    'Toán',    'Lớp 10', 0, 15),
            ('Lớp 10A - Vật lý',  'Vật lý',  'Lớp 10', 1, 12),
            ('Lớp 9A - Hóa học',  'Hóa học', 'Lớp 9',  2, 12),
            ('Lớp 4A - Toán',     'Toán',    'Lớp 4',  0, 10),
        ]
        classes = []
        for cname, course_key, grade, primary_idx, max_s in class_data:
            primary_teacher = teachers[primary_idx]
            cl = Class(
                name=cname,
                course_id=courses[course_key].id,
                grade_level=grade,
                max_students=max_s,
                primary_teacher_id=primary_teacher.id,
                start_date=date(2025, 9, 1),
                end_date=date(2026, 5, 31)
            )
            db.session.add(cl)
            db.session.flush()
            classes.append((cl, primary_teacher))

        # ── Schools
        school_data = [
            # (name, grade_from, grade_to)
            ('Tiểu học Lê Lợi',         1,  5),
            ('Tiểu học Nguyễn Trãi',     1,  5),
            ('THCS Lê Văn Tám',          6,  9),
            ('THCS Nguyễn Du',           6,  9),
            ('THPT Nguyễn Trãi',        10, 12),
            ('THPT Trần Phú',           10, 12),
        ]
        seed_schools = {}
        for sname, gf, gt in school_data:
            sc = School(name=sname, grade_from=gf, grade_to=gt)
            db.session.add(sc)
            db.session.flush()
            seed_schools[sname] = sc
        print(f"✓ {len(seed_schools)} trường học đã được thêm")

        # ── Students
        students_data = [
            # (full_name, dob, gender, school_key, current_grade, level, parent_name, parent_phone)
            ('Nguyễn Văn Anh',  date(2010, 3, 15), 'male',   'THCS Lê Văn Tám',     '8A',  StudentLevel.SECONDARY,   'Nguyễn Văn Bình',   '0901111111'),
            ('Trần Thị Bảo',    date(2010, 7, 22), 'female', 'THCS Lê Văn Tám',     '8A',  StudentLevel.SECONDARY,   'Trần Văn Cường',    '0902222222'),
            ('Lê Minh Chiến',   date(2009, 11, 5), 'male',   'THCS Nguyễn Du',      '9B',  StudentLevel.SECONDARY,   'Lê Thị Dung',       '0903333333'),
            ('Phạm Thị Diệu',   date(2008, 5, 18), 'female', 'THPT Nguyễn Trãi',    '10A', StudentLevel.HIGH_SCHOOL, 'Phạm Văn Em',       '0904444444'),
            ('Hoàng Văn Em',    date(2008, 9, 30), 'male',   'THPT Nguyễn Trãi',    '10B', StudentLevel.HIGH_SCHOOL, 'Hoàng Thị Phương',  '0905555555'),
            ('Võ Thị Phương',   date(2007, 1, 12), 'female', 'THPT Trần Phú',       '11C', StudentLevel.HIGH_SCHOOL, 'Võ Văn Giang',      '0906666666'),
            ('Đặng Quốc Hùng',  date(2014, 6,  8), 'male',   'Tiểu học Lê Lợi',     '4A',  StudentLevel.PRIMARY,     'Đặng Văn Hải',      '0907777777'),
            ('Bùi Thị Lan',     date(2014, 2, 25), 'female', 'Tiểu học Lê Lợi',     '4B',  StudentLevel.PRIMARY,     'Bùi Văn Kiên',      '0908888888'),
            ('Ngô Văn Mạnh',    date(2010, 8, 14), 'male',   'THCS Lê Văn Tám',     '8B',  StudentLevel.SECONDARY,   'Ngô Thị Ngọc',      '0909999999'),
            ('Đinh Thị Ngọc',   date(2009, 4,  3), 'female', 'THCS Nguyễn Du',      '9A',  StudentLevel.SECONDARY,   'Đinh Văn Phúc',     '0910101010'),
        ]

        # ── Parent accounts (for some students)
        parent_phones = ['0901111111', '0902222222', '0903333333']
        parent_users = {}
        for i, pp in enumerate(parent_phones):
            pu = User(
                full_name=students_data[i][7],
                username=f'parent{i+1:02d}',
                phone=pp,
                role=UserRole.PARENT
            )
            pu.set_password('parent123')
            db.session.add(pu)
            db.session.flush()
            parent_users[pp] = pu

        # ── Create students
        students = []
        for sdata in students_data:
            fname, dob, gender, school_key, grade, level, pname, pphone = sdata
            pu = parent_users.get(pphone)
            school_obj = seed_schools.get(school_key)
            s = Student(
                full_name=fname,
                date_of_birth=dob,
                gender=gender,
                current_school=school_key,
                school_id=school_obj.id if school_obj else None,
                current_grade=grade,
                level=level,
                parent_name=pname,
                parent_phone=pphone,
                parent_user_id=pu.id if pu else None
            )
            db.session.add(s)
            db.session.flush()
            students.append(s)

        # ── Student enrollments in classes
        enrollments_map = [
            # (student_index, class_index)
            (0, 0),   # Anh → Math 8A
            (1, 0),   # Bao → Math 8A
            (2, 3),   # Chien → Chemistry 9A
            (3, 1),   # Dieu → Math 10B
            (3, 2),   # Dieu → Physics 10A
            (4, 1),   # Em → Math 10B
            (4, 2),   # Em → Physics 10A
            (5, 1),   # Phuong → Math 10B
            (6, 4),   # Hung → Math Primary
            (7, 4),   # Lan → Math Primary
            (8, 0),   # Manh → Math 8A
            (9, 3),   # Ngoc → Chemistry 9A
            (2, 0),   # Chien → Math 8A
        ]
        for si, ci in enrollments_map:
            e = Enrollment(student_id=students[si].id, class_id=classes[ci][0].id)
            db.session.add(e)

        db.session.flush()

        # ── Class schedules
        today = date.today()
        # Find Monday of current week
        monday = today - timedelta(days=today.weekday())

        schedule_patterns = [
            # (class_index, weekday_offset, start_time, end_time, room)
            # Math 8A: Mon, Wed, Fri 17:00-19:00
            (0, 0, time(17, 0), time(19, 0), 'Room 101'),
            (0, 2, time(17, 0), time(19, 0), 'Room 101'),
            (0, 4, time(17, 0), time(19, 0), 'Room 101'),
            # Math 10B: Tue, Thu, Sat 17:00-19:00
            (1, 1, time(17, 0), time(19, 0), 'Room 102'),
            (1, 3, time(17, 0), time(19, 0), 'Room 102'),
            (1, 5, time(17, 0), time(19, 0), 'Room 102'),
            # Physics 10A: Mon, Thu 19:00-21:00
            (2, 0, time(19, 0), time(21, 0), 'Room 103'),
            (2, 3, time(19, 0), time(21, 0), 'Room 103'),
            # Chemistry 9A: Tue, Sat 17:00-19:00
            (3, 1, time(17, 0), time(19, 0), 'Room 104'),
            (3, 5, time(17, 0), time(19, 0), 'Room 104'),
            # Math Primary: Wed, Sat 15:00-17:00
            (4, 2, time(15, 0), time(17, 0), 'Room 105'),
            (4, 5, time(15, 0), time(17, 0), 'Room 105'),
        ]

        # Generate 4 weeks of schedules (2 past + current + 1 future)
        for week_offset in range(-2, 2):
            week_start = monday + timedelta(weeks=week_offset)
            for ci, day_off, st, et, room in schedule_patterns:
                sched_date = week_start + timedelta(days=day_off)
                cl, teacher = classes[ci]
                s = Schedule(
                    class_id=cl.id,
                    teacher_id=teacher.id,
                    date=sched_date,
                    start_time=st,
                    end_time=et,
                    room=room,
                    schedule_type=ScheduleType.REGULAR,
                    semester_id=sem_1.id,
                    teacher_checked_in=(week_offset < 0),  # past weeks: all checked in
                    teacher_check_in_time=None,
                )
                db.session.add(s)

        db.session.flush()

        # ── Sample scores
        score_samples = [
            # (student_index, class_index, source, type, value, exam_date)
            (0, 0, ScoreSource.CENTER, ScoreType.CONTINUOUS, 8.5, date(2025, 10, 5)),
            (0, 0, ScoreSource.CENTER, ScoreType.MIDTERM, 9.0, date(2025, 11, 10)),
            (1, 0, ScoreSource.CENTER, ScoreType.CONTINUOUS, 7.0, date(2025, 10, 5)),
            (1, 0, ScoreSource.CENTER, ScoreType.MIDTERM, 8.0, date(2025, 11, 10)),
            (2, 0, ScoreSource.CENTER, ScoreType.CONTINUOUS, 10.0, date(2025, 10, 5)),
            (2, 0, ScoreSource.CENTER, ScoreType.MIDTERM, 9.5, date(2025, 11, 10)),
            (3, 1, ScoreSource.CENTER, ScoreType.CONTINUOUS, 9.0, date(2025, 10, 12)),
            (3, 1, ScoreSource.SCHOOL, ScoreType.MIDTERM, 8.5, date(2025, 11, 15)),
            (4, 1, ScoreSource.CENTER, ScoreType.CONTINUOUS, 8.0, date(2025, 10, 12)),
            (4, 2, ScoreSource.CENTER, ScoreType.MIDTERM, 9.0, date(2025, 11, 20)),
            (8, 0, ScoreSource.CENTER, ScoreType.QUIZ_15, 10.0, date(2025, 10, 8)),
            (9, 3, ScoreSource.CENTER, ScoreType.MIDTERM, 9.0, date(2025, 11, 18)),
        ]
        for si, ci, src, stype, val, edate in score_samples:
            sc = Score(
                student_id=students[si].id,
                class_id=classes[ci][0].id,
                score_source=src,
                score_type=stype,
                score_value=val,
                exam_date=edate,
                school_name='Secondary Le Van Tam' if src == ScoreSource.SCHOOL else None,
                entered_by=admin.id,
            )
            db.session.add(sc)

        # ── Sample rewards (approved)
        reward_samples = [
            (2, 'Score 10/10 Continuous (Math 8A)', 20000, date(2025, 10, 6)),
            (2, 'Score 9.5/10 Midterm (Math 8A)', 150000, date(2025, 11, 11)),
            (0, 'Score 9.0/10 Midterm (Math 8A)', 150000, date(2025, 11, 11)),
            (8, 'Score 10/10 Quiz 15min (Math 8A)', 50000, date(2025, 10, 9)),
        ]
        for si, reason, amt, rdate in reward_samples:
            r = Reward(
                student_id=students[si].id,
                reason=reason,
                amount=amt,
                reward_type='cash',
                reward_date=rdate,
                is_suggested=True,
                is_confirmed=True,
                created_by=admin.id,
                confirmed_by=admin.id,
                confirmed_at=datetime.combine(rdate, time(10, 0))
            )
            db.session.add(r)

        # ── Sample tuition payments
        current_month = today.month
        current_year = today.year
        prev_month = 12 if current_month == 1 else current_month - 1
        prev_year = current_year - 1 if current_month == 1 else current_year

        tuition_samples = [
            # (student_index, class_index, amount, month, year, is_paid, method)
            # Previous month payments
            (0, 0, 800000, prev_month, prev_year, True, TuitionMethod.CASH),
            (1, 0, 800000, prev_month, prev_year, True, TuitionMethod.TRANSFER),
            (2, 0, 800000, prev_month, prev_year, True, TuitionMethod.CASH),
            (3, 1, 900000, prev_month, prev_year, True, TuitionMethod.TRANSFER),
            # Current month - mixed paid/unpaid
            (0, 0, 800000, current_month, current_year, True, TuitionMethod.CASH),
            (1, 0, 800000, current_month, current_year, False, None),
            (2, 0, 800000, current_month, current_year, False, None),
            (3, 1, 900000, current_month, current_year, True, TuitionMethod.TRANSFER),
            (4, 1, 900000, current_month, current_year, False, None),
            (6, 4, 600000, current_month, current_year, True, TuitionMethod.CASH),
            (7, 4, 600000, current_month, current_year, False, None),
        ]
        for si, ci, amt, month, year, is_paid, method in tuition_samples:
            tp = TuitionPayment(
                student_id=students[si].id,
                class_id=classes[ci][0].id,
                amount=amt,
                month=month,
                year=year,
                is_paid=is_paid,
                method=method or TuitionMethod.CASH,
                paid_at=datetime.combine(today.replace(day=5), time(10, 0)) if is_paid else None,
                received_by=admin.id if is_paid else None,
            )
            db.session.add(tp)

        db.session.commit()
        print("✓ Sample data seeded successfully!")
        print("\n--- SAMPLE ACCOUNTS ---")
        print("Admin:  admin / admin123")
        print("Teacher: phuonglinh / teacher123")
        print("Parent: parent01 / parent123")
        print("-" * 40)


if __name__ == '__main__':
    seed()
