import os
from app import create_app
from extensions import db

# On Render.com, set FLASK_ENV=production in environment variables
env = os.environ.get('FLASK_ENV', 'development')
app = create_app(env)

# Create all tables on startup if they don't exist yet
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run()
