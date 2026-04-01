import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


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
    # MySQL database URI
    # Format: mysql+pymysql://user:password@host:port/database
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'mysql+pymysql://nhat_tuyen_user:nhat_tuyen_pass@localhost:3306/nhat_tuyen_db'
    )


class ProductionConfig(Config):
    DEBUG = False
    # REQUIRED: DATABASE_URL must be set in Railway environment variables
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    WTF_CSRF_SSL_STRICT = True
    
    # Validate critical configs in production
    if not SQLALCHEMY_DATABASE_URI:
        raise ValueError('DATABASE_URL environment variable is not set!')
    if os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production') == 'dev-secret-key-change-in-production':
        raise ValueError('SECRET_KEY must be set to a secure value in production!')


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}
