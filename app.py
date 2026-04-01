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
    app.register_blueprint(parent_bp, url_prefix='/phu-huynh')
    app.register_blueprint(teacher_bp, url_prefix='/giao-vien')
    app.register_blueprint(admin_bp, url_prefix='/quan-tri')

    # Jinja2 global helpers
    from models import SystemConfig
    import models as m

    @app.context_processor
    def inject_globals():
        return {
            'SystemConfig': SystemConfig,
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

    return app
