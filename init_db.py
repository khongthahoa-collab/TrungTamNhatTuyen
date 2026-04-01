"""
Initialize database and seed sample data for Nhat Tuyen tutoring center.
Run: python init_db.py
"""
from app import create_app
from extensions import db
from models import (
    User, Teacher, Course, Class, Student, Enrollment,
    AcademicYear, Semester, Schedule, SystemConfig,
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
            ('center_name', 'Nhat Tuyen Tutoring Center', 'Center name'),
            ('center_address', '159 Le Hong Phong, Kon Tum Ward, Quang Ngai', 'Center address'),
            ('center_phone', '0901901891', 'Center phone number'),
            ('zalo_link', 'https://zalo.me/0901901891', 'Zalo chat link'),
            ('messenger_link', 'https://m.me/nhattuyenedu', 'Messenger link'),
            ('bank_account', '1234567890 - Vietcombank - Nguyen Trinh Thu Phuong', 'Bank account'),
            ('hall_of_fame_min_score', '8', 'Minimum score for hall of fame'),
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

        # ── Teachers
        teacher_data = [
            # (full_name, username, phone, specialty, is_staff, base_salary)
            ('Tran Van An', 'gvtoan', '0912345678', 'Mathematics', True, 8000000),
            ('Le Thi Binh', 'gvly', '0923456789', 'Physics', True, 7000000),
            ('Pham Quoc Cuong', 'gvhoa', '0934567890', 'Chemistry', True, 7500000),
            ('Nguyen Minh Dung', 'gvvan', '0945678901', 'Literature', False, 0),  # Part-time
        ]
        teachers = []
        for fname, uname, phone, spec, is_staff, salary in teacher_data:
            u = User(
                full_name=fname,
                username=uname,
                phone=phone,
                role=UserRole.TEACHER
            )
            u.set_password('teacher123')
            db.session.add(u)
            db.session.flush()
            t = Teacher(
                user_id=u.id,
                specialty=spec,
                is_staff=is_staff,
                base_salary=salary
            )
            db.session.add(t)
            db.session.flush()
            teachers.append(t)

        # ── Courses
        course_data = [
            # (name, level)
            ('Mathematics', StudentLevel.SECONDARY),
            ('Mathematics', StudentLevel.HIGH_SCHOOL),
            ('Physics', StudentLevel.SECONDARY),
            ('Physics', StudentLevel.HIGH_SCHOOL),
            ('Chemistry', StudentLevel.SECONDARY),
            ('Chemistry', StudentLevel.HIGH_SCHOOL),
            ('Literature', StudentLevel.SECONDARY),
            ('Mathematics', StudentLevel.PRIMARY),
        ]
        courses = {}
        for cname, level in course_data:
            c = Course(name=cname, level=level)
            db.session.add(c)
            db.session.flush()
            courses[f'{cname}_{level}'] = c

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
            name='Summer 2025',
            semester_type=SemesterType.SUMMER,
            start_date=date(2025, 6, 1),
            end_date=date(2025, 8, 31)
        )
        sem_1 = Semester(
            academic_year_id=ay.id,
            name='Semester 1 (2025-2026)',
            semester_type=SemesterType.SEMESTER_1,
            start_date=date(2025, 9, 1),
            end_date=date(2026, 1, 31)
        )
        sem_2 = Semester(
            academic_year_id=ay.id,
            name='Semester 2 (2025-2026)',
            semester_type=SemesterType.SEMESTER_2,
            start_date=date(2026, 2, 1),
            end_date=date(2026, 5, 31)
        )
        db.session.add_all([sem_summer, sem_1, sem_2])
        db.session.flush()

        # ── Classes
        class_data = [
            # (name, course, grade_level, teacher, max_students)
            ('Math 8A', courses['Mathematics_secondary'], 'Class 8', teachers[0], 15),
            ('Math 10B', courses['Mathematics_high_school'], 'Class 10', teachers[0], 15),
            ('Physics 10A', courses['Physics_high_school'], 'Class 10', teachers[1], 12),
            ('Chemistry 9A', courses['Chemistry_secondary'], 'Class 9', teachers[2], 12),
            ('Math Primary 4', courses['Mathematics_primary'], 'Class 4', teachers[0], 10),
        ]
        classes = []
        for cname, course, grade, teacher, max_s in class_data:
            cl = Class(
                name=cname,
                course_id=course.id,
                grade_level=grade,
                max_students=max_s,
                start_date=date(2025, 9, 1),
                end_date=date(2026, 5, 31)
            )
            db.session.add(cl)
            db.session.flush()
            classes.append((cl, teacher))

        # ── Students
        students_data = [
            # (full_name, dob, gender, current_school, current_grade, level, parent_name, parent_phone)
            ('Nguyen Van Anh', date(2010, 3, 15), 'male', 'Secondary Le Van Tam', '8A', StudentLevel.SECONDARY, 'Nguyen Van Binh', '0901111111'),
            ('Tran Thi Bao', date(2010, 7, 22), 'female', 'Secondary Le Van Tam', '8A', StudentLevel.SECONDARY, 'Tran Van Cuong', '0902222222'),
            ('Le Minh Chien', date(2009, 11, 5), 'male', 'Secondary Nguyen Du', '9B', StudentLevel.SECONDARY, 'Le Thi Dung', '0903333333'),
            ('Pham Thi Dieu', date(2008, 5, 18), 'female', 'HS Nguyen Trai', '10A', StudentLevel.HIGH_SCHOOL, 'Pham Van Em', '0904444444'),
            ('Hoang Van Em', date(2008, 9, 30), 'male', 'HS Nguyen Trai', '10B', StudentLevel.HIGH_SCHOOL, 'Hoang Thi Phuong', '0905555555'),
            ('Vo Thi Phuong', date(2007, 1, 12), 'female', 'HS Tran Phu', '11C', StudentLevel.HIGH_SCHOOL, 'Vo Van Giang', '0906666666'),
            ('Dang Quoc Hung', date(2014, 6, 8), 'male', 'Primary Le Loi', '4A', StudentLevel.PRIMARY, 'Dang Van Hai', '0907777777'),
            ('Bui Thi Lan', date(2014, 2, 25), 'female', 'Primary Le Loi', '4B', StudentLevel.PRIMARY, 'Bui Van Kien', '0908888888'),
            ('Ngo Van Manh', date(2010, 8, 14), 'male', 'Secondary Le Van Tam', '8B', StudentLevel.SECONDARY, 'Ngo Thi Ngoc', '0909999999'),
            ('Dinh Thi Ngoc', date(2009, 4, 3), 'female', 'Secondary Nguyen Du', '9A', StudentLevel.SECONDARY, 'Dinh Van Phuc', '0910101010'),
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
            fname, dob, gender, school, grade, level, pname, pphone = sdata
            pu = parent_users.get(pphone)
            s = Student(
                full_name=fname,
                date_of_birth=dob,
                gender=gender,
                current_school=school,
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
        print("Teacher: gvtoan / teacher123")
        print("Parent: parent01 / parent123")
        print("-" * 40)


if __name__ == '__main__':
    seed()
