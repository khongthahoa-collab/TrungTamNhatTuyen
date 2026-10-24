"""Deliver browser push notifications for newly assigned exams."""
import json

from flask import current_app, url_for
from pywebpush import WebPushException, webpush
from requests.exceptions import RequestException

from extensions import db
from models import (
    Class, Enrollment, Notification, PushSubscription, Student, User, UserRole,
)
from services.push_subscription_service import push_configuration


def exam_assignment_user_ids(exam):
    from blueprints.exams_shared import exam_is_assigned_to_student

    students = Student.query.join(User, User.id == Student.user_id).filter(
        Student.is_active.is_(True),
        Student.is_deleted.is_(False),
        User.role == UserRole.STUDENT,
        User.is_active.is_(True),
        User.is_deleted.is_(False),
    ).all()
    if not students:
        return set()

    student_ids = [student.id for student in students]
    classes_by_student = {}
    for student_id, class_id in db.session.query(
        Enrollment.student_id, Enrollment.class_id
    ).join(Class, Class.id == Enrollment.class_id).filter(
        Enrollment.student_id.in_(student_ids),
        Enrollment.is_active.is_(True),
        Class.is_active.is_(True),
    ).all():
        classes_by_student.setdefault(student_id, set()).add(class_id)

    teacher_class_ids = None
    if exam.creator and exam.creator.role == UserRole.TEACHER:
        from blueprints.teacher import _teacher_score_class_ids

        teacher = exam.creator.teacher_profile
        teacher_class_ids = _teacher_score_class_ids(teacher) if teacher else set()

    return {
        student.user_id
        for student in students
        if exam_is_assigned_to_student(
            exam,
            student,
            active_class_ids=classes_by_student.get(student.id, set()),
            teacher_class_ids=teacher_class_ids,
        )
    }


def _send_push(subscription, payload):
    try:
        response = webpush(
            subscription_info={
                'endpoint': subscription.endpoint,
                'keys': {
                    'p256dh': subscription.p256dh_key,
                    'auth': subscription.auth_key,
                },
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=current_app.config['WEB_PUSH_VAPID_PRIVATE_KEY'],
            vapid_claims={
                'sub': current_app.config['WEB_PUSH_VAPID_CLAIMS_EMAIL'],
            },
            timeout=5,
            ttl=86400,
        )
    except (WebPushException, RequestException, ValueError) as exc:
        status_code = getattr(getattr(exc, 'response', None), 'status_code', None)
        if status_code in (404, 410):
            db.session.delete(subscription)
            return True
        current_app.logger.warning(
            'Web Push delivery failed for subscription %s (HTTP %s): %s',
            subscription.id, status_code or 'unknown', exc,
        )
        return False

    if response.status_code in (404, 410):
        db.session.delete(subscription)
        return True
    return False


def notify_exam_assignment(exam, exclude_user_ids=None):
    """Notify students currently targeted by a published exam, optionally excluding existing assignees."""
    if not push_configuration()['available']:
        current_app.logger.warning(
            'Exam Web Push was skipped because VAPID keys are not configured.'
        )
        return 0

    recipient_ids = exam_assignment_user_ids(exam) - set(exclude_user_ids or ())
    if not recipient_ids:
        return 0

    link = url_for('student.exam_take', exam_id=exam.id)
    payload = {
        'title': 'Đề thi mới được giao',
        'body': f'Bạn có đề thi mới: {exam.title}',
        'url': link,
        'tag': f'exam-assignment-{exam.id}',
    }
    subscriptions = PushSubscription.query.filter(
        PushSubscription.user_id.in_(recipient_ids)
    ).all()
    removed_subscriptions = False
    for subscription in subscriptions:
        removed_subscriptions = _send_push(subscription, payload) or removed_subscriptions
    if removed_subscriptions:
        db.session.commit()
    return len(recipient_ids)


def notify_teacher_essay_to_grade(exam, attempt):
    """Alert the teacher who can grade an essay-bearing submission for their own exam."""
    teacher_user = exam.creator
    if (
        not teacher_user
        or (
            teacher_user.role != UserRole.TEACHER
            and not teacher_user.is_teacher_linked
        )
        or not teacher_user.is_active
        or teacher_user.is_deleted
        or not attempt.result.get('pending_essay_count', 0)
    ):
        return False

    link = url_for(
        'teacher.exams_attempt_detail',
        exam_id=exam.id,
        attempt_id=attempt.id,
    )
    body = (
        f'{attempt.student.full_name if attempt.student else "Học sinh"} '
        f'đã nộp đề "{exam.title}", còn '
        f'{attempt.result["pending_essay_count"]} câu tự luận cần chấm.'
    )
    db.session.add(Notification(
        user_id=teacher_user.id,
        title='Bài thi cần chấm tự luận',
        body=body,
        notif_type='info',
        link=link,
    ))
    db.session.commit()

    if not push_configuration()['available']:
        current_app.logger.warning(
            'Essay grading notification was saved in-app, but Web Push was skipped because VAPID keys are not configured.'
        )
        return True

    payload = {
        'title': 'Bài thi cần chấm tự luận',
        'body': body,
        'url': link,
        'tag': f'essay-grading-{exam.id}-{attempt.id}',
    }
    subscriptions = PushSubscription.query.filter_by(user_id=teacher_user.id).all()
    removed_subscriptions = False
    for subscription in subscriptions:
        removed_subscriptions = _send_push(subscription, payload) or removed_subscriptions
    if removed_subscriptions:
        db.session.commit()
    return True
