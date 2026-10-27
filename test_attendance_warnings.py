"""Attendance warnings use only synthetic, in-memory records."""
from datetime import date, datetime, time, timedelta
import unittest

from flask import g

from app import create_app
from config import Config, config
from extensions import db
from models import Attendance, Class, Course, Enrollment, LeaveRequest, LeaveRequestStatus, Schedule, Student, Teacher, User
from services.attendance_warnings import get_absence_warnings


class WarningConfig(Config):
    TESTING = True
    SECRET_KEY = 'synthetic-attendance-warning'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    ACADEMIC_ROLLOVER_ENABLED = False


class AttendanceWarningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config['attendance_warning_test'] = WarningConfig
        cls.app = create_app('attendance_warning_test')

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.engine.dispose()
        config.pop('attendance_warning_test')

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        user = User(username='teacher', full_name='Teacher', role='teacher', password_hash='test')
        self.teacher = Teacher(user=user)
        course = Course(name='Synthetic course')
        self.class_ = Class(name='Synthetic class', course=course, sessions_per_week=2,
                            primary_teacher=self.teacher)
        self.student = Student(full_name='Synthetic student', level='secondary')
        self.start = date(2026, 1, 1)
        self.enrollment = Enrollment(class_=self.class_, student=self.student,
                                     enrolled_at=datetime.combine(self.start, time(10)))
        db.session.add_all([self.teacher, self.class_, self.enrollment])
        db.session.commit()
        self.client = self.app.test_client()
        self.login(user)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def login(self, user):
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user.id)
            session['_fresh'] = True
            session['active_role'] = 'teacher'

    def session(self, offset, status='present', **kwargs):
        schedule = Schedule(class_=self.class_, teacher=self.teacher,
                            date=self.start + timedelta(days=offset),
                            start_time=time(17), end_time=time(18), **kwargs)
        db.session.add(schedule)
        db.session.flush()
        if status:
            db.session.add(Attendance(schedule=schedule, student=self.student, status=status))
        db.session.commit()
        return schedule

    def warnings(self, as_of=date(2026, 1, 31)):
        return get_absence_warnings([self.class_.id], as_of=as_of)

    def test_exact_threshold_excused_and_late(self):
        self.session(0, 'absent')
        self.session(3, 'excused')
        self.session(6, 'late')
        for offset in (9, 12, 15, 18, 21):
            self.session(offset, None)
        self.assertEqual(self.warnings(), [])
        schedule = Schedule.query.filter_by(date=self.start + timedelta(days=9)).one()
        db.session.add(Attendance(schedule=schedule, student=self.student, status='absent'))
        db.session.commit()
        warning, = self.warnings()
        self.assertEqual(warning['absence_count'], 3)
        self.assertEqual(warning['monthly_sessions'], 8)
        self.assertEqual(warning['completed_sessions'], 4)
        self.assertEqual(warning['start_date'], '01/01/2026')
        self.assertEqual(warning['end_date'], '31/01/2026')

    def test_calendar_month_resets_not_session_count(self):
        for offset in range(8):
            self.session(offset, 'absent' if offset < 3 else 'present')
        warning, = self.warnings()
        self.assertEqual((warning['completed_sessions'], warning['month_label']), (8, '01/2026'))
        self.session(8, 'absent')
        warning, = self.warnings()
        self.assertEqual((warning['absence_count'], warning['monthly_sessions']), (4, 9))
        self.assertEqual(self.warnings(date(2026, 2, 1)), [])
        self.session(31, 'excused')
        warning, = self.warnings(date(2026, 2, 1))
        self.assertEqual((warning['absence_count'], warning['month_label']), (1, '02/2026'))

    def test_twelve_sessions_require_more_than_three_absences(self):
        self.class_.sessions_per_week = 3
        for offset in range(12):
            self.session(offset, 'absent' if offset in (0, 7, 8) else 'present')
        self.assertEqual(self.warnings(), [])
        Attendance.query.join(Schedule).filter(Schedule.date == self.start + timedelta(days=9)).one().status = 'absent'
        db.session.commit()
        warning, = self.warnings()
        self.assertEqual(warning['monthly_sessions'], 12)
        self.assertEqual(warning['absence_count'], 4)

    def test_personal_start_excludes_sessions_before_joining(self):
        for offset in range(12):
            self.session(offset, 'absent' if offset < 3 else 'present')
        other = Student(full_name='Later joiner', level='secondary')
        db.session.add(Enrollment(class_=self.class_, student=other,
                                  enrolled_at=datetime.combine(self.start + timedelta(days=8), time())))
        db.session.flush()
        for schedule in self.class_.schedules.filter(Schedule.date >= self.start + timedelta(days=8)):
            db.session.add(Attendance(schedule=schedule, student=other, status='absent'))
        db.session.commit()
        warning, = self.warnings()
        self.assertEqual(warning['student_id'], other.id)
        self.assertEqual((warning['completed_sessions'], warning['monthly_sessions']), (4, 12))

    def test_cancelled_unmarked_and_future_excluded_intensive_counted(self):
        for offset in range(3):
            self.session(offset, 'absent', is_cancelled=True)
        self.session(3, None)
        self.session(4, 'absent', schedule_type='intensive')
        self.session(5, 'excused')
        self.session(6, 'absent')
        self.session(50, 'absent')
        warning, = self.warnings()
        self.assertEqual((warning['absence_count'], warning['completed_sessions']), (3, 3))
        self.assertEqual(warning['monthly_sessions'], 4)

    def test_future_and_unmarked_sessions_in_month_in_denominator_only(self):
        for offset in range(12):
            self.session(offset, 'absent' if offset < 3 else None)
        self.assertEqual(self.warnings(self.start + timedelta(days=2)), [])
        Schedule.query.filter_by(date=self.start + timedelta(days=11)).one().is_cancelled = True
        db.session.commit()
        warning, = self.warnings(self.start + timedelta(days=2))
        self.assertEqual((warning['absence_count'], warning['monthly_sessions']), (3, 11))

    def test_month_end_handles_february_and_leap_year(self):
        for year, last_day in ((2024, 29), (2026, 28)):
            self.start = date(year, 2, last_day)
            self.enrollment.enrolled_at = datetime(year, 2, 1)
            self.session(0, 'absent')
            warning, = self.warnings(self.start)
            self.assertEqual(warning['end_date'], f'{last_day}/02/{year}')
            self.assertEqual(self.warnings(date(year, 3, 1)), [])

    def test_thirty_day_month_and_year_boundary(self):
        for last_date, next_date in (
            (date(2025, 11, 30), date(2025, 12, 1)),
            (date(2025, 12, 31), date(2026, 1, 1)),
        ):
            self.start = last_date
            self.enrollment.enrolled_at = datetime.combine(last_date.replace(day=1), time())
            self.session(0, 'absent')
            warning, = self.warnings(last_date)
            self.assertEqual(warning['end_date'], last_date.strftime('%d/%m/%Y'))
            self.assertEqual(self.warnings(next_date), [])

    def test_approved_leave_counts_once_only_on_completed_sessions(self):
        for offset in range(3):
            self.session(offset, 'excused')
        self.session(3, None)
        self.session(4, 'present')
        for status in (LeaveRequestStatus.APPROVED, LeaveRequestStatus.APPROVED,
                       LeaveRequestStatus.PENDING, LeaveRequestStatus.REJECTED):
            db.session.add(LeaveRequest(student=self.student, start_date=self.start,
                                        end_date=self.start + timedelta(days=3), status=status))
        db.session.commit()
        warning, = self.warnings()
        self.assertEqual((warning['absence_count'], warning['completed_sessions']), (3, 4))

    def test_correction_removes_warning_and_inactive_records_excluded(self):
        for offset in range(3):
            self.session(offset, 'absent')
        for offset in range(3, 8):
            self.session(offset, None)
        self.assertEqual(len(self.warnings()), 1)
        attendance = Attendance.query.first()
        attendance.status = 'late'
        db.session.commit()
        self.assertEqual(self.warnings(), [])
        attendance.status = 'absent'
        self.student.is_deleted = True
        db.session.commit()
        self.assertEqual(self.warnings(), [])
        self.student.is_deleted = False
        self.enrollment.is_active = False
        db.session.commit()
        self.assertEqual(self.warnings(), [])

    def test_completed_class_session_counts_leave_without_personal_record(self):
        helper = Student(full_name='Other student', level='secondary')
        db.session.add(helper)
        for offset in range(3):
            schedule = self.session(offset, None)
            db.session.add(Attendance(schedule=schedule, student=helper, status='present'))
        db.session.add(LeaveRequest(student=self.student, start_date=self.start,
                                    end_date=self.start + timedelta(days=2),
                                    status=LeaveRequestStatus.APPROVED))
        db.session.commit()
        warning, = self.warnings()
        self.assertEqual((warning['absence_count'], warning['completed_sessions']), (3, 3))

    def test_absences_do_not_combine_between_classes(self):
        for offset in range(8):
            self.session(offset, 'absent' if offset < 2 else 'present')
        other = Class(name='Other class', course=self.class_.course, sessions_per_week=3,
                      primary_teacher=self.teacher)
        db.session.add(Enrollment(class_=other, student=self.student,
                                  enrolled_at=datetime.combine(self.start, time())))
        db.session.flush()
        for offset in range(8):
            schedule = Schedule(class_=other, date=self.start + timedelta(days=offset),
                                start_time=time(10), end_time=time(11))
            db.session.add(Attendance(schedule=schedule, student=self.student,
                                      status='absent' if offset < 2 else 'present'))
        db.session.commit()
        self.assertEqual(get_absence_warnings([self.class_.id, other.id], as_of=date(2026, 1, 31)), [])

    def test_warning_only_on_student_detail_and_updates_after_save(self):
        self.start = date.today()
        self.enrollment.enrolled_at = datetime.combine(self.start, time())
        self.session(0, 'absent')
        self.session(0, 'excused')
        current = self.session(0, None)
        for offset in range(3, 8):
            self.session(0, None)
        detail_path = f'/teacher/students/{self.student.id}'
        self.assertNotIn('Cảnh báo học sinh nghỉ học', self.client.get(detail_path).get_data(as_text=True))
        paths = ('/teacher/', '/teacher/attendance', f'/teacher/attendance/{current.id}',
                 '/teacher/students', f'/teacher/students/class/{self.class_.id}')
        for path in paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('Cảnh báo học sinh nghỉ học', response.get_data(as_text=True))
        response = self.client.post(f'/teacher/api/attendance/{current.id}/save',
                                    json={'attendance': [{'student_id': self.student.id, 'status': 'absent'}]})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('absence_warnings', response.json)
        self.assertIn('nghỉ 3/8 buổi', self.client.get(detail_path).get_data(as_text=True))
        for path in paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('Cảnh báo học sinh nghỉ học', response.get_data(as_text=True))
        response = self.client.post(f'/teacher/api/attendance/{current.id}/save',
                                    json={'attendance': [{'student_id': self.student.id, 'status': 'late'}]})
        self.assertTrue(response.json['success'])
        self.assertNotIn('Cảnh báo học sinh nghỉ học', self.client.get(detail_path).get_data(as_text=True))
        html = self.client.get('/teacher/attendance').get_data(as_text=True)
        self.assertIn(f'data-student="{self.student.id}" data-status="late"', html)

    def test_other_teacher_cannot_see_class_warning(self):
        self.start = date.today()
        self.enrollment.enrolled_at = datetime.combine(self.start, time())
        for offset in range(3):
            current = self.session(0, 'absent')
        outsider = User(username='outsider', full_name='Other teacher', role='teacher', password_hash='test')
        db.session.add(Teacher(user=outsider))
        db.session.commit()
        self.login(outsider)
        for path in ('/teacher/', '/teacher/attendance'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('nghỉ 3/3 buổi'.encode(), response.data)
        self.assertEqual(self.client.get(f'/teacher/attendance/{current.id}').status_code, 403)
        self.class_.assistant_teachers.append(outsider.teacher_profile)
        db.session.commit()
        self.assertIn('nghỉ 3/3 buổi'.encode(), self.client.get(f'/teacher/students/{self.student.id}').data)
        self.assertNotIn('Cảnh báo học sinh nghỉ học', self.client.get('/teacher/').get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
