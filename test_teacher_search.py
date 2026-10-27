"""Teacher search uses only synthetic in-memory data."""
import unittest
from unittest.mock import patch

from flask import g

from app import create_app
from config import Config, config
from extensions import db
from models import Teacher, User


class TeacherSearchConfig(Config):
    TESTING = True
    SECRET_KEY = 'synthetic-teacher-search'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    ACADEMIC_ROLLOVER_ENABLED = False


class TeacherSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config['teacher_search_test'] = TeacherSearchConfig
        cls.app = create_app('teacher_search_test')

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.engine.dispose()
        config.pop('teacher_search_test')

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.master = User(username='master', role='admin', is_master=True, password_hash='test')
        self.denied = User(username='denied', role='admin', password_hash='test')
        db.session.add_all([self.master, self.denied])
        for i in range(12):
            user = User(username=f'teacher{i:02}', full_name=f'Nguyễn An {i:02}',
                        phone=f'09000000{i:02}', role='teacher', password_hash='test')
            db.session.add(user)
            db.session.flush()
            db.session.add(Teacher(user_id=user.id, is_staff=i % 2 == 0))
        for name, active, deleted in (
            ('Inactive', False, False), ('Deleted', True, True), ('Literal %_/', True, False),
        ):
            user = User(username=name, full_name=name, role='teacher', password_hash='test',
                        is_active=active, is_deleted=deleted)
            db.session.add(user)
            db.session.flush()
            db.session.add(Teacher(user_id=user.id))
        db.session.commit()
        self.client = self.app.test_client()
        self.login(self.master)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def login(self, user):
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user.id)
            session['_fresh'] = True

    def search(self, **params):
        captured = {}

        def capture(template, **context):
            captured.update(context)
            return 'OK'

        with patch('blueprints.admin.teachers.render_template', side_effect=capture):
            response = self.client.get('/admin/teachers', query_string=params)
        self.assertEqual(response.status_code, 200)
        return captured

    def test_partial_name_phone_username_and_whitespace(self):
        for term in (' An 03 ', '0900000003', 'TEACHER03'):
            context = self.search(q=term)
            self.assertEqual([t.user.username for t in context['teachers']], ['teacher03'])
            self.assertEqual(context['q'], term.strip())
        self.assertEqual(self.search(q='Nguyễn')['pagination'].total, 12)

    def test_search_before_pagination_and_stable_pages(self):
        first = self.search(q='An', page=1)
        second = self.search(q='An', page=2)
        self.assertEqual(first['pagination'].total, 12)
        self.assertEqual(len(first['teachers']), 10)
        self.assertEqual(len(second['teachers']), 2)
        self.assertFalse({t.id for t in first['teachers']} & {t.id for t in second['teachers']})
        html = self.client.get('/admin/teachers?q=An').get_data(as_text=True)
        self.assertIn('page=2&amp;q=An', html)
        self.assertIn('value="An"', html)
        self.assertIn('Xóa tìm kiếm', html)

    def test_literal_wildcards_empty_no_match_and_inactive_accounts(self):
        self.assertEqual(self.search(q='%_/')['pagination'].total, 1)
        self.assertEqual(self.search(q='Inactive')['pagination'].total, 0)
        self.assertEqual(self.search(q='Deleted')['pagination'].total, 0)
        self.assertEqual(self.search(q='   ')['pagination'].total, 13)
        html = self.client.get('/admin/teachers?q=missing').get_data(as_text=True)
        self.assertIn('Không tìm thấy giáo viên phù hợp', html)
        self.assertNotIn('Thêm giáo viên đầu tiên', html)
        self.assertEqual(self.search(q='An', page=99)['teachers'], [])

    def test_master_only_access_unchanged(self):
        self.login(self.denied)
        self.assertEqual(self.client.get('/admin/teachers?q=An').status_code, 403)
        g.pop('_login_user', None)
        self.assertEqual(self.app.test_client().get('/admin/teachers?q=An').status_code, 302)
