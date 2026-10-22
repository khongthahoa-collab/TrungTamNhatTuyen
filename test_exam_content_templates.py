"""Focused library checks: venv/bin/python -m unittest test_exam_content_templates."""
import json
import re
import unittest
from html import unescape
from unittest.mock import patch

from sqlalchemy import create_engine, inspect, select

from app import _ensure_new_columns, create_app
from config import Config, config
from extensions import db
from models import Exam, ExamContentTemplate, PermissionGroup, User, UserRole


class LibraryTestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'exam-content-library-test'


class ExamContentTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config['exam_content_library_test'] = LibraryTestConfig
        cls.app = create_app('exam_content_library_test')
        with cls.app.app_context():
            group = PermissionGroup(name='Library read only', permissions=json.dumps({'exams': 'read'}))
            db.session.add(group)
            db.session.flush()
            cls.user_ids = {}
            for role in (UserRole.ADMIN, UserRole.TEACHER, UserRole.PARENT, UserRole.STUDENT):
                user = User(
                    username='library_' + role, full_name=role, role=role,
                    password_hash='not-used', is_master=role == UserRole.ADMIN,
                )
                db.session.add(user)
                db.session.flush()
                cls.user_ids[role] = user.id
            for name, permission_group in [('reader', group), ('denied', None)]:
                user = User(
                    username='library_' + name, role=UserRole.ADMIN,
                    password_hash='not-used', permission_group=permission_group,
                )
                db.session.add(user)
                db.session.flush()
                cls.user_ids[name] = user.id
            db.session.commit()

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.engine.dispose()
        config.pop('exam_content_library_test', None)

    def setUp(self):
        self.client = self.app.test_client()
        with self.app.app_context():
            ExamContentTemplate.query.delete()
            db.session.commit()

    def login(self, role, active_role=None):
        with self.client.session_transaction() as session:
            csrf_secret = session.get('csrf_token')
            session.clear()
            if csrf_secret:
                session['csrf_token'] = csrf_secret
            session['_user_id'] = str(self.user_ids[role])
            session['_fresh'] = True
            if active_role:
                session['active_role'] = active_role

    def csrf(self):
        response = self.client.get('/admin/exam/content-templates/new')
        self.assertEqual(response.status_code, 200)
        return re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))[1]

    def add_template(self, name='Mẫu chung', content='  Nội dung\n<em>Giữ nguyên</em>\n'):
        response = self.client.post('/admin/exam/content-templates/new', data={
            'csrf_token': self.csrf(), 'name': name, 'content': content,
        })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            return ExamContentTemplate.query.filter_by(name=name.strip()).one().id

    def test_admin_crud_persists_and_does_not_change_existing_exams(self):
        self.login('admin')
        raw = '  # Phần 1\nCâu 1: Nội dung\nA. Sai\n*B. Đúng\n'
        template_id = self.add_template(content=raw)
        with self.app.app_context():
            db.session.remove()
            stored = db.session.execute(select(ExamContentTemplate)).scalar_one()
            self.assertEqual((stored.id, stored.content), (template_id, raw))
            exam = Exam(
                title='Đề độc lập', created_by=self.user_ids['admin'],
                questions_json='{"groups":[]}',
            )
            db.session.add(exam)
            db.session.commit()
            exam_id = exam.id
        response = self.client.post(f'/admin/exam/content-templates/{template_id}/edit', data={
            'csrf_token': self.csrf(), 'name': 'Tên mới', 'content': 'Nội dung mới',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get('/exam-content-templates').get_json(), {
            'templates': [{'id': template_id, 'name': 'Tên mới', 'content': 'Nội dung mới'}],
        })
        response = self.client.post(f'/admin/exam/content-templates/{template_id}/delete', data={
            'csrf_token': self.csrf(),
        })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            db.session.remove()
            self.assertIsNone(db.session.get(ExamContentTemplate, template_id))
            self.assertEqual(db.session.get(Exam, exam_id).questions_json, '{"groups":[]}')

    def test_read_api_for_admin_and_teacher_only(self):
        self.login('admin')
        template_id = self.add_template()
        for role in ('admin', 'teacher', 'reader'):
            with self.subTest(role=role):
                self.login(role)
                response = self.client.get('/exam-content-templates')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()['templates'][0]['id'], template_id)
                self.assertEqual(set(response.get_json()['templates'][0]), {'id', 'name', 'content'})
                self.assertIn('no-store', response.headers['Cache-Control'])
        for role in ('parent', 'student', 'denied'):
            with self.subTest(role=role):
                self.login(role)
                self.assertEqual(self.client.get('/exam-content-templates').status_code, 403)
        self.login('parent', active_role='teacher')
        self.assertEqual(self.client.get('/exam-content-templates').status_code, 403)
        self.client = self.app.test_client()
        self.assertEqual(self.client.get('/exam-content-templates').status_code, 302)

    def test_non_admins_cannot_manage_even_with_valid_csrf(self):
        self.login('admin')
        template_id = self.add_template()
        token = self.csrf()
        for role in ('teacher', 'parent', 'student'):
            self.login(role)
            for path in (
                '/admin/exam/content-templates',
                '/admin/exam/content-templates/new',
                f'/admin/exam/content-templates/{template_id}/edit',
            ):
                self.assertEqual(self.client.get(path).status_code, 403)
            for path in (
                '/admin/exam/content-templates/new',
                f'/admin/exam/content-templates/{template_id}/edit',
                f'/admin/exam/content-templates/{template_id}/delete',
            ):
                response = self.client.post(path, data={
                    'csrf_token': token, 'name': 'Unauthorized', 'content': 'No',
                })
                self.assertEqual(response.status_code, 403)
        self.login('admin', active_role='teacher')
        self.assertEqual(self.client.get('/admin/exam/content-templates').status_code, 403)
        self.assertEqual(self.client.get('/exam-content-templates').status_code, 200)
        self.assertEqual(self.client.post(
            f'/admin/exam/content-templates/{template_id}/delete',
            data={'csrf_token': token},
        ).status_code, 403)

    def test_csrf_required_and_read_only_admin_cannot_write(self):
        self.login('admin')
        template_id = self.add_template()
        for suffix in ('new', f'{template_id}/edit', f'{template_id}/delete'):
            self.assertEqual(self.client.post(
                '/admin/exam/content-templates/' + suffix,
                data={'name': 'No CSRF', 'content': 'No CSRF'},
            ).status_code, 400)
        self.login('reader')
        token = self.csrf()
        self.assertEqual(self.client.get('/admin/exam/content-templates').status_code, 200)
        for suffix in ('new', f'{template_id}/edit', f'{template_id}/delete'):
            self.assertEqual(self.client.post(
                '/admin/exam/content-templates/' + suffix,
                data={'csrf_token': token, 'name': 'Blocked', 'content': 'Blocked'},
            ).status_code, 403)
        self.assertEqual(self.client.get(
            f'/admin/exam/content-templates/{template_id}/delete'
        ).status_code, 405)

    def test_validation_errors_are_visible_and_preserve_input(self):
        self.login('admin')
        template_id = self.add_template()
        for name, content, error in (
            (' ', 'Valid content', 'Vui lòng nhập tên mẫu.'),
            ('x' * 201, 'Valid content', 'Tên mẫu không được vượt quá 200 ký tự.'),
            ('Name', ' \n ', 'Vui lòng nhập nội dung mẫu.'),
            ('Name', 'x' * 200001, 'Nội dung mẫu không được vượt quá 200.000 ký tự.'),
        ):
            for suffix in ('new', f'{template_id}/edit'):
                response = self.client.post('/admin/exam/content-templates/' + suffix, data={
                    'csrf_token': self.csrf(), 'name': name, 'content': content,
                })
                self.assertEqual(response.status_code, 400)
                self.assertIn(error, response.get_data(as_text=True))
        response = self.client.post('/admin/exam/content-templates/new', data={
            'csrf_token': self.csrf(), 'name': '', 'content': '<script>alert(1)</script>',
        })
        self.assertIn('&lt;script&gt;', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(ExamContentTemplate.query.count(), 1)
            self.assertEqual(db.session.get(ExamContentTemplate, template_id).name, 'Mẫu chung')

    def test_empty_api_missing_records_admin_link_and_startup_are_safe(self):
        self.login('admin')
        self.assertEqual(self.client.get('/exam-content-templates').get_json(), {'templates': []})
        self.assertIn('/admin/exam/content-templates', self.client.get('/admin/exam').get_data(as_text=True))
        self.assertEqual(self.client.get('/admin/exam/content-templates/99999/edit').status_code, 404)
        self.assertEqual(self.client.post('/admin/exam/content-templates/99999/delete', data={
            'csrf_token': self.csrf(),
        }).status_code, 404)
        template_id = self.add_template()
        with self.app.app_context():
            _ensure_new_columns()
            _ensure_new_columns()
            self.assertEqual(db.session.get(ExamContentTemplate, template_id).name, 'Mẫu chung')

    def test_startup_creates_library_table_for_existing_database(self):
        with self.app.app_context():
            db.session.remove()
            ExamContentTemplate.__table__.drop(bind=db.engine)
            _ensure_new_columns()
            self.assertTrue(inspect(db.engine).has_table('exam_content_templates'))
            self.assertTrue(inspect(db.engine).has_table('exams'))

    def test_standalone_migration_is_idempotent_and_preserves_content(self):
        from migrate_add_exam_content_templates import migrate

        engine = create_engine('sqlite:///:memory:')
        try:
            with patch('migrate_add_exam_content_templates.create_engine', return_value=engine), \
                    patch.object(engine, 'dispose'), patch('builtins.print'):
                migrate()
                with engine.begin() as connection:
                    connection.execute(ExamContentTemplate.__table__.insert().values(
                        name='Migration persistence', content='Raw content\n',
                    ))
                migrate()
                with engine.connect() as connection:
                    self.assertEqual(connection.execute(select(
                        ExamContentTemplate.content
                    )).scalar_one(), 'Raw content\n')
        finally:
            engine.dispose()

    def test_real_editor_routes_render_and_preserve_five_question_types(self):
        groups = [
            {'title': 'Trắc nghiệm', 'type': 'mcq', 'instruction': '', 'questions': [
                {'text': 'Một cộng một?', 'options': ['1', '2'], 'correct_index': 1,
                 'explanation': 'Bằng hai.'},
            ]},
            {'title': 'Đúng sai', 'type': 'true_false', 'instruction': '', 'questions': [
                {'text': 'Xét các mệnh đề', 'statements': [
                    {'text': 'Một nhỏ hơn hai', 'correct': True},
                    {'text': 'Hai nhỏ hơn một', 'correct': False},
                ], 'explanation': 'Theo thứ tự số.'},
            ]},
            {'title': 'Trả lời ngắn', 'type': 'short_answer', 'instruction': '', 'questions': [
                {'text': 'Kết quả?', 'accepted_answers': ['2.1', '2,1'], 'explanation': ''},
            ]},
            {'title': 'Tự luận', 'type': 'essay', 'instruction': '', 'questions': [
                {'text': 'Trình bày cách giải', 'explanation': 'Đáp án tham khảo.'},
            ]},
            {'title': 'Tìm lỗi', 'type': 'error_id', 'instruction': '', 'questions': [
                {'text': '[A:She] [*B:are] a teacher.', 'correct_label': 'B',
                 'explanation': 'Use is.'},
            ]},
        ]
        self.login('admin')
        sample_id = self.add_template(content='PHẦN I. Trắc nghiệm\nCâu 1: Một cộng một?')
        for role, new_path, edit_prefix, confirm_path in (
            ('admin', '/admin/exam/create', '/admin/exam/edit/', '/admin/exam/confirm'),
            ('teacher', '/teacher/exams/create?mode=compose', '/teacher/exams/edit/',
             '/teacher/exams/confirm'),
        ):
            with self.subTest(role=role):
                self.login(role)
                with self.app.app_context():
                    exam = Exam(
                        title='Đề có sẵn ' + role, created_by=self.user_ids[role],
                        questions_json=json.dumps({'groups': groups}, ensure_ascii=False),
                    )
                    db.session.add(exam)
                    db.session.commit()
                    exam_id = exam.id
                for path, editing in ((new_path, False), (edit_prefix + str(exam_id), True)):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200, path)
                    page = response.get_data(as_text=True)
                    editor_config = json.loads(re.search(
                        r'<script type="application/json" id="examEditorConfig">(.*?)</script>',
                        page, re.S,
                    )[1])
                    self.assertEqual(editor_config['samplesUrl'], '/exam-content-templates')
                    self.assertEqual(editor_config['groups'], groups if editing else [])
                    self.assertEqual('/admin/exam/content-templates' in page, role == 'admin')
                    self.assertIn('id="rawTextEditor"', page)
                    self.assertIn('Xem trước', page)
                    self.assertIn('Chỉ đọc', page)
                    self.assertIn(
                        f'{role}-exam-editor-draft:{self.user_ids[role]}:'
                        + (str(exam_id) if editing else 'new'),
                        editor_config['draftKey'],
                    )
                    token = re.search(r'name="csrf_token" value="([^"]+)"', page)[1]
                    response = self.client.post(path, data={
                        'csrf_token': token, 'title': 'Đề năm dạng',
                        'groups_json': json.dumps({'groups': groups}, ensure_ascii=False),
                    })
                    self.assertEqual(response.status_code, 200)
                    confirmation = response.get_data(as_text=True)
                    self.assertIn(f'action="{confirm_path}"', confirmation)
                    carried_groups = json.loads(unescape(re.search(
                        r'name="groups_json" value="([^"]+)"', confirmation,
                    )[1]))
                    self.assertEqual(carried_groups, {'groups': groups})
                    self.assertIn(
                        f'name="edit_exam_id" value="{exam_id if editing else ""}"',
                        confirmation,
                    )
                self.assertEqual(
                    self.client.get('/exam-content-templates').get_json()['templates'][0]['id'],
                    sample_id,
                )
                if role == 'teacher':
                    self.assertEqual(
                        self.client.get('/admin/exam/content-templates').status_code, 403,
                    )
                with self.app.app_context():
                    db.session.remove()
                    self.assertEqual(db.session.get(Exam, exam_id).question_groups, groups)
                    self.assertEqual(db.session.get(Exam, exam_id).title, 'Đề có sẵn ' + role)


if __name__ == '__main__':
    unittest.main()
