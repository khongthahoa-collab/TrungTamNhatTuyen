"""REST API layer (/api/v1) — token-authenticated, JSON-only, additive
alongside the existing session-cookie HTML routes. Reuses the same
User.can_access/can_write permission system as the web app (see
blueprints/permissions.py) so an API token has identical effective
access to what that account can do in the browser.
"""
from functools import wraps
from flask import Blueprint, request, jsonify, g
from models import User

api_bp = Blueprint('api', __name__, url_prefix='/api/v1')


def api_ok(data, status=200, meta=None):
    body = {'data': data}
    if meta is not None:
        body['meta'] = meta
    return jsonify(body), status


def api_error(message, status=400, code=None):
    err = {'message': message}
    if code:
        err['code'] = code
    return jsonify({'error': err}), status


def pagination_meta(pagination):
    return {
        'page': pagination.page,
        'pages': pagination.pages,
        'total': pagination.total,
        'per_page': pagination.per_page,
    }


def get_page_args(default_per_page=30, max_per_page=100):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', default_per_page, type=int)
    per_page = max(1, min(per_page, max_per_page))
    return page, per_page


def get_body():
    """Request body as a plain dict, whether the client sent JSON or a
    regular form POST — every write endpoint accepts either."""
    json_body = request.get_json(silent=True)
    if json_body is not None:
        return json_body
    return request.form.to_dict()


def body_int(body, key, default=None):
    """Coerce a possibly-string/possibly-int body value to int, tolerating
    missing/blank/invalid input by returning `default` instead of raising —
    callers that require the field should treat `default=None` as 'missing'."""
    value = body.get(key)
    if value in (None, ''):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def body_bool(body, key, default=None):
    value = body.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def parse_amount(body, key='amount', required=True):
    """Parse a monetary amount from a request body. Unlike body_int (which
    tolerates bad input with a default, for optional filter params), a
    malformed/missing/negative amount is a hard validation failure for a
    financial write — raises ValueError with a clean message; callers
    catch it and return a 400 instead of letting a bare float(...) crash
    with an uncaught 500."""
    value = body.get(key)
    if value in (None, ''):
        if required:
            raise ValueError(f"Trường '{key}' là bắt buộc.")
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Giá trị '{key}' không hợp lệ, phải là một số.")
    if amount < 0:
        raise ValueError(f"Giá trị '{key}' không được nhỏ hơn 0.")
    return amount


def api_login_required(f):
    """Bearer-token auth — looks up User.api_token instead of the
    session-cookie Flask-Login mechanism the HTML routes use."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        token = auth_header[7:].strip() if auth_header.startswith('Bearer ') else None
        user = User.query.filter_by(api_token=token, is_active=True, is_deleted=False).first() if token else None
        if not user:
            return api_error('Thiếu hoặc sai access token.', 401, code='unauthorized')
        g.api_user = user
        return f(*args, **kwargs)
    return decorated


def api_require_module(module_key, write=False):
    """Gate an endpoint the same way blueprints/admin's before_request
    hook gates the equivalent HTML route — same module key, same
    read-vs-write distinction."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            allowed = g.api_user.can_write(module_key) if write else g.api_user.can_access(module_key)
            if not allowed:
                return api_error('Không có quyền truy cập chức năng này.', 403, code='forbidden')
            return f(*args, **kwargs)
        return decorated
    return decorator


# Import sub-modules to register routes on api_bp
from blueprints.api import (auth, students, classes, teachers, schedules,  # noqa: E402,F401
                            attendance, scores, tuition, rewards, rooms,
                            courses, schools, notifications)
