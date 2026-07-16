import secrets
from datetime import datetime
from flask import request, g
from extensions import db
from models import User
from blueprints.api import api_bp, api_ok, api_error, api_login_required


@api_bp.route('/auth/login', methods=['POST'])
def login():
    body = request.get_json(silent=True) or request.form
    identifier = (body.get('phone_or_username') or body.get('phone') or body.get('username') or '').strip()
    password = body.get('password') or ''

    if not identifier or not password:
        return api_error('Vui lòng nhập tên đăng nhập/SĐT và mật khẩu.', 400, code='validation_error')

    user = User.query.filter(
        (User.phone == identifier) | (User.username == identifier)
    ).first()

    if not user or not user.check_password(password) or not user.is_active or user.is_deleted:
        return api_error('Thông tin đăng nhập không đúng.', 401, code='invalid_credentials')

    user.api_token = secrets.token_hex(32)
    user.last_login = datetime.utcnow()
    db.session.commit()

    return api_ok({'token': user.api_token, 'user': user.to_dict()})


@api_bp.route('/auth/logout', methods=['POST'])
@api_login_required
def logout():
    g.api_user.api_token = None
    db.session.commit()
    return api_ok({'message': 'Đã đăng xuất.'})


@api_bp.route('/auth/me', methods=['GET'])
@api_login_required
def me():
    return api_ok(g.api_user.to_dict())
