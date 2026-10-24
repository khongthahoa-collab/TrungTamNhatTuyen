"""Private essay uploads: access control, limits, submission and lifecycle."""
import io
import json
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

from PIL import Image
from flask import g

from app import create_app
from config import Config, config
from extensions import db
from models import EssayImage, Exam, ExamAttempt, PermissionGroup, Student, User
from services.essay_images import image_path, process_image


class EssayImageTestConfig(Config):
    TESTING = True
    SECRET_KEY = 'essay-image-test'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WEB_PUSH_VAPID_PUBLIC_KEY = ''
    WEB_PUSH_VAPID_PRIVATE_KEY = ''


class EssayImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config['essay_images_test'] = EssayImageTestConfig
        cls.app = create_app('essay_images_test')

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.engine.dispose()
        config.pop('essay_images_test', None)

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.directory = tempfile.TemporaryDirectory()
        self.app.config['ESSAY_IMAGE_FOLDER'] = str(Path(self.directory.name) / 'private')
        self.app.config['UPLOAD_FOLDER'] = str(Path(self.directory.name) / 'public')
        self.client = self.app.test_client()
        self.teacher = self.user('teacher', 'teacher')
        self.other_teacher = self.user('other-teacher', 'teacher')
        self.parent = self.user('parent', 'parent')
        self.other_parent = self.user('other-parent', 'parent')
        self.student_user = self.user('student', 'student')
        self.other_student = self.user('other-student', 'student')
        self.admin = self.user('admin', 'admin', is_master=True)
        denied_group = PermissionGroup(name='No exams', permissions='{"exams":"deny"}')
        self.denied_admin = self.user('denied-admin', 'admin', permission_group=denied_group)
        self.student = Student(full_name='Student', level='primary',
                               user_id=self.student_user.id, parent_user_id=self.parent.id)
        self.stranger = Student(full_name='Stranger', level='primary',
                                user_id=self.other_student.id)
        db.session.add_all([self.student, self.stranger])
        db.session.flush()
        self.groups = [
            {'title': 'Essay', 'type': 'essay', 'questions': [
                {'text': 'Explain 1'}, {'text': 'Explain 2'},
                {'text': 'Explain 3'}, {'text': 'Explain 4'},
            ]},
            {'title': 'MCQ', 'type': 'mcq', 'questions': [
                {'text': 'Choose', 'options': ['A', 'B'], 'correct_index': 0},
            ]},
        ]
        self.exam = Exam(title='Photo exam', created_by=self.teacher.id, is_draft=False,
                         student_ids=str(self.student.id), duration_minutes=40,
                         questions_json=json.dumps({'groups': self.groups}))
        db.session.add(self.exam)
        db.session.commit()
        self.login(self.student_user)
        response = self.client.get(f'/student/exams/{self.exam.id}')
        self.assertEqual(response.status_code, 200)
        self.csrf = re.search(r'name="csrf_token" value="([^"]+)"',
                              response.get_data(as_text=True))[1]
        self.attempt = ExamAttempt.query.one()
        self.upload_url = f'/exam-images/attempts/{self.attempt.id}'

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.directory.cleanup()

    def user(self, username, role, **kwargs):
        user = User(username=username, full_name=username, password_hash='test',
                    role=role, **kwargs)
        db.session.add(user)
        db.session.flush()
        return user

    def login(self, user):
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user.id)
            session['_fresh'] = True
            session.pop('active_role', None)

    def upload(self, field='g0_q1', content=None, filename='answer.png', csrf=True):
        if content is None:
            image = io.BytesIO()
            Image.new('RGB', (2400, 1600), 'white').save(image, format='PNG')
            content = image.getvalue()
        return self.client.post(self.upload_url, data={
            'answer_field': field, 'image': (io.BytesIO(content), filename),
        }, headers={'X-CSRFToken': self.csrf} if csrf else {})

    def test_upload_reencodes_and_private_read_checks_all_roles(self):
        response = self.upload(filename='../../outside.html')
        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        stored = EssayImage.query.one()
        with Image.open(image_path(stored.id)) as image:
            self.assertEqual(image.format, 'JPEG')
            self.assertLessEqual(max(image.size), 2000)
            self.assertFalse(image.getexif())
        self.assertLessEqual(image_path(stored.id).stat().st_size, 1024 * 1024)
        self.assertEqual(len(list(Path(self.app.config['ESSAY_IMAGE_FOLDER']).iterdir())), 2)
        for user, permitted in (
            (self.student_user, True), (self.parent, True), (self.other_student, False),
            (self.other_parent, False), (self.other_teacher, False),
            (self.teacher, False), (self.admin, False),
        ):
            self.login(user)
            result = self.client.get(payload['url'])
            self.assertEqual(result.status_code, 200 if permitted else 403)
            if permitted:
                self.assertIn('no-store', result.headers['Cache-Control'])
                self.assertEqual(result.headers['X-Content-Type-Options'], 'nosniff')
                self.assertEqual(result.mimetype, 'image/jpeg')
                result.close()
        self.attempt.status = 'submitted'
        self.exam.is_shared_with_teachers = True
        db.session.commit()
        for user, expected in ((self.teacher, 200), (self.admin, 200),
                               (self.other_teacher, 403), (self.denied_admin, 403)):
            self.login(user)
            result = self.client.get(payload['thumbnail_url'])
            self.assertEqual(result.status_code, expected)
            result.close()
        with self.client.session_transaction() as session:
            session.clear()
        g.pop('_login_user', None)
        self.assertEqual(self.client.get(payload['url']).status_code, 302)

    def test_exam_routes_share_upload_validation_and_private_reads(self):
        self.upload_url = f'/exam/attempt/{self.attempt.id}/upload-essay-image'
        self.assertEqual(self.upload(csrf=False).status_code, 400)
        self.login(self.other_student)
        self.assertEqual(self.upload().status_code, 403)
        self.login(self.student_user)
        payload = self.upload().get_json()
        self.assertIsNotNone(payload)
        self.assertIn('id', payload)
        url = f'/exam/essay-image/{payload["id"]}'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('private', response.headers['Cache-Control'])
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        response.close()
        self.login(self.other_student)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.login(self.teacher)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.attempt.status = 'submitted'
        db.session.commit()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response.close()
        self.login(self.student_user)
        self.assertEqual(self.upload().status_code, 409)
        self.attempt.status = 'in_progress'
        self.attempt.started_at = datetime.utcnow() - timedelta(hours=2)
        db.session.commit()
        self.assertEqual(self.upload().status_code, 409)
        with self.client.session_transaction() as session:
            session.clear()
        g.pop('_login_user', None)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_invalid_files_fields_and_csrf_are_rejected(self):
        self.assertEqual(self.upload(csrf=False).status_code, 400)
        self.assertEqual(self.upload(content=b'<svg onload="alert(1)"/>',
                                     filename='photo.jpg').status_code, 400)
        self.assertEqual(self.upload(content=b'not an image').status_code, 400)
        self.assertEqual(self.upload('g1_q1').status_code, 400)
        self.assertEqual(self.upload('g0_q99').status_code, 400)
        self.assertEqual(self.upload(content=b'x' * (10 * 1024 * 1024 + 1)).status_code, 400)
        self.assertEqual(EssayImage.query.count(), 0)
        with patch('services.essay_images.MAX_PIXELS', 1):
            self.assertEqual(self.upload().status_code, 400)
        with patch('services.essay_images.MAX_IMAGE_BYTES', 1):
            self.assertEqual(self.upload().status_code, 400)
        self.assertEqual(self.client.delete('/exam-images/' + 'a' * 32).status_code, 400)

    def test_wrong_owner_unassigned_and_expired_attempts_cannot_upload(self):
        for user in (self.other_student, self.other_parent, self.teacher, self.admin):
            self.login(user)
            self.assertEqual(self.upload().status_code, 403)
        self.login(self.student_user)
        self.exam.student_ids = ''
        db.session.commit()
        self.assertEqual(self.upload().status_code, 404)
        self.exam.student_ids = str(self.student.id)
        self.attempt.started_at = datetime.utcnow() - timedelta(hours=2)
        db.session.commit()
        self.assertEqual(self.upload().status_code, 409)
        self.attempt.started_at = datetime.utcnow()
        self.attempt.status = 'submitted'
        db.session.commit()
        self.assertEqual(self.upload().status_code, 409)

    def test_question_attempt_storage_and_hourly_quotas(self):
        for index in range(10):
            response = self.upload(f'g0_q{index // 3 + 1}')
            self.assertEqual(response.status_code, 201)
        self.assertEqual(self.upload('g0_q1').status_code, 400)
        self.assertEqual(self.upload('g0_q4').status_code, 400)
        self.assertEqual(EssayImage.query.count(), 10)
        for image in EssayImage.query.all():
            image.deleted_at = datetime.utcnow()
        db.session.commit()
        for index in range(40):
            db.session.add(EssayImage(
                id=f'{index:032x}', attempt_id=self.attempt.id, student_id=self.student.id,
                answer_field='g0_q1', size_bytes=1, deleted_at=datetime.utcnow(),
            ))
        db.session.commit()
        self.assertEqual(self.upload().status_code, 429)
        EssayImage.query.delete()
        db.session.add(EssayImage(id='f' * 32, attempt_id=self.attempt.id,
                                 student_id=self.student.id, answer_field='g0_q2',
                                 size_bytes=100 * 1024 * 1024))
        db.session.commit()
        self.assertEqual(self.upload().status_code, 400)

    def test_reorder_delete_and_submit_preserve_images_and_grading(self):
        first = self.upload().get_json()
        second = self.upload().get_json()
        order_url = self.upload_url + '/order'
        headers = {'X-CSRFToken': self.csrf}
        self.assertEqual(self.client.post(order_url, json={
            'answer_field': 'g0_q1', 'ids': [second['id'], first['id']],
        }, headers=headers).status_code, 200)
        self.assertEqual(self.client.post(order_url, json={
            'answer_field': 'g0_q1', 'ids': [first['id'], 'bad-id'],
        }, headers=headers).status_code, 400)
        self.assertEqual(self.client.get(f'/student/exams/{self.exam.id}').status_code, 200)
        data = {'csrf_token': self.csrf, 'attempt_id': str(self.attempt.id),
                'g0_q1': 'Written answer'}
        self.assertEqual(self.client.post(
            f'/student/exams/{self.exam.id}/save', data=data,
        ).status_code, 200)
        response = self.client.post(f'/student/exams/{self.exam.id}/submit', data=data)
        self.assertEqual(response.status_code, 302)
        db.session.refresh(self.attempt)
        self.assertEqual(self.attempt.result['pending_essay_count'], 4)
        self.assertEqual(self.client.delete(first['url'], headers=headers).status_code, 409)
        self.assertEqual(self.client.post(order_url, json={
            'answer_field': 'g0_q1', 'ids': [first['id'], second['id']],
        }, headers=headers).status_code, 409)
        html = self.client.get(f'/student/exams/{self.exam.id}/result').get_data(as_text=True)
        self.assertIn(first['thumbnail_url'].replace('&', '&amp;'), html)
        self.assertLess(html.index(second['id']), html.index(first['id']))
        self.login(self.teacher)
        response = self.client.get(
            f'/teacher/exams/{self.exam.id}/attempts/{self.attempt.id}',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(first['id'], response.get_data(as_text=True))
        self.login(self.admin)
        response = self.client.get(
            f'/admin/exam/{self.exam.id}/attempt/{self.attempt.id}/grade',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(first['id'], response.get_data(as_text=True))

    def test_delete_cleanup_and_storage_failure(self):
        payload = self.upload().get_json()
        headers = {'X-CSRFToken': self.csrf}
        self.assertEqual(self.client.delete(payload['url'], headers=headers).status_code, 200)
        self.assertEqual(self.client.get(payload['url']).status_code, 404)
        EssayImage.query.one().deleted_at = datetime.utcnow() - timedelta(hours=2)
        db.session.commit()
        result = self.app.test_cli_runner().invoke(args=['cleanup-essay-images'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(EssayImage.query.count(), 0)
        self.assertFalse(image_path(payload['id']).exists())
        with self.assertLogs(self.app.logger, level='ERROR'):
            with patch('pathlib.Path.open', side_effect=OSError('disk unavailable')):
                self.assertEqual(self.upload().status_code, 503)
        self.assertEqual(EssayImage.query.count(), 0)

    def test_upload_rechecks_status_and_deadline_after_image_processing(self):
        from services.essay_images import process_image as decode

        def submit_while_decoding(upload):
            content = decode(upload)
            self.attempt.status = 'submitted'
            db.session.commit()
            return content

        with patch('blueprints.exam_images.process_image', side_effect=submit_while_decoding):
            self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(EssayImage.query.count(), 0)
        self.attempt.status = 'in_progress'
        db.session.commit()

        def expire_while_decoding(upload):
            content = decode(upload)
            self.attempt.started_at = datetime.utcnow() - timedelta(hours=2)
            db.session.commit()
            return content

        with patch('blueprints.exam_images.process_image', side_effect=expire_while_decoding):
            self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(EssayImage.query.count(), 0)

    def test_submit_uses_the_attempt_displayed_not_another_open_tab(self):
        photo = self.upload().get_json()
        other = ExamAttempt(
            exam_id=self.exam.id, student_id=self.student.id, user_id=self.student_user.id,
            order_json=self.attempt.order_json, started_at=datetime.utcnow() + timedelta(seconds=1),
        )
        db.session.add(other)
        db.session.commit()
        data = {'csrf_token': self.csrf, 'attempt_id': str(self.attempt.id), 'g0_q1': 'Answer'}
        self.assertEqual(self.client.post(
            f'/student/exams/{self.exam.id}/submit', data=data,
        ).status_code, 302)
        db.session.refresh(self.attempt)
        db.session.refresh(other)
        self.assertEqual(self.attempt.status, 'submitted')
        self.assertEqual(other.status, 'in_progress')
        self.assertEqual(EssayImage.query.one().id, photo['id'])

    def test_other_students_cannot_delete_or_reorder_and_reset_removes_records(self):
        payload = self.upload().get_json()
        self.login(self.other_student)
        headers = {'X-CSRFToken': self.csrf}
        self.assertEqual(self.client.delete(payload['url'], headers=headers).status_code, 403)
        self.assertEqual(self.client.post(self.upload_url + '/order', json={
            'answer_field': 'g0_q1', 'ids': [payload['id']],
        }, headers=headers).status_code, 403)
        self.login(self.student_user)
        for field in ([], {}, None):
            self.assertEqual(self.client.post(self.upload_url + '/order', json={
                'answer_field': field, 'ids': [payload['id']],
            }, headers=headers).status_code, 400)
        from blueprints.exams_shared import reset_student_exam_attempts
        count, _name = reset_student_exam_attempts(self.exam, self.student.id, self.teacher.id)
        self.assertEqual(count, 1)
        self.assertEqual(EssayImage.query.count(), 0)
        self.assertEqual(ExamAttempt.query.count(), 0)
        self.assertEqual(self.client.get(payload['url']).status_code, 404)

    def test_abandoned_cleanup_preserves_submitted_images(self):
        abandoned = self.upload().get_json()
        EssayImage.query.one().created_at = datetime.utcnow() - timedelta(days=8)
        self.attempt.started_at = datetime.utcnow() - timedelta(days=8)
        db.session.commit()
        result = self.app.test_cli_runner().invoke(args=['cleanup-essay-images'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(image_path(abandoned['id']).exists())
        self.attempt.started_at = datetime.utcnow()
        db.session.commit()
        submitted = self.upload().get_json()
        EssayImage.query.one().created_at = datetime.utcnow() - timedelta(days=8)
        self.attempt.status = 'submitted'
        db.session.commit()
        result = self.app.test_cli_runner().invoke(args=['cleanup-essay-images'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(EssayImage.query.count(), 1)
        self.assertTrue(image_path(submitted['id']).exists())

    def test_cleanup_keeps_recent_deletions_and_only_removes_old_orphan_images(self):
        payload = self.upload().get_json()
        image = EssayImage.query.one()
        now = datetime.utcnow()
        image.created_at = now - timedelta(days=8)
        image.deleted_at = now - timedelta(minutes=30)
        self.attempt.status = 'submitted'
        db.session.commit()
        root = Path(self.app.config['ESSAY_IMAGE_FOLDER'])
        old_files = [root / ('a' * 32 + suffix) for suffix in ('.jpg', '-thumb.jpg')]
        recent_orphan = root / ('b' * 32 + '.jpg')
        unrelated = root / 'keep.txt'
        for path in old_files + [recent_orphan, unrelated]:
            path.write_bytes(b'orphan')
        for path in old_files + [unrelated, image_path(image.id)]:
            os.utime(path, (now.timestamp() - 2 * 86400,) * 2)
        result = self.app.test_cli_runner().invoke(args=['cleanup-essay-images'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(EssayImage.query.count(), 1)
        self.assertTrue(image_path(payload['id']).exists(), 'known old files must not be orphans')
        self.assertTrue(recent_orphan.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue(all(not path.exists() for path in old_files))
        self.assertIn('2 orphan files', result.output)
        result = self.app.test_cli_runner().invoke(args=['cleanup-essay-images'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('0 orphan files', result.output)

    def test_cleanup_failure_is_not_reported_as_success(self):
        payload = self.upload().get_json()
        EssayImage.query.one().deleted_at = datetime.utcnow() - timedelta(hours=2)
        db.session.commit()
        with patch('pathlib.Path.unlink', side_effect=OSError('permission denied')):
            result = self.app.test_cli_runner().invoke(args=['cleanup-essay-images'])
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(EssayImage.query.count(), 1)
        self.assertTrue(image_path(payload['id']).exists())

    def test_static_gif_heic_and_jpeg_size_boundary_are_rejected(self):
        gif = io.BytesIO()
        Image.new('RGB', (20, 20), 'white').save(gif, format='GIF')
        self.assertEqual(self.upload(content=gif.getvalue(), filename='photo.jpg').status_code, 400)
        self.assertEqual(self.upload(content=b'\x00\x00\x00\x18ftypheic', filename='photo.heic').status_code, 400)
        jpeg_size = len(process_image(self._source_image())[0])
        with patch('services.essay_images.MAX_IMAGE_BYTES', jpeg_size):
            self.assertEqual(self.upload().status_code, 400, 'stored JPEG must be strictly under its limit')

    def _source_image(self):
        from werkzeug.datastructures import FileStorage
        source = io.BytesIO()
        Image.new('RGB', (2400, 1600), 'white').save(source, format='PNG')
        source.seek(0)
        return FileStorage(stream=source)

    def test_decoder_rejects_animation_and_strips_metadata(self):
        from werkzeug.datastructures import FileStorage
        frames = [Image.new('RGB', (20, 20), color) for color in ('white', 'black')]
        animated = io.BytesIO()
        frames[0].save(animated, format='WEBP', save_all=True, append_images=frames[1:])
        animated.seek(0)
        with self.assertRaises(ValueError):
            process_image(FileStorage(stream=animated))
        original = io.BytesIO()
        exif = Image.Exif()
        exif[270] = '<script>private metadata</script>'
        frames[0].save(original, format='JPEG', exif=exif)
        original.seek(0)
        content, _thumbnail = process_image(FileStorage(stream=original))
        with Image.open(io.BytesIO(content)) as decoded:
            self.assertFalse(decoded.getexif())
