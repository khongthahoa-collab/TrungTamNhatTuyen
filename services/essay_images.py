"""Private essay-image storage, decoding limits and answer associations."""
import io
import re
import warnings
from pathlib import Path

from flask import current_app, url_for
from PIL import Image, ImageOps, UnidentifiedImageError

from models import EssayImage

MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_BYTES = 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_PER_QUESTION = 3
MAX_PER_ATTEMPT = 10


def storage_root():
    root = Path(current_app.config['ESSAY_IMAGE_FOLDER']).resolve()
    public_roots = [
        Path(current_app.static_folder).resolve(),
        Path(current_app.config['UPLOAD_FOLDER']).resolve(),
    ]
    if any(root == public or public in root.parents for public in public_roots):
        raise ValueError('ESSAY_IMAGE_FOLDER must be outside publicly served upload folders.')
    return root


def image_path(image_id, thumbnail=False):
    if not re.fullmatch(r'[0-9a-f]{32}', image_id):
        raise ValueError('Invalid essay image storage identifier.')
    return storage_root() / f'{image_id}{"-thumb" if thumbnail else ""}.jpg'


def process_image(upload):
    source = upload.stream.read(MAX_SOURCE_BYTES + 1)
    if not source or len(source) > MAX_SOURCE_BYTES:
        raise ValueError('Ảnh gốc phải có dung lượng không quá 10 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(source)) as original:
                if original.format not in ('JPEG', 'PNG', 'WEBP'):
                    raise ValueError('Chỉ nhận ảnh JPEG, PNG hoặc WebP, không nhận SVG hay ảnh động.')
                if original.width * original.height > MAX_PIXELS or getattr(original, 'n_frames', 1) != 1:
                    raise ValueError('Ảnh quá lớn (tối đa 20 triệu điểm ảnh) hoặc là ảnh động.')
                original.load()
                oriented = ImageOps.exif_transpose(original)
                rgba = oriented.convert('RGBA')
                image = Image.new('RGB', rgba.size, 'white')
                image.paste(rgba, mask=rgba.getchannel('A'))
                image.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.save(output, format='JPEG', quality=85, optimize=True)
                if output.tell() > MAX_IMAGE_BYTES:
                    raise ValueError('Ảnh sau nén vẫn vượt 1 MB. Hãy chụp riêng từng trang rõ nét.')
                image.thumbnail((360, 360), Image.Resampling.LANCZOS)
                thumbnail = io.BytesIO()
                image.save(thumbnail, format='JPEG', quality=75)
                return output.getvalue(), thumbnail.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError('Không đọc được ảnh hoặc ảnh vượt giới hạn an toàn.') from exc


def essay_answer_fields(attempt):
    fields = set()
    orders = attempt.order_data.get('groups', [])
    for gi, group in enumerate(attempt.exam.question_groups):
        if group.get('type') != 'essay':
            continue
        questions = group.get('questions', [])
        order = orders[gi] if gi < len(orders) else {}
        q_order = order.get('q_order') or list(range(len(questions)))
        for position, original_index in enumerate(q_order, 1):
            if 0 <= original_index < len(questions):
                fields.add(f'g{gi}_q{position}')
    return fields


def active_images(attempt_id):
    return EssayImage.query.filter_by(attempt_id=attempt_id, deleted_at=None).order_by(
        EssayImage.position, EssayImage.created_at, EssayImage.id,
    ).all()


def image_data(image):
    return {
        'id': image.id,
        'url': url_for('exam_images.read_image', image_id=image.id),
        'thumbnail_url': url_for('exam_images.read_image', image_id=image.id, thumbnail=1),
    }


def images_by_answer(attempt_id):
    result = {}
    for image in active_images(attempt_id):
        result.setdefault(image.answer_field, []).append(image_data(image))
    return result
