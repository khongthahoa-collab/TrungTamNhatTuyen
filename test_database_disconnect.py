"""A lost authentication connection is retried without replaying request writes."""
import json
import unittest
from unittest.mock import patch

from flask import abort
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from app import create_app
from config import Config, config
from extensions import db
from models import Exam, Teacher, User


class DisconnectConfig(Config):
    TESTING = True
    PROPAGATE_EXCEPTIONS = False
    SECRET_KEY = 'database-disconnect-test'
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


class DatabaseDisconnectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config['disconnect_test'] = DisconnectConfig
        cls.app = create_app('disconnect_test')
        cls.app.add_url_rule('/test-internal-error', endpoint='test_internal_error', view_func=lambda: abort(500))
        cls.app.add_url_rule('/test-bad-gateway', endpoint='test_bad_gateway', view_func=lambda: abort(502))

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.engine.dispose()
        config.pop('disconnect_test', None)

    def setUp(self):
        with self.app.app_context():
            db.drop_all()
            db.create_all()
            teacher = User(username='disconnect-teacher', full_name='Synthetic teacher',
                           role='teacher', password_hash='test')
            db.session.add(Teacher(user=teacher))
            db.session.commit()
            self.teacher_id = teacher.id
            self.engine = db.engine
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['_user_id'] = str(self.teacher_id)
            session['_fresh'] = True

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def disconnect_listener(self, failures=1, invalidated=True):
        state = {'reads': 0, 'failures': failures}

        def listener(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith('SELECT') and 'FROM users' in statement:
                state['reads'] += 1
                if state['failures']:
                    state['failures'] -= 1
                    raise OperationalError(
                        'synthetic authentication read', {}, RuntimeError('synthetic disconnect'),
                        connection_invalidated=invalidated,
                    )
        return state, listener

    def test_idle_disconnect_recovers_attendance_and_configuration(self):
        for path, method, data in (
            ('/teacher/attendance?date=2026-11-01&view=day', 'GET', None),
            ('/teacher/exams/create?mode=compose', 'POST', {
                'title': 'Recovered configuration', 'groups_json': json.dumps({'groups': [
                    {'title': 'Essay', 'type': 'essay', 'questions': [{'text': 'Explain'}]},
                ]}),
            }),
        ):
            with self.subTest(path=path):
                state, listener = self.disconnect_listener()
                event.listen(self.engine, 'before_cursor_execute', listener)
                try:
                    with self.assertLogs(self.app.logger, level='WARNING') as logs:
                        response = self.client.open(path, method=method, data=data)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(state['reads'], 2)
                    self.assertTrue(any('reconnecting once' in line for line in logs.output))
                    with self.client.session_transaction() as session:
                        self.assertEqual(session['_user_id'], str(self.teacher_id))
                finally:
                    event.remove(self.engine, 'before_cursor_execute', listener)

    def test_recovery_does_not_duplicate_exam_writes(self):
        state, listener = self.disconnect_listener()
        event.listen(self.engine, 'before_cursor_execute', listener)
        try:
            with self.assertLogs(self.app.logger, level='WARNING'):
                response = self.client.post('/teacher/exams/confirm', data={
                    'title': 'Created once', 'subject': 'Math', 'duration_minutes': '40',
                    'section_points_0': '10', 'question_points_0_0': '10',
                    'is_draft': 'draft', 'groups_json': json.dumps({'groups': [
                        {'title': 'Essay', 'type': 'essay', 'questions': [{'text': 'Explain'}]},
                    ]}),
                })
            self.assertEqual(response.status_code, 302)
            self.assertEqual(state['reads'], 2)
            with self.app.app_context():
                self.assertEqual(Exam.query.filter_by(title='Created once').count(), 1)
        finally:
            event.remove(self.engine, 'before_cursor_execute', listener)

    def test_persistent_disconnect_is_bounded_and_error_page_needs_no_database(self):
        state, listener = self.disconnect_listener(failures=10)
        event.listen(self.engine, 'before_cursor_execute', listener)
        try:
            with patch('models.SystemConfig.get', side_effect=AssertionError('Error page used DB')), \
                    patch.dict(self.app.template_context_processors, {None: [
                        lambda: (_ for _ in ()).throw(AssertionError('Error page ran context processors'))
                    ]}), self.assertLogs(self.app.logger, level='WARNING'):
                response = self.client.get('/teacher/attendance')
            self.assertEqual(response.status_code, 500)
            self.assertEqual(state['reads'], 2)
            self.assertIn('Tải lại trang', response.get_data(as_text=True))
            self.assertIn('500', response.get_data(as_text=True))
        finally:
            event.remove(self.engine, 'before_cursor_execute', listener)
        self.assertEqual(self.client.get('/teacher/attendance').status_code, 200)

    def test_non_disconnect_database_error_is_not_retried(self):
        state, listener = self.disconnect_listener(invalidated=False)
        event.listen(self.engine, 'before_cursor_execute', listener)
        try:
            with self.assertLogs(self.app.logger, level='ERROR'):
                response = self.client.get('/teacher/attendance')
            self.assertEqual(response.status_code, 500)
            self.assertEqual(state['reads'], 1)
        finally:
            event.remove(self.engine, 'before_cursor_execute', listener)

    def test_server_error_pages_skip_queries_and_keep_status(self):
        for path, status in (('/test-internal-error', 500), ('/test-bad-gateway', 502)):
            with self.subTest(status=status):
                with patch('models.SystemConfig.get', side_effect=AssertionError('Error page used DB')):
                    response = self.client.get(path)
                self.assertEqual(response.status_code, status)
                self.assertIn('Tải lại trang', response.get_data(as_text=True))
                self.assertIn('no-store', response.headers['Cache-Control'])
