"""VietQR proxy tests: synthetic accounts, in-memory DB, mocked upstream only."""
from io import BytesIO
import unittest
from unittest.mock import MagicMock, patch

from PIL import Image

from app import create_app
from config import Config, config
from extensions import db
from models import PermissionGroup, User
from services.vietqr_image import build_vietqr_image_url, image_signer


class QRTestConfig(Config):
    TESTING = True
    SECRET_KEY = 'synthetic-qr-test'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    ACADEMIC_ROLLOVER_ENABLED = False


class VietQRImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config['qr_image_test'] = QRTestConfig
        cls.app = create_app('qr_image_test')

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.engine.dispose()
        config.pop('qr_image_test')

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        group = PermissionGroup(name='Students only', permissions='{"students":"read"}')
        db.session.add(group)
        db.session.flush()
        self.users = {}
        for name, role, master, permission in (
            ('master', 'admin', True, None), ('student_reader', 'admin', False, group),
            ('denied', 'admin', False, None), ('teacher', 'teacher', False, None),
        ):
            user = User(username=name, role=role, is_master=master,
                        permission_group=permission, password_hash='test')
            db.session.add(user)
            db.session.flush()
            self.users[name] = user.id
        db.session.commit()
        self.client = self.app.test_client()
        self.login('master')
        with self.app.test_request_context():
            self.url = build_vietqr_image_url('VCB', '0000000000', 'SYNTHETIC', 500000, 'HP TEST')
        buf = BytesIO()
        Image.new('RGB', (32, 32), 'white').save(buf, 'PNG')
        self.image = buf.getvalue()
        self.upstream = MagicMock()
        self.upstream.status_code = 200
        self.upstream.iter_content.return_value = [self.image]
        self.upstream.__enter__.return_value = self.upstream
        self.get_patch = patch('requests.get', return_value=self.upstream)
        self.get = self.get_patch.start()

    def tearDown(self):
        self.get_patch.stop()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def login(self, name):
        from flask import g
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session.clear()
            session['_user_id'] = str(self.users[name])
            session['_fresh'] = True

    def test_same_origin_image_and_export_bytes(self):
        self.assertTrue(self.url.startswith('/admin/tuition/qr-image?'))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, self.image)
        self.assertEqual(response.mimetype, 'image/png')
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        source = self.get.call_args.args[0]
        self.assertTrue(source.startswith('https://img.vietqr.io/image/VCB-0000000000-print.jpg?'))
        self.assertIn('amount=500000', source)
        self.assertIn('addInfo=HP+TEST', source)
        self.assertFalse(self.get.call_args.kwargs['allow_redirects'])
        self.assertEqual(self.get.call_args.kwargs['timeout'], (3, 8))

    def test_permissions_and_login(self):
        for name, expected in (('student_reader', 200), ('denied', 403), ('teacher', 403)):
            self.login(name)
            self.assertEqual(self.client.get(self.url).status_code, expected)
        from flask import g
        g.pop('_login_user', None)
        self.assertEqual(self.app.test_client().get(self.url).status_code, 302)

    def test_tampering_and_signed_external_host_rejected_without_fetch(self):
        self.assertEqual(self.client.get(self.url + 'tampered').status_code, 400)
        token = image_signer().dumps('https://example.test/image')
        self.assertEqual(self.client.get('/admin/tuition/qr-image', query_string={'token': token}).status_code, 400)
        self.get.assert_not_called()

    def test_upstream_http_failure_redirect_and_nonimage_are_explicit_errors(self):
        for status in (301, 404, 429, 500):
            self.upstream.status_code = status
            self.assertEqual(self.client.get(self.url).status_code, 502)
        self.upstream.status_code = 200
        self.upstream.iter_content.return_value = [b'<html>Unavailable</html>']
        self.assertEqual(self.client.get(self.url).status_code, 502)

    def test_timeout_and_oversized_image(self):
        import requests
        self.get.side_effect = requests.Timeout()
        self.assertEqual(self.client.get(self.url).status_code, 502)
        self.get.side_effect = None
        self.upstream.iter_content.return_value = [b'x' * (2 * 1024 * 1024 + 1)]
        self.assertEqual(self.client.get(self.url).status_code, 502)

    def test_url_keeps_bank_and_amount_independent(self):
        with self.app.test_request_context():
            other = build_vietqr_image_url('BIDV', '0000000001', 'OTHER', 600000, 'HP OTHER')
            self.assertIsNone(build_vietqr_image_url('', '', ''))
        self.client.get(other)
        source = self.get.call_args.args[0]
        self.assertIn('/BIDV-0000000001-print.jpg?', source)
        self.assertIn('amount=600000', source)
        self.assertIn('addInfo=HP+OTHER', source)
