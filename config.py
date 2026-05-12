import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _fix_db_url(url):
    """Normalize database URL for SQLAlchemy + psycopg3.
    - postgres://    → postgresql+psycopg://  (Supabase/Heroku old scheme)
    - postgresql://  → postgresql+psycopg://  (force psycopg3 driver)
    """
    if not url:
        return url
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
    # Supabase dùng pgbouncer transaction mode — phải tắt prepared statements
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'connect_args': {'prepare_threshold': 0},
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
