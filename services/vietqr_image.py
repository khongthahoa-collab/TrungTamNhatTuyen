"""Same-origin VietQR images for previews and canvas exports."""
import base64
import binascii
import io
import re
import warnings
from xml.etree import ElementTree

from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException
from flask import current_app, url_for
from itsdangerous import URLSafeSerializer
from PIL import Image, UnidentifiedImageError

from services.tuition_service import build_vietqr_url


def sanitize_vietqr_svg(content):
    """Rebuild the provider's static SVG without scripts or remote resources."""
    namespace = 'http://www.w3.org/2000/svg'
    allowed = {
        'svg': {'width', 'height', 'viewBox', 'role'},
        'title': set(),
        'rect': {'x', 'y', 'width', 'height', 'fill'},
        'image': {'x', 'y', 'width', 'height', 'href', 'id', 'preserveAspectRatio'},
        'g': {'transform'},
        'path': {'d', 'fill', 'shape-rendering'},
        'text': {'x', 'y', 'fill', 'font-family', 'font-size', 'font-weight', 'text-anchor'},
    }
    try:
        root = SafeElementTree.fromstring(content, forbid_dtd=True)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise ValueError('Invalid VietQR SVG XML') from exc
    if root.tag != f'{{{namespace}}}svg':
        raise ValueError('Invalid VietQR SVG root')
    width = root.get('width', '')
    height = root.get('height', '')
    if not width.isdigit() or not height.isdigit() or not (0 < int(width) * int(height) <= 4_000_000):
        raise ValueError('Invalid VietQR SVG dimensions')
    if len(list(root.iter())) > 20_000:
        raise ValueError('VietQR SVG exceeds element limit')

    def rebuild(node, depth=0):
        tag = node.tag.removeprefix(f'{{{namespace}}}')
        if depth > 16 or tag not in allowed or set(node.attrib) - allowed[tag]:
            raise ValueError('Unsupported VietQR SVG element or attribute')
        attributes = dict(node.attrib)
        for key, value in attributes.items():
            if key == 'href':
                formats = {'data:image/png;base64,': 'PNG', 'data:image/jpeg;base64,': 'JPEG'}
                prefix = next((candidate for candidate in formats if value.startswith(candidate)), None)
                if tag != 'image' or prefix is None:
                    raise ValueError('External SVG image is forbidden')
                try:
                    image_bytes = base64.b64decode(value[len(prefix):], validate=True)
                    with warnings.catch_warnings():
                        warnings.simplefilter('error', Image.DecompressionBombWarning)
                        with Image.open(io.BytesIO(image_bytes)) as image:
                            if image.format != formats[prefix] or image.width * image.height > 4_000_000:
                                raise ValueError('Invalid embedded QR image')
                            image.verify()
                except (binascii.Error, OSError, UnidentifiedImageError,
                        Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
                    raise ValueError('Invalid embedded QR image') from exc
            elif re.search(r'url\s*\(|javascript:|data:|https?:|[<>]', value, re.IGNORECASE):
                raise ValueError('Unsafe SVG attribute value')
        element = ElementTree.Element(f'{{{namespace}}}{tag}', attributes)
        element.text = node.text
        element.tail = node.tail
        for child in node:
            element.append(rebuild(child, depth + 1))
        return element

    return ElementTree.tostring(rebuild(root), encoding='utf-8')


def image_signer():
    return URLSafeSerializer(current_app.secret_key, salt='vietqr-image')


def build_vietqr_image_url(bank_id, account_number, account_name, amount=None, add_info=''):
    source = build_vietqr_url(bank_id, account_number, account_name, amount, add_info)
    if source is None:
        return None
    return url_for('admin.vietqr_image', token=image_signer().dumps(source))
