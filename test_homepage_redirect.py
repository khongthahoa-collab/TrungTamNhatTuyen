"""The temporarily disabled homepage redirects without loading public data."""
import unittest
from unittest.mock import patch

from flask import Flask
from flask_login import LoginManager, UserMixin

from blueprints.public import public_bp


class HomepageRedirectTests(unittest.TestCase):
    def test_homepage_redirects_anonymous_and_signed_in_visitors(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='homepage-redirect-test')
        login = LoginManager(app)

        @login.user_loader
        def load_user(user_id):
            user = UserMixin()
            user.id = user_id
            return user

        app.register_blueprint(public_bp)
        app.add_url_rule('/auth/login', endpoint='auth.login', view_func=lambda: 'Login')
        client = app.test_client()
        with patch('blueprints.public.date') as today:
            for signed_in in (False, True):
                if signed_in:
                    with client.session_transaction() as session:
                        session['_user_id'] = '1'
                        session['_fresh'] = True
                for path in ('/', '/?week=2&course_id=1'):
                    for method in ('GET', 'HEAD'):
                        response = client.open(path, method=method)
                        self.assertEqual(response.status_code, 302)
                        self.assertEqual(response.headers['Location'], '/auth/login')
                        self.assertEqual(response.headers['Cache-Control'], 'no-store')
                response = client.get('/', follow_redirects=True)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, b'Login')
            today.today.assert_not_called()
        self.assertEqual(client.get('/manifest.json').status_code, 200)
        self.assertEqual(client.get('/sw.js').status_code, 200)
