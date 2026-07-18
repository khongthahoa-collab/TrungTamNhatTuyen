import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _fix_db_url(url):
    """Normalize database URL for SQLAlchemy + psycopg3.
    - Xoá ?pgbouncer=true  — psycopg3 không nhận param này (dùng prepare_threshold=0 thay)
    - postgres://           → postgresql+psycopg://
    - postgresql://         → postgresql+psycopg://  (force psycopg3 driver)
    """
    if not url:
        return url
    # Strip pgbouncer query param — psycopg3 rejects unknown libpq params
    url = url.replace('?pgbouncer=true', '').replace('&pgbouncer=true', '')
    for prefix in ('postgres://', 'postgresql://', 'postgresql+psycopg2://'):
        if url.startswith(prefix):
            return 'postgresql+psycopg://' + url.split('://', 1)[1]
    return url


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True
    UPLOAD_FOLDER = os.path.join(BASE_DIR, os.environ.get('UPLOAD_FOLDER', 'uploads/documents'))
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 20 * 1024 * 1024))  # 20MB
    ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'jpg', 'jpeg', 'png', 'zip', 'rar', 'mp4'}

    # Remember-me cookie for teacher accounts (see blueprints/auth.py login_post).
    REMEMBER_COOKIE_DURATION = timedelta(days=365)
    REMEMBER_COOKIE_HTTPONLY = True

    # Zalo (Phase 2)
    ZALO_OA_ID = os.environ.get('ZALO_OA_ID', '')
    ZALO_ACCESS_TOKEN = os.environ.get('ZALO_ACCESS_TOKEN', '')
    ZALO_SECRET_KEY = os.environ.get('ZALO_SECRET_KEY', '')


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = _fix_db_url(os.environ.get('DATABASE_URL', 'sqlite:///nhat_tuyen_dev.db'))


class ProductionConfig(Config):
    DEBUG = False
    # REQUIRED: Set DATABASE_URL in Render.com environment variables
    SQLALCHEMY_DATABASE_URI = _fix_db_url(os.environ.get('DATABASE_URL'))
    WTF_CSRF_SSL_STRICT = True
    REMEMBER_COOKIE_SECURE = True
    # pool_pre_ping: reconnect tự động nếu connection bị drop.
    # pool_recycle: chủ động đóng/mở lại connection trước khi Supabase pooler
    # tự ngắt do idle — tránh phải dựa hoàn toàn vào pre_ping (vẫn tốn 1 round
    # trip kiểm tra mỗi lần checkout nếu connection đã chết).
    # pool_size/max_overflow: giới hạn rõ ràng thay vì mặc định của SQLAlchemy,
    # để không mở quá nhiều connection tới Supabase khi traffic tăng.
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 280,
        'pool_size': 5,
        'max_overflow': 10,
    }

    def __init__(self):
        if not self.SQLALCHEMY_DATABASE_URI:
            raise ValueError('DATABASE_URL environment variable is not set!')
        if os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production') == 'dev-secret-key-change-in-production':
            raise ValueError('SECRET_KEY must be set to a secure value in production!')


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}
