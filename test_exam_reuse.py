"""Reusing grade-tagged content never moves assignments or copies old answers."""
import json
import unittest

from flask import g
from werkzeug.datastructures import MultiDict

from app import create_app
from config import Config, config
from extensions import db
from models import AcademicYear, Class, Course, Exam, ExamAttempt, ExamFolder, Student, User
from blueprints.exams_shared import parse_confirm_settings


class ReuseConfig(Config):
    TESTING = True
    SECRET_KEY = 'reuse-test'
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


class ExamReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config['reuse_test'] = ReuseConfig
        cls.app = create_app('reuse_test')

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.engine.dispose()
        config.pop('reuse_test', None)

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.admin = User(username='admin', role='admin', is_master=True, password_hash='test')
        self.teacher = User(username='teacher', role='teacher', password_hash='test')
        self.other = User(username='other', role='teacher', password_hash='test')
        self.student_user = User(username='student', role='student', password_hash='test')
        course = Course(name='Hoá')
        db.session.add_all([self.admin, self.teacher, self.other, self.student_user, course])
        db.session.flush()
        self.old = Class(name='Hoá 10 cũ', course_id=course.id, grade_level='Lớp 10', is_active=False)
        db.session.add(self.old)
        db.session.flush()
        self.folder = ExamFolder(name='Lớp cũ', scope_type='class', class_id=self.old.id, created_by=self.teacher.id)
        self.student = Student(full_name='Student', level='high_school', current_grade='Lớp 11')
        db.session.add_all([self.folder, self.student])
        db.session.flush()
        self.exam = Exam(
            title='Old chemistry exam', subject='Hoá', content_grade='Lớp 10', created_by=self.teacher.id,
            class_ids=str(self.old.id), student_ids=str(self.student.id), folder_id=self.folder.id,
            questions_json=json.dumps({'groups': [{'type': 'essay', 'questions': [{'text': 'Explain'}]}]}),
            shuffle_questions=False, shuffle_answers=False, availability_mode='time_window',
        )
        db.session.add(self.exam)
        db.session.flush()
        self.attempt = ExamAttempt(exam_id=self.exam.id, user_id=self.student_user.id,
                                   student_id=self.student.id, status='submitted', score=8,
                                   answers_json='{"g0_q1":"Old answer"}')
        db.session.add(self.attempt)
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def login(self, user):
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session.clear()
            session['_user_id'] = str(user.id)
            session['_fresh'] = True

    def test_teacher_copy_keeps_content_and_grade_but_no_assignments_or_attempts(self):
        self.login(self.teacher)
        response = self.client.post(f'/teacher/exams/{self.exam.id}/duplicate')
        self.assertEqual(response.status_code, 302)
        copy = Exam.query.filter(Exam.id != self.exam.id).one()
        self.assertEqual(copy.content_grade, 'Lớp 10')
        self.assertEqual(copy.questions_json, self.exam.questions_json)
        self.assertEqual((copy.class_ids, copy.school_ids, copy.student_ids), ('', '', ''))
        self.assertIsNone(copy.folder_id)
        self.assertEqual(copy.availability_mode, 'always')
        self.assertIsNone(copy.available_from)
        self.assertIsNone(copy.available_to)
        self.assertFalse(copy.shuffle_questions)
        self.assertFalse(copy.shuffle_answers)
        self.assertTrue(copy.is_draft)
        self.assertFalse(copy.is_shared_with_teachers)
        self.assertEqual(copy.attempts.count(), 0)
        self.assertEqual(self.attempt.score, 8)
        self.assertEqual(self.attempt.exam_id, self.exam.id)
        self.assertEqual(self.exam.class_ids, str(self.old.id))
        copy.questions_json = '{"groups":[]}'
        db.session.commit()
        self.assertNotEqual(copy.questions_json, self.exam.questions_json)
        response = self.client.get('/teacher/exams?reuse=1&content_grade=Lớp+10')
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.exam.title, response.get_data(as_text=True))
        response = self.client.get('/teacher/exams?reuse=1&content_grade=Lớp+11')
        self.assertNotIn(self.exam.title, response.get_data(as_text=True))

    def test_admin_copy_and_shared_permissions(self):
        self.login(self.other)
        self.assertEqual(self.client.post(f'/teacher/exams/{self.exam.id}/duplicate').status_code, 404)
        self.exam.is_shared_with_teachers = True
        db.session.commit()
        self.assertEqual(self.client.post(f'/teacher/exams/{self.exam.id}/duplicate').status_code, 302)
        copy = Exam.query.filter_by(created_by=self.other.id).one()
        self.assertEqual(copy.content_grade, 'Lớp 10')
        self.assertEqual(copy.attempts.count(), 0)
        self.login(self.admin)
        self.assertEqual(self.client.post(f'/admin/exam/{self.exam.id}/duplicate').status_code, 302)
        admin_copy = Exam.query.filter_by(created_by=self.admin.id).one()
        self.assertEqual(admin_copy.content_grade, 'Lớp 10')
        self.assertEqual(admin_copy.attempts.count(), 0)
        self.assertEqual(self.client.get('/admin/exam?content_grade=Lớp+10').status_code, 200)
        self.assertEqual(ExamAttempt.query.count(), 1)

    def test_grade_validation_and_teacher_confirm_persistence(self):
        self.login(self.teacher)
        data = MultiDict({
            'title': 'New content', 'groups_json': self.exam.questions_json, 'subject': 'Hoá',
            'content_grade': 'Lớp 10', 'is_draft': 'draft', 'duration_minutes': '40',
            'section_points_0': '10',
            'question_points_0_0': '10',
        })
        parsed, error = parse_confirm_settings(data, [])
        self.assertIsNone(error)
        self.assertEqual(parsed['content_grade'], 'Lớp 10')
        response = self.client.post('/teacher/exams/confirm', data=data)
        self.assertEqual(response.status_code, 302)
        saved = Exam.query.filter_by(title='New content').one()
        self.assertEqual(saved.content_grade, 'Lớp 10')
        response = self.client.get(f'/teacher/exams/edit/{saved.id}')
        self.assertEqual(response.status_code, 200)
        data['content_grade'] = 'Lớp 13'
        self.assertIsNotNone(parse_confirm_settings(data, [])[1])

    def test_schema_upgrade_is_idempotent(self):
        from app import _ensure_new_columns
        from sqlalchemy import inspect
        _ensure_new_columns()
        _ensure_new_columns()
        columns = {column['name'] for column in inspect(db.engine).get_columns('exams')}
        self.assertIn('content_grade', columns)
        self.assertEqual(self.exam.content_grade, 'Lớp 10')

    def test_existing_database_upgrades_without_backfilling_or_losing_content(self):
        from app import _ensure_new_columns
        from sqlalchemy import text, inspect
        exam_id = self.exam.id
        content = self.exam.questions_json
        db.session.remove()
        with db.engine.begin() as conn:
            conn.execute(text('ALTER TABLE exams DROP COLUMN content_grade'))
            conn.execute(text('ALTER TABLE students DROP COLUMN grade_year'))
            conn.execute(text('DROP TABLE academic_rollovers'))
        _ensure_new_columns()
        _ensure_new_columns()
        self.assertIn('academic_rollovers', inspect(db.engine).get_table_names())
        self.assertEqual(db.session.get(Exam, exam_id).questions_json, content)
        self.assertEqual(db.session.get(Exam, exam_id).content_grade, '')
        self.assertIsNone(Student.query.one().grade_year)
        self.assertEqual(ExamAttempt.query.count(), 1)

    def test_homework_reuse_does_not_copy_old_student_records(self):
        from datetime import date
        from models import Teacher, Homework, HomeworkRecord, Enrollment
        teacher = Teacher(user_id=self.teacher.id)
        db.session.add(teacher)
        db.session.flush()
        self.old.primary_teacher_id = teacher.id
        target = Class(name='Hoá 10 mới', grade_level='Lớp 10', course_id=self.old.course_id,
                       primary_teacher_id=teacher.id)
        db.session.add(target)
        db.session.flush()
        db.session.add(Enrollment(class_id=target.id, student_id=self.student.id))
        source = Homework(class_id=self.old.id, title='Bài tập khối 10', note='Keep instruction',
                          assigned_date=date(2026, 8, 1), semester='semester_1')
        db.session.add(source)
        db.session.flush()
        db.session.add(HomeworkRecord(homework_id=source.id, student_id=self.student.id, status='done'))
        db.session.commit()
        self.login(self.teacher)
        html = self.client.get(f'/teacher/homework/{target.id}').get_data(as_text=True)
        self.assertIn('source_homework_id', html)
        self.assertIn(source.title, html)
        response = self.client.post(f'/teacher/homework/{target.id}/new', data={
            'source_homework_id': str(source.id), 'assigned_date': '2027-08-03', 'semester': 'semester_2',
        })
        self.assertEqual(response.status_code, 302)
        copied = Homework.query.filter_by(class_id=target.id).one()
        self.assertEqual((copied.title, copied.note), (source.title, source.note))
        self.assertEqual(copied.assigned_date, date(2027, 8, 3))
        self.assertEqual(copied.semester, 'semester_2')
        self.assertEqual(copied.records.count(), 0)
        self.assertEqual(source.records.count(), 1)
        self.assertEqual(self.client.post(f'/teacher/homework/{self.old.id}/new').status_code, 409)
        self.login(self.other)
        self.assertEqual(self.client.post(f'/teacher/homework/{target.id}/new', data={
            'source_homework_id': source.id,
        }).status_code, 403)
