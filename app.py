import os
from flask import Flask, request
from config import config
from extensions import db, login_manager, csrf, migrate


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'default')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)

    # Auto-create database tables for local development when schema is missing.
    if config_name != 'production':
        import models  # noqa: F401
        with app.app_context():
            db.create_all()
            from models import User, UserRole

            if not User.query.filter_by(username='nhattuyen').first():
                admin = User(
                    full_name='Nguyen Thi Nhat Tuyen',
                    username='nhattuyen',
                    phone='0901234567',
                    role=UserRole.ADMIN,
                    is_master=True,
                )
                admin.set_password(os.environ.get('SEED_ADMIN_PASSWORD', '!123123@'))
                db.session.add(admin)
                db.session.commit()

    # User loader
    from models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints
    from blueprints.auth import auth_bp
    from blueprints.public import public_bp
    from blueprints.parent import parent_bp
    from blueprints.teacher import teacher_bp
    from blueprints.admin import admin_bp
    from blueprints.api import api_bp
    from blueprints.api.calendar import api_calendar_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(public_bp, url_prefix='/')
    app.register_blueprint(parent_bp, url_prefix='/parent')
    app.register_blueprint(teacher_bp, url_prefix='/teacher')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(api_bp)
    app.register_blueprint(api_calendar_bp)
    # Token-authenticated JSON API, not cookie/session-based — Flask-WTF's
    # CSRF protection doesn't apply the same way here.
    csrf.exempt(api_bp)

    # iOS standalone PWA (Add to Home Screen) caches HTML far more aggressively
    # than a normal Safari tab, and has no reload button/URL bar to bypass it —
    # so business pages can get stuck showing stale data indefinitely. Force
    # no-store on the dynamic sections; static assets are untouched.
    @app.after_request
    def disable_dynamic_routes_cache(response):
        path = request.path
        if (path.startswith('/admin') or path.startswith('/teacher') or
                path.startswith('/parent') or path.startswith('/api') or path == '/'):
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

    # Force a password change before any other page is reachable for accounts
    # created with a temporary password (see blueprints/admin/account_utils.py).
    @app.before_request
    def enforce_password_change():
        from flask import redirect, url_for
        from flask_login import current_user
        if current_user.is_authenticated and current_user.must_change_password:
            allowed = {'auth.change_password', 'auth.logout', 'static'}
            if request.endpoint not in allowed:
                return redirect(url_for('auth.change_password'))

    # Jinja2 global helpers
    from models import SystemConfig, ContactInquiry, Notification
    from flask_login import current_user
    from blueprints.permissions import ADMIN_ENDPOINT_MODULES, ADMIN_SIDEBAR_GROUPS
    import models as m

    @app.context_processor
    def inject_globals():
        try:
            # Only rendered on the admin sidebar — skip the query entirely
            # for every public/teacher/parent page view (the majority of traffic).
            if current_user.is_authenticated and current_user.is_admin:
                unread_inquiries = ContactInquiry.query.filter_by(is_read=False).count()
            else:
                unread_inquiries = 0
        except Exception:
            unread_inquiries = 0
        try:
            if current_user.is_authenticated:
                unread_notifications = Notification.query.filter_by(
                    user_id=current_user.id, is_read=False
                ).count()
            else:
                unread_notifications = 0
        except Exception:
            unread_notifications = 0
        return {
            'SystemConfig': SystemConfig,
            'unread_inquiries': unread_inquiries,
            'unread_notifications': unread_notifications,
            'current_admin_module': ADMIN_ENDPOINT_MODULES.get((request.endpoint or '').split('.')[-1]),
            'ADMIN_SIDEBAR_GROUPS': ADMIN_SIDEBAR_GROUPS,
            'UserRole': m.UserRole,
            'StudentLevel': m.StudentLevel,
            'ScheduleType': m.ScheduleType,
            'AttendanceStatus': m.AttendanceStatus,
            'ScoreSource': m.ScoreSource,
            'ScoreType': m.ScoreType,
            'SemesterType': m.SemesterType,
            'TuitionMethod': m.TuitionMethod,
            'ExpenseCategory': m.ExpenseCategory,
        }

    @app.template_filter('vnd')
    def format_vnd(value):
        if value is None:
            return '0 ₫'
        try:
            return f'{int(value):,} ₫'.replace(',', '.')
        except (ValueError, TypeError):
            return str(value)

    @app.template_filter('date_vn')
    def format_date_vn(value):
        if not value:
            return ''
        try:
            return value.strftime('%d/%m/%Y')
        except Exception:
            return str(value)

    @app.template_filter('datetime_vn')
    def format_datetime_vn(value):
        if not value:
            return ''
        try:
            return value.strftime('%d/%m/%Y %H:%M')
        except Exception:
            return str(value)

    @app.template_filter('weekday_vn')
    def format_weekday_vn(value):
        days = ['Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'Chủ nhật']
        try:
            return days[value.weekday()]
        except Exception:
            return ''

    # Friendly, on-brand error pages instead of Flask/Werkzeug's default
    # plain-text ones — see templates/errors/error.html. Note: a 502 raised
    # by Railway's edge proxy when the app process itself is unreachable
    # never reaches this handler (the app isn't running to respond at all);
    # this only covers a 502 the app itself explicitly returns.
    def _render_error(code, icon, title, message, show_retry=False):
        from flask import render_template
        return render_template(
            'errors/error.html',
            code=code, icon=icon, title=title, message=message, show_retry=show_retry,
            center_name=SystemConfig.get('center_name', 'Trung tâm Nhật Tuyền'),
        ), code

    @app.errorhandler(403)
    def handle_403(e):
        return _render_error(
            403, 'bi-shield-lock',
            'Bạn không có quyền truy cập',
            'Trang này yêu cầu quyền truy cập mà tài khoản của bạn hiện chưa có. Nếu đây là nhầm lẫn, hãy liên hệ quản trị viên.',
        )

    @app.errorhandler(404)
    def handle_404(e):
        return _render_error(
            404, 'bi-signpost-2',
            'Không tìm thấy trang',
            'Đường dẫn bạn truy cập không tồn tại hoặc đã được thay đổi. Vui lòng kiểm tra lại địa chỉ hoặc quay về trang chủ.',
        )

    @app.errorhandler(500)
    def handle_500(e):
        db.session.rollback()
        return _render_error(
            500, 'bi-tools',
            'Đã có lỗi xảy ra',
            'Hệ thống gặp sự cố ngoài ý muốn. Đội ngũ kỹ thuật đã được ghi nhận lỗi này — vui lòng thử lại sau ít phút.',
            show_retry=True,
        )

    @app.errorhandler(502)
    def handle_502(e):
        return _render_error(
            502, 'bi-cloud-slash',
            'Hệ thống đang khởi động lại',
            'Máy chủ đang tạm thời quá tải hoặc đang khởi động lại. Vui lòng tải lại trang sau ít phút.',
            show_retry=True,
        )

    @app.template_filter('error_id_render')
    def error_id_render(text, reveal=True):
        """Render '[A:seg]' / '[*B:seg]' error-identification markers as underlined, labeled spans.
        reveal=False hides which one is correct (use for student-facing exam papers)."""
        import re
        from markupsafe import Markup, escape
        if not text:
            return Markup('')
        escaped = str(escape(text))

        def repl(m):
            star, label, seg = m.group(1), m.group(2), m.group(3)
            cls = 'text-success fw-bold' if (star and reveal) else ''
            return f'<span class="{cls}" style="text-decoration:underline;">{seg}</span><sup>{label}</sup>'

        return Markup(re.sub(r'\[(\*?)([A-F]):([^\]]*)\]', repl, escaped))

    return app
