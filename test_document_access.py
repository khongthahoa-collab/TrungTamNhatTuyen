"""Regression checks for object permissions on both document-download routes."""
from pathlib import Path
import tempfile
import unittest

from flask import g

from app import create_app
from config import Config, config
from extensions import db
from models import Class, ClassDocument, Course, Enrollment, PermissionGroup, Student, Teacher, User


class DocumentAccessConfig(Config):
    TESTING = True
    SECRET_KEY = 'document-access-test'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


class DocumentAccessTests(unittest.TestCase):
    def test_downloads_enforce_class_relationships_and_module_permissions(self):
        config['document_access_test'] = DocumentAccessConfig
        app = create_app('document_access_test')
        try:
            with app.app_context(), tempfile.TemporaryDirectory() as directory:
                app.config['UPLOAD_FOLDER'] = directory
                Path(directory, 'document.pdf').write_bytes(b'Synthetic class document')
                users = {}
                for name, role in (
                    ('student', 'student'), ('other-student', 'student'),
                    ('parent', 'parent'), ('other-parent', 'parent'),
                    ('teacher', 'teacher'), ('other-teacher', 'teacher'),
                    ('master', 'admin'), ('denied', 'admin'), ('reader', 'admin'),
                ):
                    users[name] = User(username=name, role=role, password_hash='test',
                                       is_master=name == 'master')
                users['denied'].permission_group = PermissionGroup(
                    name='Denied', permissions='{"documents":"deny"}',
                )
                users['reader'].permission_group = PermissionGroup(
                    name='Reader', permissions='{"documents":"read"}',
                )
                db.session.add_all(users.values())
                db.session.flush()
                profile = Teacher(user_id=users['teacher'].id)
                db.session.add(profile)
                db.session.flush()
                course = Course(name='Course')
                db.session.add(course)
                db.session.flush()
                class_ = Class(name='Class', course_id=course.id, primary_teacher_id=profile.id)
                student = Student(full_name='Student', level='primary',
                                  user_id=users['student'].id, parent_user_id=users['parent'].id)
                db.session.add_all([class_, student])
                db.session.flush()
                enrollment = Enrollment(class_id=class_.id, student_id=student.id)
                document = ClassDocument(
                    class_id=class_.id, uploaded_by=users['master'].id,
                    title='Class document', stored_filename='document.pdf',
                    original_filename='original.pdf',
                )
                db.session.add_all([enrollment, document])
                db.session.commit()
                client = app.test_client()

                def login(name):
                    g.pop('_login_user', None)
                    with client.session_transaction() as session:
                        session.clear()
                        session['_user_id'] = str(users[name].id)
                        session['_fresh'] = True

                routes = (f'/admin/documents/{document.id}/download',
                          f'/parent/documents/{document.id}/download')
                for name, expected in (
                    ('student', (200, 403)), ('other-student', (403, 403)),
                    ('parent', (200, 200)), ('other-parent', (403, 403)),
                    ('teacher', (200, 200)), ('other-teacher', (403, 403)),
                    ('master', (200, 200)), ('denied', (403, 403)), ('reader', (200, 200)),
                ):
                    login(name)
                    for route, status in zip(routes, expected):
                        with self.subTest(user=name, route=route):
                            response = client.get(route)
                            self.assertEqual(response.status_code, status)
                            if status == 200:
                                self.assertEqual(response.data, b'Synthetic class document')
                                self.assertIn('no-store', response.headers['Cache-Control'])
                            response.close()
                enrollment.is_active = False
                db.session.commit()
                for name in ('student', 'parent'):
                    login(name)
                    self.assertEqual(client.get(routes[0]).status_code, 403)
                document.is_active = False
                db.session.commit()
                login('master')
                self.assertEqual(client.get(routes[0]).status_code, 404)
                self.assertEqual(client.get(routes[1]).status_code, 404)
                db.session.remove()
                db.engine.dispose()
        finally:
            config.pop('document_access_test', None)
