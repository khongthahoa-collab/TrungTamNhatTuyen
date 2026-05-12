import os
from app import create_app

# On Render.com, set FLASK_ENV=production in environment variables
env = os.environ.get('FLASK_ENV', 'development')
app = create_app(env)

if __name__ == '__main__':
    app.run()
