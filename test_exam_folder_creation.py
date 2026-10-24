"""Regression coverage for creating teacher exams inside a folder."""
import json
import unittest

from app import create_app
from config import Config, config
from extensions import db
from models import Exam, ExamFolder, User


class FolderCreationConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


class ExamFolderCreationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config['folder_creation_test'] = FolderCreationConfig
        cls.app = create_app('folder_creation_test')

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.engine.dispose()
        config.pop('folder_creation_test', None)

    def test_folder_context_survives_creation_and_validation(self):
        with self.app.app_context():
            teacher = User(username='folder-teacher', full_name='Teacher',
                           role='teacher', password_hash='test')
            other = User(username='other-teacher', role='teacher', password_hash='test')
            db.session.add_all([teacher, other])
            db.session.flush()
            folder = ExamFolder(name='Math folder', scope_type='subject', subject='Math',
                                created_by=teacher.id)
            forbidden = ExamFolder(name='Other folder', scope_type='subject', subject='Math',
                                   created_by=other.id)
            db.session.add_all([folder, forbidden])
            db.session.commit()
            client = self.app.test_client()
            with client.session_transaction() as session:
                session['_user_id'] = str(teacher.id)
                session['_fresh'] = True
            folder_id = folder.id
            create_url = f'/teacher/exams/create?folder_id={folder_id}'
            compose_url = f'/teacher/exams/create?mode=compose&folder_id={folder_id}'
            self.assertIn(f'folder_id={folder_id}', client.get(create_url).get_data(as_text=True))
            self.assertEqual(client.get(compose_url).status_code, 200)
            self.assertEqual(client.get(
                f'/teacher/exams/create?folder_id={forbidden.id}'
            ).status_code, 404)
            groups = [{'title': 'Section 1', 'type': 'mcq', 'questions': [
                {'text': 'Question?', 'options': ['A', 'B'], 'correct_index': 0},
            ]}]
            data = {'title': 'Folder exam', 'groups_json': json.dumps({'groups': groups})}
            response = client.post(compose_url, data=data)
            self.assertEqual(response.status_code, 200)
            self.assertRegex(response.get_data(as_text=True),
                             rf'<option value="{folder_id}"\s+selected>')
            data.update(folder_id=str(folder_id), subject='Math', is_draft='draft',
                        section_points_0='10', question_points_0_0='1',
                        scoring_mode='section_custom', duration_minutes='invalid')
            response = client.post('/teacher/exams/confirm', data=data)
            self.assertEqual(response.status_code, 200)
            self.assertRegex(response.get_data(as_text=True),
                             rf'<option value="{folder_id}"\s+selected>')
            data['duration_minutes'] = '40'
            response = client.post('/teacher/exams/confirm', data=data)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.location, f'/teacher/exams?folder_id={folder_id}')
            saved = Exam.query.filter_by(title='Folder exam').one()
            self.assertEqual(saved.folder_id, folder_id)
            self.assertEqual(saved.allow_attempts, 0)

    def test_teacher_edit_save_button_is_in_jump_bar_and_still_saves(self):
        with self.app.app_context():
            teacher = User(username='editor-teacher', full_name='Editor',
                           role='teacher', password_hash='test')
            db.session.add(teacher)
            db.session.flush()
            groups = [{'title': 'Essay', 'type': 'essay', 'questions': [{'text': 'Explain'}]}]
            exam = Exam(title='Edit exam', created_by=teacher.id,
                        questions_json=json.dumps({'groups': groups}))
            db.session.add(exam)
            db.session.commit()
            client = self.app.test_client()
            with client.session_transaction() as session:
                session['_user_id'] = str(teacher.id)
                session['_fresh'] = True
            url = f'/teacher/exams/edit/{exam.id}'
            response = client.get(url)
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertEqual(html.count('name="quick_save"'), 2)
            self.assertLess(html.index('id="examJumpBar"'), html.index('name="quick_save"'))
            self.assertLess(html.index('name="quick_save"'), html.index('id="examJumpHint"'))
            self.assertLess(html.index('id="examSampleStatus"'), html.rindex('name="quick_save"'))
            self.assertLess(html.rindex('name="quick_save"'), html.index('id="examEditorConfig"'))
            response = client.post(url, data={
                'title': 'Updated title', 'groups_json': json.dumps({'groups': groups}),
                'quick_save': '1',
            })
            self.assertEqual(response.status_code, 302)
            db.session.refresh(exam)
            self.assertEqual(exam.title, 'Updated title')
            new_html = client.get('/teacher/exams/create?mode=compose').get_data(as_text=True)
            self.assertNotIn('name="quick_save"', new_html)
            self.assertIn('Cấu hình', new_html)
