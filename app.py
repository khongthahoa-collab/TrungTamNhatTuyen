import os
from flask import Flask
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

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(public_bp, url_prefix='/')
    app.register_blueprint(parent_bp, url_prefix='/parent')
    app.register_blueprint(teacher_bp, url_prefix='/teacher')
    app.register_blueprint(admin_bp, url_prefix='/admin')

    # Force a password change before any other page is reachable for accounts
    # created with a temporary password (see blueprints/admin/account_utils.py).
    @app.before_request
    def enforce_password_change():
        from flask import redirect, url_for, request
        from flask_login import current_user
        if current_user.is_authenticated and current_user.must_change_password:
            allowed = {'auth.change_password', 'auth.logout', 'static'}
            if request.endpoint not in allowed:
                return redirect(url_for('auth.change_password'))

    # Jinja2 global helpers
    from flask import request
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
