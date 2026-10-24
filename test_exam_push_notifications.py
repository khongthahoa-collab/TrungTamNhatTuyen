"""Tests for PWA push registration and newly assigned exam notifications."""
import hashlib
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from flask import Flask, render_template
from flask_login import login_user

from blueprints.student import student_bp
from blueprints.teacher import teacher_bp
from blueprints.exams_shared import publish_exam
from blueprints.auth import auth_bp
from blueprints.public import public_bp
from extensions import db, login_manager
from models import (
    Class, Course, Enrollment, Exam, ExamAttempt, Notification, PushSubscription,
    School, Student, User, UserRole,
)
from services.exam_push_notifications import (
    exam_assignment_user_ids, notify_exam_assignment, notify_teacher_essay_to_grade,
)


class ExamPushNotificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            SECRET_KEY='test-secret',
            TESTING=True,
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            WEB_PUSH_VAPID_PUBLIC_KEY='test-public-key',
            WEB_PUSH_VAPID_PRIVATE_KEY='test-private-key',
            WEB_PUSH_VAPID_CLAIMS_EMAIL='mailto:test@example.com',
        )
        db.init_app(cls.app)
        login_manager.init_app(cls.app)
        cls.app.register_blueprint(student_bp, url_prefix='/student')
        cls.app.register_blueprint(teacher_bp, url_prefix='/teacher')
        cls.app.register_blueprint(public_bp)
        cls.app.register_blueprint(auth_bp, url_prefix='/auth')
        cls.app.jinja_env.globals['csrf_token'] = lambda: 'test-token'

        @login_manager.user_loader
        def load_user(user_id):
            return db.session.get(User, int(user_id))

    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _user(self, username, role=UserRole.STUDENT):
        user = User(
            full_name=username,
            username=username,
            password_hash='test',
            role=role,
            is_active=True,
            is_deleted=False,
        )
        db.session.add(user)
        db.session.flush()
        return user

    def test_exam_assignment_push_uses_union_of_class_school_and_student_targets(self):
        admin = self._user('admin', UserRole.ADMIN)
        student_users = [self._user(f'student-{i}') for i in range(1, 4)]
        first_school = School(name='First School')
        second_school = School(name='Second School')
        course = Course(name='Math')
        db.session.add_all([first_school, second_school, course])
        db.session.flush()
        class_ = Class(name='Class A', course_id=course.id)
        db.session.add(class_)
        db.session.flush()

        students = [
            Student(
                full_name=user.full_name,
                level='primary',
                user_id=user.id,
                school_id=first_school.id if index < 2 else second_school.id,
            )
            for index, user in enumerate(student_users)
        ]
        db.session.add_all(students)
        db.session.flush()
        db.session.add(Enrollment(student_id=students[0].id, class_id=class_.id))
        exam = Exam(
            title='New exam',
            created_by=admin.id,
            class_ids=str(class_.id),
            school_ids=str(first_school.id),
            student_ids=str(students[2].id),
            is_draft=False,
        )
        db.session.add(exam)
        for user in student_users:
            endpoint = f'https://fcm.googleapis.com/fcm/send/{user.id}'
            db.session.add(PushSubscription(
                user_id=user.id,
                endpoint=endpoint,
                endpoint_hash=hashlib.sha256(endpoint.encode()).hexdigest(),
                p256dh_key='public-key',
                auth_key='auth-key',
            ))
        db.session.commit()

        self.assertEqual(exam_assignment_user_ids(exam), {user.id for user in student_users})
        with patch(
            'services.exam_push_notifications.webpush',
            return_value=SimpleNamespace(status_code=201),
        ) as send:
            with self.app.test_request_context('/teacher/exams/confirm'):
                notified = notify_exam_assignment(
                    exam, exclude_user_ids={student_users[1].id},
                )

        self.assertEqual(notified, 2)
        endpoints = {
            call.kwargs['subscription_info']['endpoint']
            for call in send.call_args_list
        }
        self.assertEqual(endpoints, {
            f'https://fcm.googleapis.com/fcm/send/{student_users[0].id}',
            f'https://fcm.googleapis.com/fcm/send/{student_users[2].id}',
        })

    def test_student_can_register_and_remove_own_push_subscription(self):
        user = self._user('student')
        db.session.add(Student(
            full_name=user.full_name,
            level='primary',
            user_id=user.id,
        ))
        db.session.commit()
        endpoint = 'https://fcm.googleapis.com/fcm/send/device-token'
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user.id)
            session['_fresh'] = True

        response = self.client.post('/student/push/subscriptions', json={
            'endpoint': endpoint,
            'keys': {'p256dh': 'browser-key', 'auth': 'browser-auth'},
        })

        self.assertEqual(response.status_code, 200)
        subscription = PushSubscription.query.one()
        self.assertEqual(subscription.user_id, user.id)

        response = self.client.delete(
            '/student/push/subscriptions', json={'endpoint': endpoint},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(PushSubscription.query.count(), 0)

    def test_public_key_endpoint_does_not_expose_private_key(self):
        user = self._user('student')
        db.session.add(Student(
            full_name=user.full_name,
            level='primary',
            user_id=user.id,
        ))
        db.session.commit()
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user.id)
            session['_fresh'] = True

        response = self.client.get('/student/push/public-key')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {
            'available': True,
            'public_key': 'test-public-key',
        })

    def test_publishing_exam_triggers_assignment_push(self):
        admin = self._user('admin', UserRole.ADMIN)
        exam = Exam(
            title='Draft exam',
            created_by=admin.id,
            class_ids='7',
            is_draft=True,
        )
        db.session.add(exam)
        db.session.commit()

        with patch('services.exam_push_notifications.notify_exam_assignment') as notify:
            published, _message = publish_exam(exam, admin.id)

        self.assertTrue(published)
        notify.assert_called_once_with(exam)

    def test_teacher_can_register_push_and_get_pending_essay_alert(self):
        teacher = self._user('teacher', UserRole.TEACHER)
        student_user = self._user('student')
        student = Student(
            full_name=student_user.full_name,
            level='primary',
            user_id=student_user.id,
        )
        exam = Exam(
            title='Essay exam',
            created_by=teacher.id,
            is_draft=False,
        )
        db.session.add_all([student, exam])
        db.session.flush()
        attempt = ExamAttempt(
            exam_id=exam.id,
            user_id=student_user.id,
            student_id=student.id,
            status='submitted',
            result_json='{"pending_essay_count": 2}',
        )
        endpoint = 'https://fcm.googleapis.com/fcm/send/teacher-device'
        db.session.add_all([
            attempt,
            PushSubscription(
                user_id=teacher.id,
                endpoint=endpoint,
                endpoint_hash=hashlib.sha256(endpoint.encode()).hexdigest(),
                p256dh_key='public-key',
                auth_key='auth-key',
            ),
        ])
        db.session.commit()
        with self.client.session_transaction() as session:
            session['_user_id'] = str(teacher.id)
            session['_fresh'] = True

        response = self.client.post('/teacher/push/subscriptions', json={
            'endpoint': endpoint,
            'keys': {'p256dh': 'public-key', 'auth': 'auth-key'},
        })
        self.assertEqual(response.status_code, 200)

        with patch(
            'services.exam_push_notifications.webpush',
            return_value=SimpleNamespace(status_code=201),
        ) as send:
            with self.app.test_request_context('/student/exams'):
                notified = notify_teacher_essay_to_grade(exam, attempt)

        self.assertTrue(notified)
        alert = Notification.query.filter_by(user_id=teacher.id).one()
        self.assertEqual(alert.title, 'Bài thi cần chấm tự luận')
        self.assertIn('còn 2 câu tự luận cần chấm', alert.body)
        self.assertIn(f'/teacher/exams/{exam.id}/attempts/{attempt.id}', alert.link)
        self.assertEqual(send.call_args.kwargs['subscription_info']['endpoint'], endpoint)

    def test_teacher_pwa_template_includes_push_opt_in(self):
        teacher = self._user('teacher', UserRole.TEACHER)
        db.session.commit()

        with self.app.test_request_context('/teacher/'):
            login_user(teacher)
            html = render_template('teacher/base.html')

        self.assertIn('/teacher/push/public-key', html)
        self.assertIn(
            'Bật thông báo để biết khi có học sinh nộp bài cần chấm tự luận.',
            html,
        )
        self.assertIn('/static/js/student-push.js', html)

    def test_student_cannot_register_arbitrary_push_endpoint(self):
        user = self._user('student')
        db.session.add(Student(
            full_name=user.full_name,
            level='primary',
            user_id=user.id,
        ))
        db.session.commit()
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user.id)
            session['_fresh'] = True

        response = self.client.post('/student/push/subscriptions', json={
            'endpoint': 'https://localhost/internal',
            'keys': {'p256dh': 'browser-key', 'auth': 'browser-auth'},
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(PushSubscription.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
