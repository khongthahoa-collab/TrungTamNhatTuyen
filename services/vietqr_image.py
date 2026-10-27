"""Same-origin VietQR images for previews and canvas exports."""
from flask import current_app, url_for
from itsdangerous import URLSafeSerializer

from services.tuition_service import build_vietqr_url


def image_signer():
    return URLSafeSerializer(current_app.secret_key, salt='vietqr-image')


def build_vietqr_image_url(bank_id, account_number, account_name, amount=None, add_info=''):
    source = build_vietqr_url(bank_id, account_number, account_name, amount, add_info)
    if source is None:
        return None
    return url_for('admin.vietqr_image', token=image_signer().dumps(source))
