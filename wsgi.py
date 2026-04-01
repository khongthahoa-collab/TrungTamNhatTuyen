import os
from app import create_app

# Railway will set FLASK_ENV to 'production'
# If not set, default to 'development'
env = os.environ.get('FLASK_ENV', 'development')
app = create_app(env)

if __name__ == '__main__':
    app.run()
