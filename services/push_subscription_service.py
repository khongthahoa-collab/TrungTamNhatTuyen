"""Shared validation and persistence for browser push subscriptions."""
import hashlib
from urllib.parse import urlsplit

from flask import current_app

from extensions import db
from models import PushSubscription

ALLOWED_PUSH_HOSTS = {
    'fcm.googleapis.com',
    'updates.push.services.mozilla.com',
    'push.services.mozilla.com',
    'web.push.apple.com',
}


def push_configuration():
    public_key = current_app.config.get('WEB_PUSH_VAPID_PUBLIC_KEY', '')
    available = bool(
        public_key and current_app.config.get('WEB_PUSH_VAPID_PRIVATE_KEY')
    )
    return {'available': available, 'public_key': public_key if available else ''}


def _validated_endpoint(payload):
    endpoint = payload.get('endpoint')
    if not isinstance(endpoint, str) or len(endpoint) > 4096:
        raise ValueError('Địa chỉ đăng ký thông báo không hợp lệ.')
    try:
        parsed_endpoint = urlsplit(endpoint)
        endpoint_port = parsed_endpoint.port
    except ValueError as exc:
        raise ValueError('Địa chỉ đăng ký thông báo không hợp lệ.') from exc

    if (
        parsed_endpoint.scheme != 'https'
        or not parsed_endpoint.hostname
        or parsed_endpoint.hostname.lower() not in ALLOWED_PUSH_HOSTS
        or endpoint_port not in (None, 443)
        or parsed_endpoint.username
        or parsed_endpoint.password
    ):
        raise ValueError('Địa chỉ đăng ký thông báo không hợp lệ.')
    return endpoint


def remove_push_subscription(user_id, payload):
    endpoint = _validated_endpoint(payload)
    endpoint_hash = hashlib.sha256(endpoint.encode('utf-8')).hexdigest()
    PushSubscription.query.filter_by(
        user_id=user_id, endpoint_hash=endpoint_hash
    ).delete(synchronize_session=False)
    db.session.commit()


def save_push_subscription(user_id, payload):
    if not push_configuration()['available']:
        raise ValueError('Thông báo đẩy chưa được cấu hình.')
    endpoint = _validated_endpoint(payload)
    keys = payload.get('keys')
    if not isinstance(keys, dict):
        raise ValueError('Thiếu khóa mã hóa của trình duyệt.')
    p256dh_key, auth_key = keys.get('p256dh'), keys.get('auth')
    if not (
        isinstance(p256dh_key, str) and 0 < len(p256dh_key) <= 256
        and isinstance(auth_key, str) and 0 < len(auth_key) <= 128
    ):
        raise ValueError('Khóa mã hóa của trình duyệt không hợp lệ.')

    endpoint_hash = hashlib.sha256(endpoint.encode('utf-8')).hexdigest()
    subscription = PushSubscription.query.filter_by(endpoint_hash=endpoint_hash).first()
    if subscription is None:
        subscription = PushSubscription(
            endpoint=endpoint,
            endpoint_hash=endpoint_hash,
        )
        db.session.add(subscription)
    subscription.user_id = user_id
    subscription.endpoint = endpoint
    subscription.p256dh_key = p256dh_key
    subscription.auth_key = auth_key
    db.session.commit()
