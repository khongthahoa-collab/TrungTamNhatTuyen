import hashlib
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, jsonify, request
from flask_login import current_user, login_required
from extensions import db

from models import Exam, PushSubscription
from blueprints import parent

student_bp = Blueprint('student', __name__)


def _current_student():
    if (not current_user.is_authenticated or not current_user.is_active
            or not current_user.is_student):
        abort(403)
    student = current_user.student_profile
    if not student or not student.is_active or student.is_deleted:
        abort(403)
    return student


def _assigned_exam_or_404(exam_id):
    student = _current_student()
    exam = Exam.query.get_or_404(exam_id)
    if exam not in parent._exams_for_student(student):
        abort(404)
    return student, exam


@student_bp.route('/exams')
@login_required
def exams_list():
    student = _current_student()
    return parent.exams(student.id)


@student_bp.route('/exams/<int:exam_id>')
@login_required
def exam_take(exam_id):
    student, _exam = _assigned_exam_or_404(exam_id)
    return parent.exam_take(student.id, exam_id)


@student_bp.route('/exams/<int:exam_id>/submit', methods=['POST'])
@login_required
def exam_submit(exam_id):
    student, _exam = _assigned_exam_or_404(exam_id)
    return parent.exam_submit(student.id, exam_id)


@student_bp.route('/exams/<int:exam_id>/save', methods=['POST'])
@login_required
def exam_save_progress(exam_id):
    student, _exam = _assigned_exam_or_404(exam_id)
    return parent.exam_save_progress(student.id, exam_id)


@student_bp.route('/exams/<int:exam_id>/result')
@login_required
def exam_result(exam_id):
    student, _exam = _assigned_exam_or_404(exam_id)
    return parent.exam_result(student.id, exam_id)


@student_bp.route('/push/public-key')
@login_required
def push_public_key():
    _current_student()
    public_key = current_app.config.get('WEB_PUSH_VAPID_PUBLIC_KEY', '')
    available = bool(
        public_key and current_app.config.get('WEB_PUSH_VAPID_PRIVATE_KEY')
    )
    return jsonify({'available': available, 'public_key': public_key if available else ''})


@student_bp.route('/push/subscriptions', methods=['POST', 'DELETE'])
@login_required
def push_subscription():
    _current_student()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'Dữ liệu đăng ký thông báo không hợp lệ.'}), 400

    endpoint = body.get('endpoint')
    if not isinstance(endpoint, str) or len(endpoint) > 4096:
        return jsonify({'error': 'Địa chỉ đăng ký thông báo không hợp lệ.'}), 400
    try:
        parsed_endpoint = urlsplit(endpoint)
        endpoint_port = parsed_endpoint.port
    except ValueError:
        return jsonify({'error': 'Địa chỉ đăng ký thông báo không hợp lệ.'}), 400
    allowed_push_hosts = {
        'fcm.googleapis.com',
        'updates.push.services.mozilla.com',
        'push.services.mozilla.com',
        'web.push.apple.com',
    }
    if (
        parsed_endpoint.scheme != 'https'
        or not parsed_endpoint.hostname
        or parsed_endpoint.hostname.lower() not in allowed_push_hosts
        or endpoint_port not in (None, 443)
        or parsed_endpoint.username
        or parsed_endpoint.password
    ):
        return jsonify({'error': 'Địa chỉ đăng ký thông báo không hợp lệ.'}), 400
    endpoint_hash = hashlib.sha256(endpoint.encode('utf-8')).hexdigest()

    if request.method == 'DELETE':
        PushSubscription.query.filter_by(
            user_id=current_user.id, endpoint_hash=endpoint_hash
        ).delete(synchronize_session=False)
        db.session.commit()
        return jsonify({'ok': True})

    if not (
        current_app.config.get('WEB_PUSH_VAPID_PUBLIC_KEY')
        and current_app.config.get('WEB_PUSH_VAPID_PRIVATE_KEY')
    ):
        return jsonify({'error': 'Thông báo đẩy chưa được cấu hình.'}), 503

    keys = body.get('keys')
    if not isinstance(keys, dict):
        return jsonify({'error': 'Thiếu khóa mã hóa của trình duyệt.'}), 400
    p256dh_key, auth_key = keys.get('p256dh'), keys.get('auth')
    if not (
        isinstance(p256dh_key, str) and 0 < len(p256dh_key) <= 256
        and isinstance(auth_key, str) and 0 < len(auth_key) <= 128
    ):
        return jsonify({'error': 'Khóa mã hóa của trình duyệt không hợp lệ.'}), 400

    subscription = PushSubscription.query.filter_by(endpoint_hash=endpoint_hash).first()
    if subscription is None:
        subscription = PushSubscription(
            endpoint=endpoint,
            endpoint_hash=endpoint_hash,
        )
        db.session.add(subscription)
    subscription.user_id = current_user.id
    subscription.endpoint = endpoint
    subscription.p256dh_key = p256dh_key
    subscription.auth_key = auth_key
    db.session.commit()
    return jsonify({'ok': True})
