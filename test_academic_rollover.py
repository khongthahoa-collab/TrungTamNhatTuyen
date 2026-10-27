"""Isolated year-transition checks; no production database is used."""
from datetime import date, time
import json
import unittest
from unittest.mock import patch

from flask import g
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import psycopg

from app import create_app
from config import Config, config
from extensions import db
from models import (
    AcademicRollover, AcademicYear, Attendance, Class, Course, Enrollment, Exam,
    ExamAttempt, Homework, PermissionGroup, Schedule, Student, Teacher, TuitionPayment, User,
)
from services.academic_rollover import build_rollover_plan, execute_rollover, RolloverError


class RolloverConfig(Config):
    ACADEMIC_ROLLOVER_ENABLED = True
    TESTING = True
    SECRET_KEY = 'rollover-test'
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


class AcademicRolloverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config['rollover_test'] = RolloverConfig
        cls.app = create_app('rollover_test')

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.engine.dispose()
        config.pop('rollover_test', None)

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.admin = User(username='admin', role='admin', is_master=True, password_hash='test')
        self.teacher_user = User(username='teacher', role='teacher', password_hash='test')
        self.assistant_user = User(username='assistant', role='teacher', password_hash='test')
        self.student_user = User(username='student', role='student', password_hash='test')
        db.session.add_all([self.admin, self.teacher_user, self.assistant_user, self.student_user])
        db.session.flush()
        self.teacher = Teacher(user_id=self.teacher_user.id)
        self.assistant = Teacher(user_id=self.assistant_user.id)
        self.course = Course(name='Hoá')
        self.year = AcademicYear(name='2026-2027', start_date=date(2026, 7, 1),
                                 end_date=date(2027, 6, 30))
        db.session.add_all([self.teacher, self.assistant, self.course, self.year])
        db.session.flush()
        self.cls = Class(
            name='Hoá 10 - Cô A - nhóm 2', grade_level='Lớp 10', course_id=self.course.id,
            primary_teacher_id=self.teacher.id, monthly_fee=500000, sessions_per_week=3,
            max_students=25, description='Keep', zalo_group_id='group', start_date=self.year.start_date,
            end_date=self.year.end_date,
        )
        self.cls.assistant_teachers = [self.assistant]
        self.student = Student(full_name='Student', level='high_school', current_grade='Lớp 10',
                               grade_year=2026, user_id=self.student_user.id, note='Keep student')
        db.session.add_all([self.cls, self.student])
        db.session.flush()
        self.enrollment = Enrollment(class_id=self.cls.id, student_id=self.student.id,
                                     discount_pct=15, note='Keep enrollment')
        db.session.add(self.enrollment)
        for day in (21, 23, 25):  # Monday/Wednesday/Friday.
            db.session.add(Schedule(
                class_id=self.cls.id, date=date(2027, 6, day), start_time=time(17), end_time=time(18),
                teacher_id=self.assistant.id if day == 23 else self.teacher.id, room='A',
            ))
        db.session.flush()
        self.history = [
            Attendance(schedule_id=Schedule.query.first().id, student_id=self.student.id, status='present'),
            Homework(class_id=self.cls.id, title='Old homework', assigned_date=date(2027, 6, 21)),
            TuitionPayment(class_id=self.cls.id, student_id=self.student.id, month=6, year=2027,
                           amount=500000, amount_collected=100000, debt_carried_over=30000),
            Exam(title='Hoá 10 đề cũ', subject='Hoá', content_grade='Lớp 10',
                 created_by=self.teacher_user.id, class_ids=str(self.cls.id), is_draft=False,
                 questions_json='{"groups": []}'),
        ]
        db.session.add_all(self.history)
        db.session.commit()
        self.client = self.app.test_client()
        self.login(self.admin)
        self.clock = patch('services.academic_rollover.date', wraps=date)
        self.mock_date = self.clock.start()
        self.mock_date.today.return_value = date(2027, 7, 1)
        self.window = patch('blueprints.admin.academic._rollover_window_open', return_value=True)
        self.window.start()

    def tearDown(self):
        self.window.stop()
        self.clock.stop()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def login(self, user):
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session.clear()
            session['_user_id'] = str(user.id)
            session['_fresh'] = True

    def queue(self):
        plan = build_rollover_plan()
        self.assertEqual(plan['errors'], [])
        response = self.client.post('/admin/academic-years/rollover', data={'fingerprint': plan['fingerprint']})
        self.assertEqual(response.status_code, 302)
        return AcademicRollover.query.filter_by(target_year=plan['next_year']).one()

    def run_worker(self):
        return self.app.test_cli_runner().invoke(args=['process-academic-rollovers'])

    @staticmethod
    def snapshot(row):
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    def test_worker_preserves_history_roster_settings_and_weekly_schedule(self):
        from models import Score, HomeworkRecord, ClassDocument
        db.session.add_all([
            Score(class_id=self.cls.id, student_id=self.student.id, score_type='midterm', score_value=8,
                  exam_date=date(2027, 6, 21)),
            HomeworkRecord(homework_id=self.history[1].id, student_id=self.student.id, status='done'),
            ClassDocument(class_id=self.cls.id, uploaded_by=self.teacher_user.id,
                          title='Old document', stored_filename='old.pdf'),
        ])
        attempt = ExamAttempt(exam_id=self.history[3].id, user_id=self.student_user.id,
                              student_id=self.student.id, status='submitted', score=8,
                              answers_json='{"old":"keep"}')
        db.session.add(attempt)
        db.session.commit()
        extra_history = [*Score.query.all(), *HomeworkRecord.query.all(), *ClassDocument.query.all(), attempt]
        extra_before = [self.snapshot(row) for row in extra_history]
        schedules_before = [self.snapshot(row) for row in Schedule.query.all()]
        histories = [self.snapshot(row) for row in self.history]
        enrollment_before = self.snapshot(self.enrollment)
        old_class = self.snapshot(self.cls)
        job = self.queue()
        self.assertEqual(Class.query.count(), 1, 'web request must only queue work')
        self.assertEqual(self.student.current_grade, 'Lớp 10')
        self.assertEqual(self.client.get(f'/admin/academic-rollovers/{job.id}').status_code, 200)
        result = self.run_worker()
        self.assertEqual(result.exit_code, 0, result.output)
        db.session.expire_all()
        new = Class.query.filter_by(rolled_over_from_id=self.cls.id).one()
        self.assertEqual(new.name, 'Hoá 11 - Cô A - nhóm 2')
        self.assertEqual(new.grade_level, 'Lớp 11')
        for field in ('monthly_fee', 'sessions_per_week', 'max_students', 'description',
                      'primary_teacher_id', 'zalo_group_id', 'course_id'):
            self.assertEqual(getattr(new, field), old_class[field])
        self.assertEqual([t.id for t in new.assistant_teachers], [self.assistant.id])
        new_enrollment = new.enrollments.one()
        self.assertEqual(new_enrollment.student_id, self.student.id)
        self.assertEqual(new_enrollment.discount_pct, 15)
        self.assertEqual(new_enrollment.note, 'Keep enrollment')
        self.assertEqual(self.snapshot(self.enrollment), enrollment_before)
        expected_old = {**old_class, 'is_active': False}
        self.assertEqual(self.snapshot(self.cls), expected_old)
        self.assertEqual([self.snapshot(row) for row in self.history], histories)
        self.assertEqual([self.snapshot(row) for row in extra_history], extra_before)
        self.assertEqual([self.snapshot(row) for row in Schedule.query.filter_by(class_id=self.cls.id)], schedules_before)
        new_rows = new.schedules.all()
        self.assertEqual(len(new_rows), 157)  # The target school year includes 29/02/2028.
        self.assertEqual({row.date.weekday() for row in new_rows}, {0, 2, 4})
        for row in new_rows:
            self.assertGreaterEqual(row.date, date(2027, 7, 1))
            self.assertLessEqual(row.date, date(2028, 6, 30))
            self.assertEqual((row.start_time, row.end_time, row.room), (time(17), time(18), 'A'))
            self.assertEqual(row.teacher_id, self.assistant.id if row.date.weekday() == 2 else self.teacher.id)
        self.assertEqual(self.student.current_grade, 'Lớp 11')
        self.assertEqual(self.student.grade_year, 2027)
        self.assertEqual(self.student.note, 'Keep student')
        self.assertTrue(self.student_user.is_active)
        self.assertFalse(self.year.is_active)
        self.assertEqual(AcademicYear.query.filter_by(is_active=True).one().start_date, date(2027, 7, 1))
        self.assertEqual(job.status, 'succeeded')
        self.assertEqual(self.run_worker().exit_code, 0)
        self.assertEqual(Class.query.count(), 2)
        self.login(self.student_user)
        html = self.client.get('/student/exams').get_data(as_text=True)
        self.assertIn(self.history[3].title, html)
        self.assertIn('Lịch sử bài đã nộp', html)
        self.assertEqual(self.client.get(f'/student/exams/{self.history[3].id}/result').status_code, 200)
        self.assertEqual(self.client.get(f'/student/exams/{self.history[3].id}').status_code, 404)

    def test_preview_and_worker_reject_stale_data(self):
        plan = build_rollover_plan()
        self.student.note = 'Changed after preview'
        db.session.commit()
        response = self.client.post('/admin/academic-years/rollover', data={'fingerprint': plan['fingerprint']})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AcademicRollover.query.count(), 0)
        job = self.queue()
        self.enrollment.discount_pct = 20
        db.session.commit()
        with self.assertLogs(self.app.logger, level='ERROR'):
            result = self.run_worker()
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(job.status, 'failed')
        self.assertEqual(Class.query.count(), 1)
        self.assertEqual(Schedule.query.count(), 3)
        self.assertEqual(self.student.current_grade, 'Lớp 10')
        retry = self.queue()
        self.assertEqual(retry.id, job.id)
        self.assertEqual(self.run_worker().exit_code, 0)
        self.assertEqual(Class.query.filter_by(rolled_over_from_id=self.cls.id).one().enrollments.one().discount_pct, 20)

    def test_failure_after_writes_rolls_back_everything(self):
        job = self.queue()
        real_execute = execute_rollover

        def fail_after_writes(job):
            real_execute(job)
            db.session.flush()
            raise RuntimeError('Synthetic failure')

        with patch('services.academic_rollover.execute_rollover', side_effect=fail_after_writes):
            with self.assertLogs(self.app.logger, level='ERROR'):
                result = self.run_worker()
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(job.status, 'failed')
        self.assertEqual(Class.query.count(), 1)
        self.assertEqual(AcademicYear.query.count(), 1)
        self.assertEqual(Enrollment.query.count(), 1)
        self.assertEqual(Schedule.query.count(), 3)
        self.assertTrue(self.cls.is_active)
        self.assertTrue(self.year.is_active)
        self.assertEqual(self.student.current_grade, 'Lớp 10')

    def test_missing_stale_future_or_unknown_grade_blocks_without_writes(self):
        for year in (None, 2024, 2027):
            self.student.grade_year = year
            db.session.commit()
            self.assertTrue(build_rollover_plan()['errors'])
            self.client.post('/admin/academic-years/rollover', data={'fingerprint': build_rollover_plan()['fingerprint']})
            self.assertEqual(AcademicRollover.query.count(), 0)
        self.student.grade_year = 2026
        self.student.current_grade = 'Unknown'
        db.session.commit()
        self.assertTrue(build_rollover_plan()['errors'])
        self.assertEqual(Class.query.count(), 1)

    def test_pre_july_and_missing_or_multiple_active_years_block(self):
        self.assertTrue(build_rollover_plan(date(2027, 6, 30))['errors'])
        self.year.is_active = False
        db.session.commit()
        with self.assertRaises(RolloverError):
            build_rollover_plan()
        self.year.is_active = True
        db.session.add(AcademicYear(name='Other', start_date=date(2027, 7, 1), end_date=date(2028, 6, 30)))
        db.session.commit()
        with self.assertRaises(RolloverError):
            build_rollover_plan()

    def test_graduation_and_pending_students(self):
        self.student.current_grade = 'Lớp 12'
        self.cls.grade_level = 'Lớp 12'
        db.session.add(Student(full_name='Pending', current_grade='Lớp 4', level='primary',
                               status='pending_confirmation', grade_year=None))
        db.session.commit()
        self.queue()
        self.assertEqual(self.run_worker().exit_code, 0)
        self.assertFalse(self.student.is_active)
        self.assertEqual(self.student.status, 'graduated')
        self.assertFalse(self.student_user.is_active)
        self.assertFalse(self.cls.is_active)
        self.assertEqual(Class.query.count(), 1)
        self.assertEqual(Enrollment.query.count(), 1)
        self.assertEqual(Student.query.filter_by(full_name='Pending').one().current_grade, 'Lớp 4')

    def test_multislot_latest_schedule_ignores_makeup_cancelled_and_future(self):
        db.session.add_all([
            Schedule(class_id=self.cls.id, date=date(2027, 6, 21), start_time=time(19), end_time=time(20), teacher_id=self.teacher.id),
            Schedule(class_id=self.cls.id, date=date(2027, 6, 28), start_time=time(10), end_time=time(11), teacher_id=self.teacher.id, schedule_type='makeup'),
            Schedule(class_id=self.cls.id, date=date(2027, 6, 28), start_time=time(11), end_time=time(12), teacher_id=self.teacher.id, is_cancelled=True),
        ])
        db.session.commit()
        plan = build_rollover_plan()
        self.assertEqual(plan['errors'], [])
        monday = [slot for slot in plan['rolling'][0]['slots'] if slot['weekday'] == 0]
        self.assertEqual({slot['start_time'] for slot in monday}, {time(17), time(19)})

    def test_existing_teacher_room_and_student_conflicts_block(self):
        db.session.add(Schedule(class_id=self.cls.id, date=date(2027, 7, 2),
                                start_time=time(17, 30), end_time=time(18, 30),
                                teacher_id=self.teacher.id, room='A'))
        db.session.commit()
        plan = build_rollover_plan()
        self.assertTrue(any('teacher' in error for error in plan['errors']))
        self.assertTrue(any('room_text' in error for error in plan['errors']))
        self.assertTrue(any('student' in error for error in plan['errors']))
        self.assertEqual(AcademicRollover.query.count(), 0)

    def test_schedule_before_source_year_is_not_inherited(self):
        db.session.add(Schedule(
            class_id=self.cls.id, date=date(2026, 6, 30),
            start_time=time(10), end_time=time(11), teacher_id=self.teacher.id,
        ))
        db.session.commit()
        plan = build_rollover_plan()
        self.assertEqual(plan['errors'], [])
        self.assertEqual({slot['weekday'] for slot in plan['rolling'][0]['slots']}, {0, 2, 4})
        Schedule.query.filter(Schedule.date >= self.year.start_date).delete()
        db.session.commit()
        plan = build_rollover_plan()
        self.assertTrue(any('không có lịch thường kỳ' in error for error in plan['errors']))
        self.assertEqual(plan['schedules'], [])
        self.assertEqual(self.student.current_grade, 'Lớp 10')

    def test_inactive_management_teacher_blocks_even_without_teaching_slots(self):
        Schedule.query.update({'teacher_id': self.teacher.id})
        self.assistant_user.is_active = False
        db.session.commit()
        plan = build_rollover_plan()
        self.assertTrue(any('trợ giảng' in error for error in plan['errors']))
        self.assistant_user.is_active = True
        self.cls.primary_teacher_id = self.assistant.id
        self.cls.assistant_teachers = []
        self.assistant_user.is_deleted = True
        db.session.commit()
        plan = build_rollover_plan()
        self.assertTrue(any('giáo viên quản lý' in error for error in plan['errors']))
        response = self.client.post('/admin/academic-years/rollover', data={'fingerprint': plan['fingerprint']})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AcademicRollover.query.count(), 0)
        self.assertTrue(self.cls.is_active)

    def test_custom_names_free_grade_and_empty_schedule_block(self):
        self.cls.name = 'Special 10 group'
        db.session.commit()
        self.assertTrue(build_rollover_plan()['errors'])
        self.cls.name = 'Hoá 10 - Cô A - nhóm 2'
        self.cls.grade_level = 'Other'
        db.session.commit()
        self.assertTrue(build_rollover_plan()['errors'])
        self.cls.grade_level = 'Lớp 10'
        Schedule.query.update({'is_cancelled': True})
        db.session.commit()
        self.assertTrue(build_rollover_plan()['errors'])

    def test_queue_repeated_post_permissions_and_preview(self):
        self.assertEqual(self.client.get('/admin/academic-years/rollover').status_code, 200)
        plan = build_rollover_plan()
        job = self.queue()
        self.client.post('/admin/academic-years/rollover', data={'fingerprint': plan['fingerprint']})
        self.assertEqual(AcademicRollover.query.count(), 1)
        group = PermissionGroup(name='read only', permissions='{"academic":"read"}')
        reader = User(username='reader', role='admin', password_hash='test', permission_group=group)
        db.session.add(reader)
        db.session.commit()
        self.login(reader)
        self.assertEqual(self.client.get('/admin/academic-years/rollover').status_code, 302)
        self.assertEqual(self.client.post('/admin/academic-years/rollover').status_code, 403)
        self.login(self.teacher_user)
        self.assertEqual(self.client.get(f'/admin/academic-rollovers/{job.id}').status_code, 403)
        sql = str(select(AcademicRollover).with_for_update().compile(dialect=psycopg.dialect()))
        self.assertIn('FOR UPDATE', sql)

    def test_inactive_deleted_and_pending_students_not_advanced_and_boundary_levels(self):
        for label, kwargs in (
            ('inactive', {'is_active': False}),
            ('deleted', {'is_deleted': True}),
            ('pending', {'status': 'pending_confirmation'}),
        ):
            db.session.add(Student(full_name=label, current_grade='Lớp 4', level='primary',
                                   grade_year=None, **kwargs))
        fifth = Student(full_name='Fifth', current_grade='Lớp 5', level='primary', grade_year=2026)
        ninth = Student(full_name='Ninth', current_grade='Lớp 9', level='secondary', grade_year=2026)
        db.session.add_all([fifth, ninth])
        db.session.commit()
        self.queue()
        self.assertEqual(self.run_worker().exit_code, 0)
        self.assertEqual((fifth.current_grade, fifth.level), ('Lớp 6', 'secondary'))
        self.assertEqual((ninth.current_grade, ninth.level), ('Lớp 10', 'high_school'))
        for student in Student.query.filter(Student.full_name.in_(['inactive', 'deleted', 'pending'])):
            self.assertEqual(student.current_grade, 'Lớp 4')
            self.assertIsNone(student.grade_year)

    def test_roster_with_invalid_student_blocks_and_does_not_drop_them(self):
        self.student.is_active = False
        db.session.commit()
        self.assertTrue(any('Đăng ký' in error for error in build_rollover_plan()['errors']))
        self.assertEqual(self.cls.enrollments.count(), 1)

    def test_precreated_inactive_year_is_reused_and_semesters_created(self):
        from models import Semester
        target = AcademicYear(name='2027-2028', start_date=date(2027, 7, 1),
                              end_date=date(2028, 6, 30), is_active=False)
        db.session.add(target)
        db.session.commit()
        self.queue()
        self.assertEqual(self.run_worker().exit_code, 0)
        self.assertEqual(AcademicYear.query.count(), 2)
        self.assertTrue(target.is_active)
        self.assertEqual(Semester.query.filter_by(academic_year_id=target.id).count(), 3)
        new = Class.query.filter_by(rolled_over_from_id=self.cls.id).one()
        self.assertTrue(all(row.semester_id for row in new.schedules))

    def test_multiple_slots_same_day_and_shared_teacher_conflict_between_new_classes(self):
        second = Class(name='Hoá 9', grade_level='Lớp 9', course_id=self.course.id,
                       primary_teacher_id=self.teacher.id)
        db.session.add(second)
        db.session.flush()
        db.session.add(Schedule(class_id=second.id, date=date(2027, 6, 21),
                                start_time=time(17, 15), end_time=time(17, 45),
                                teacher_id=self.teacher.id, room='B'))
        db.session.commit()
        errors = build_rollover_plan()['errors']
        self.assertTrue(any('teacher' in error for error in errors))
        self.assertFalse(any('room_text' in error for error in errors))

    def test_1000_students_are_advanced_once_without_changing_profiles(self):
        for i in range(999):
            db.session.add(Student(full_name=f'Bulk {i}', current_grade='Lớp 4',
                                   level='primary', grade_year=2026, note='Unchanged'))
        db.session.commit()
        self.queue()
        self.assertEqual(self.run_worker().exit_code, 0)
        self.assertEqual(Student.query.filter_by(current_grade='Lớp 5', grade_year=2027).count(), 999)
        self.assertEqual(Student.query.filter_by(note='Unchanged').count(), 999)
        self.assertEqual(self.run_worker().exit_code, 0)
        self.assertEqual(Student.query.filter_by(current_grade='Lớp 5', grade_year=2027).count(), 999)

    def test_student_baseline_can_be_corrected_explicitly_without_enrollment_changes(self):
        self.student.grade_year = None
        db.session.commit()
        original = self.snapshot(self.enrollment)
        url = f'/admin/students/{self.student.id}/edit'
        data = {'current_grade': 'Lớp 10', 'level': 'high_school', 'grade_year': 'bad'}
        self.assertEqual(self.client.post(url, data=data).status_code, 200)
        self.assertIsNone(self.student.grade_year)
        data.update(grade_year='2026', is_active='1')
        self.assertEqual(self.client.post(url, data=data).status_code, 302)
        self.assertEqual(self.student.grade_year, 2026)
        self.assertEqual(self.snapshot(self.enrollment), original)

    def test_large_schedule_batch_commits_every_expected_record(self):
        from time import perf_counter
        for i in range(24):
            user = User(username=f'bulk-teacher-{i}', role='teacher', password_hash='test')
            db.session.add(user)
            db.session.flush()
            teacher = Teacher(user_id=user.id)
            db.session.add(teacher)
            db.session.flush()
            cls = Class(name=f'Hoá 10 - nhóm {i}', grade_level='Lớp 10', course_id=self.course.id,
                        primary_teacher_id=teacher.id, start_date=self.year.start_date, end_date=self.year.end_date)
            db.session.add(cls)
            db.session.flush()
            for day in (21, 23, 25):
                db.session.add(Schedule(class_id=cls.id, date=date(2027, 6, day), start_time=time(17),
                                        end_time=time(18), teacher_id=teacher.id, room=f'room-{i}'))
        db.session.commit()
        plan = build_rollover_plan()
        self.assertEqual(plan['errors'], [])
        self.assertEqual(len(plan['schedules']), 25 * 157)
        self.queue()
        started = perf_counter()
        result = self.run_worker()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(Class.query.filter(Class.rolled_over_from_id.isnot(None)).count(), 25)
        self.assertEqual(Schedule.query.count(), 25 * (157 + 3))
        print(f'Rollover fixture: 25 classes / 3925 new schedules committed in {perf_counter() - started:.2f}s (local SQLite).')

    def test_post_requires_csrf_when_enabled(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        try:
            plan = build_rollover_plan()
            response = self.client.post('/admin/academic-years/rollover', data={'fingerprint': plan['fingerprint']})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(AcademicRollover.query.count(), 0)
        finally:
            self.app.config['WTF_CSRF_ENABLED'] = False

    def test_next_cohort_can_receive_grade10_content_after_grade10_cohort_advances(self):
        source = self.history[3]
        source.questions_json = json.dumps({'groups': [
            {'title': 'Essay', 'type': 'essay', 'questions': [{'text': 'Explain chemistry'}]},
        ]})
        ninth_user = User(username='ninth-user', role='student', password_hash='test')
        db.session.add(ninth_user)
        db.session.flush()
        ninth = Student(full_name='Next cohort', current_grade='Lớp 9', level='secondary',
                        grade_year=2026, user_id=ninth_user.id)
        old_ninth = Class(name='Hoá 9 - Cô A', grade_level='Lớp 9', course_id=self.course.id,
                          primary_teacher_id=self.teacher.id, start_date=self.year.start_date,
                          end_date=self.year.end_date)
        db.session.add_all([ninth, old_ninth])
        db.session.flush()
        db.session.add(Enrollment(class_id=old_ninth.id, student_id=ninth.id, discount_pct=5))
        db.session.add(Schedule(class_id=old_ninth.id, date=date(2027, 6, 21),
                                start_time=time(19), end_time=time(20), teacher_id=self.teacher.id, room='B'))
        db.session.commit()
        self.queue()
        self.assertEqual(self.run_worker().exit_code, 0)
        new_tenth = Class.query.filter_by(rolled_over_from_id=old_ninth.id).one()
        self.assertEqual(new_tenth.grade_level, 'Lớp 10')
        self.assertEqual(ninth.current_grade, 'Lớp 10')
        self.assertEqual(self.student.current_grade, 'Lớp 11')
        self.assertEqual(source.content_grade, 'Lớp 10')
        self.login(self.teacher_user)
        html = self.client.get('/teacher/exams?reuse=1&content_grade=Lớp+10').get_data(as_text=True)
        self.assertIn(source.title, html)
        self.assertEqual(self.client.post(f'/teacher/exams/{source.id}/duplicate').status_code, 302)
        copy = Exam.query.filter(Exam.id != source.id).one()
        response = self.client.post('/teacher/exams/confirm', data={
            'edit_exam_id': str(copy.id), 'title': copy.title, 'groups_json': source.questions_json,
            'subject': 'Hoá', 'content_grade': 'Lớp 10', 'is_draft': 'published',
            'class_ids': [str(new_tenth.id)], 'duration_minutes': '40',
            'section_points_0': '10', 'question_points_0_0': '10',
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(copy.is_draft)
        self.assertEqual(copy.class_list, [new_tenth.id])
        self.assertEqual(source.class_list, [self.cls.id])
        self.assertEqual(copy.attempts.count(), 0)
        self.login(ninth_user)
        self.assertEqual(self.client.get(f'/student/exams/{copy.id}').status_code, 200)
        self.assertEqual(self.client.get(f'/student/exams/{source.id}').status_code, 404)
        self.login(self.student_user)
        self.assertEqual(self.client.get(f'/student/exams/{copy.id}').status_code, 404)

    def test_tuition_debt_follows_new_class_without_mutating_old_invoice(self):
        from services.tuition_service import get_previous_month_debt, generate_missing_bills_for_class
        old_invoice = self.snapshot(self.history[2])
        self.queue()
        self.assertEqual(self.run_worker().exit_code, 0)
        new = Class.query.filter_by(rolled_over_from_id=self.cls.id).one()
        self.assertEqual(get_previous_month_debt(self.student.id, new.id, 7, 2027), 430000)
        self.assertEqual(generate_missing_bills_for_class(new.id, 7, 2027), 1)
        db.session.commit()
        new_invoice = TuitionPayment.query.filter_by(class_id=new.id, month=7, year=2027).one()
        self.assertEqual(new_invoice.debt_carried_over, 430000)
        self.assertEqual(self.snapshot(self.history[2]), old_invoice)

    def test_following_year_advances_once_and_keeps_each_year_separate(self):
        self.queue()
        self.assertEqual(self.run_worker().exit_code, 0)
        second = Class.query.filter_by(rolled_over_from_id=self.cls.id).one()
        second_id = second.id
        self.mock_date.today.return_value = date(2028, 7, 1)
        self.queue()
        self.assertEqual(self.run_worker().exit_code, 0)
        third = Class.query.filter_by(rolled_over_from_id=second_id).one()
        self.assertEqual((third.grade_level, self.student.current_grade), ('Lớp 12', 'Lớp 12'))
        self.assertTrue(self.student.is_active, 'Entering grade 12 must not graduate early')
        self.assertFalse(second.is_active)
        self.assertEqual(Class.query.count(), 3)
        self.assertEqual(AcademicRollover.query.filter_by(status='succeeded').count(), 2)

    def test_api_creation_and_grade_edits_record_baseline_year(self):
        self.admin.api_token = 'synthetic-rollover-test-token'
        db.session.commit()
        headers = {'Authorization': f'Bearer {self.admin.api_token}'}
        response = self.client.post('/api/v1/students', headers=headers, json={
            'full_name': 'API Student', 'level': 'primary', 'current_grade': 'Lớp 4',
        })
        self.assertEqual(response.status_code, 201)
        student = Student.query.filter_by(full_name='API Student').one()
        self.assertEqual(student.grade_year, 2026)
        student.grade_year = 2025
        db.session.commit()
        self.assertEqual(self.client.put(f'/api/v1/students/{student.id}', headers=headers, json={
            'note': 'Note edit only',
        }).status_code, 200)
        self.assertEqual(student.grade_year, 2025)
        self.assertEqual(self.client.put(f'/api/v1/students/{student.id}', headers=headers, json={
            'current_grade': 'Lớp 5',
        }).status_code, 200)
        self.assertEqual(student.grade_year, 2026)

    def test_room_id_and_legacy_room_name_refer_to_same_resource(self):
        from models import Room
        room = Room(name='A')
        db.session.add(room)
        db.session.flush()
        db.session.add(Schedule(class_id=self.cls.id, date=date(2027, 7, 2),
                                start_time=time(17, 15), end_time=time(17, 45),
                                teacher_id=self.assistant.id, room_id=room.id))
        db.session.commit()
        errors = build_rollover_plan()['errors']
        self.assertTrue(any(f'room #{room.id}:' in error for error in errors))

    def test_disabled_teacher_and_overlapping_semesters_block(self):
        from models import Semester
        self.teacher_user.is_active = False
        db.session.commit()
        self.assertTrue(any('giáo viên' in error for error in build_rollover_plan()['errors']))
        self.teacher_user.is_active = True
        target = AcademicYear(name='2027-2028', start_date=date(2027, 7, 1),
                              end_date=date(2028, 6, 30), is_active=False)
        db.session.add(target)
        db.session.flush()
        for label in ('One', 'Two'):
            db.session.add(Semester(academic_year_id=target.id, name=label, semester_type='semester_1',
                                    start_date=target.start_date, end_date=target.end_date))
        db.session.commit()
        self.assertTrue(any('chồng lấn' in error for error in build_rollover_plan()['errors']))

    def test_default_off_blocks_queue_worker_and_direct_execution_even_after_july(self):
        job = self.queue()
        self.app.config['ACADEMIC_ROLLOVER_ENABLED'] = False
        try:
            response = self.client.post('/admin/academic-years/rollover', data={
                'fingerprint': build_rollover_plan()['fingerprint'],
            })
            self.assertEqual(response.status_code, 302)
            self.assertEqual(Class.query.count(), 1)
            self.assertEqual(AcademicRollover.query.count(), 1)
            result = self.run_worker()
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn('disabled', result.output)
            self.assertEqual(job.status, 'pending')
            with self.assertRaises(RolloverError):
                execute_rollover(job)
            self.assertEqual(self.student.current_grade, 'Lớp 10')
            self.assertEqual(Schedule.query.count(), 3)
            self.assertTrue(self.year.is_active)
            html = self.client.get('/admin/academic-years').get_data(as_text=True)
            self.assertIn('Chức năng đang tắt', html)
        finally:
            self.app.config['ACADEMIC_ROLLOVER_ENABLED'] = True
