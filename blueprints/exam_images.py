"""Authenticated, attempt-scoped essay images; never served through public uploads."""
from datetime import datetime, timedelta
import re
import time
import uuid

import click
from flask import Blueprint, abort, current_app, jsonify, request, send_file
from flask.cli import with_appcontext
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import EssayImage, ExamAttempt, Student
from services.auth_context import get_active_role
from services.essay_images import (
    MAX_PER_ATTEMPT, MAX_PER_QUESTION, active_images, essay_answer_fields,
    image_data, image_path, process_image, storage_root,
)

exam_images_bp = Blueprint('exam_images', __name__, url_prefix='/exam-images')


def _require_access(attempt, write=False):
    if not current_user.is_active or current_user.is_deleted:
        abort(403)
    role = get_active_role(current_user)
    if role in ('student', 'parent') and (
        (role == 'student' and current_user.is_student)
        or (role == 'parent' and current_user.is_parent)
    ):
        from blueprints.parent import _exams_for_student, _get_student_or_403
        student = _get_student_or_403(attempt.student_id)
        if not student.is_active or student.is_deleted:
            abort(403)
        if attempt.exam.is_draft or attempt.exam not in _exams_for_student(student):
            abort(404)
    elif not write and role in ('teacher', 'admin'):
        if not (current_user.is_admin or current_user.is_teacher):
            abort(403)
        if not current_user.can_access('exams'):
            abort(403)
        if role == 'teacher' and attempt.exam.created_by != current_user.id:
            abort(403)
        if attempt.status != 'submitted':
            abort(403)
    else:
        abort(403)
    if write and (
        attempt.status != 'in_progress'
        or (datetime.utcnow() - attempt.started_at).total_seconds()
        >= attempt.exam.duration_minutes * 60
    ):
        abort(409, description='Lượt làm bài đã nộp hoặc đã hết thời gian.')


def _locked_attempt(attempt_id):
    attempt = ExamAttempt.query.filter_by(id=attempt_id).with_for_update().first_or_404()
    _require_access(attempt, write=True)
    # Serialize quotas across different attempts belonging to the same student.
    db.session.query(Student.id).filter_by(id=attempt.student_id).with_for_update().one()
    _require_access(attempt, write=True)
    return attempt


@exam_images_bp.errorhandler(409)
@exam_images_bp.errorhandler(413)
def image_request_error(error):
    message = (
        'Ảnh gửi lên vượt giới hạn 10 MB.'
        if error.code == 413 else 'Lượt làm bài đã nộp hoặc đã hết thời gian.'
    )
    return jsonify({'error': message}), error.code


@exam_images_bp.post('/attempts/<int:attempt_id>')
@login_required
def upload_image(attempt_id):
    if request.content_length and request.content_length > 11 * 1024 * 1024:
        abort(413)
    attempt = ExamAttempt.query.get_or_404(attempt_id)
    _require_access(attempt, write=True)
    answer_field = request.form.get('answer_field', '')
    if answer_field not in essay_answer_fields(attempt):
        return jsonify({'error': 'Câu hỏi tự luận không hợp lệ.'}), 400
    upload = request.files.get('image')
    if upload is None or sum(len(values) for _key, values in request.files.lists()) != 1:
        return jsonify({'error': 'Vui lòng chọn một ảnh cho mỗi lần tải.'}), 400
    try:
        content, thumbnail = process_image(upload)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    # Decode before taking locks, then reload: a submission may have finished meanwhile.
    db.session.rollback()
    attempt = _locked_attempt(attempt_id)
    if answer_field not in essay_answer_fields(attempt):
        return jsonify({'error': 'Cấu trúc câu hỏi đã thay đổi. Hãy tải lại trang.'}), 409
    images = active_images(attempt.id)
    if len(images) >= MAX_PER_ATTEMPT or sum(
        image.answer_field == answer_field for image in images
    ) >= MAX_PER_QUESTION:
        return jsonify({'error': 'Tối đa 3 ảnh mỗi câu và 10 ảnh mỗi lượt làm bài.'}), 400
    recent_count = EssayImage.query.filter(
        EssayImage.student_id == attempt.student_id,
        EssayImage.created_at >= datetime.utcnow() - timedelta(hours=1),
    ).count()
    total_bytes = db.session.query(db.func.coalesce(db.func.sum(EssayImage.size_bytes), 0)).filter(
        EssayImage.student_id == attempt.student_id,
    ).scalar()
    if recent_count >= 50:
        return jsonify({'error': 'Đã đạt giới hạn 50 ảnh/giờ. Vui lòng thử lại sau.'}), 429
    if total_bytes + len(content) + len(thumbnail) > 100 * 1024 * 1024:
        return jsonify({'error': 'Đã đạt giới hạn lưu ảnh 100 MB của học sinh. Liên hệ quản trị viên.'}), 400
    image = EssayImage(
        id=uuid.uuid4().hex, attempt_id=attempt.id, student_id=attempt.student_id,
        answer_field=answer_field, position=max((item.position for item in images), default=-1) + 1,
        size_bytes=len(content) + len(thumbnail),
    )
    written = []
    try:
        storage_root().mkdir(parents=True, exist_ok=True, mode=0o700)
        for is_thumbnail, data in ((False, content), (True, thumbnail)):
            path = image_path(image.id, is_thumbnail)
            with path.open('xb') as file:
                written.append(path)
                file.write(data)
            path.chmod(0o600)
        db.session.add(image)
        db.session.commit()
    except (OSError, SQLAlchemyError, ValueError):
        db.session.rollback()
        current_app.logger.exception('Failed to store essay image for attempt %s', attempt_id)
        for path in written:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                current_app.logger.exception('Failed to remove incomplete essay image %s', path.name)
        return jsonify({'error': 'Không thể lưu ảnh. Hãy thử lại hoặc liên hệ quản trị viên.'}), 503
    return jsonify(image_data(image)), 201


@exam_images_bp.get('/<image_id>')
@login_required
def read_image(image_id):
    image = EssayImage.query.filter_by(id=image_id, deleted_at=None).first_or_404()
    _require_access(image.attempt)
    path = image_path(image.id, request.args.get('thumbnail') == '1')
    if not path.is_file():
        current_app.logger.error('Essay image file missing: %s', path.name)
        abort(404)
    response = send_file(path, mimetype='image/jpeg', conditional=False, etag=False)
    response.headers['Cache-Control'] = 'private, no-store, max-age=0'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Disposition'] = 'inline; filename="essay-answer.jpg"'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    return response


@exam_images_bp.delete('/<image_id>')
@login_required
def delete_image(image_id):
    image = EssayImage.query.filter_by(id=image_id, deleted_at=None).first_or_404()
    _locked_attempt(image.attempt_id)
    db.session.refresh(image)
    if image.deleted_at is not None:
        abort(404)
    image.deleted_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'deleted': True})


@exam_images_bp.post('/attempts/<int:attempt_id>/order')
@login_required
def reorder_images(attempt_id):
    attempt = _locked_attempt(attempt_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'Thứ tự ảnh không hợp lệ.'}), 400
    field = body.get('answer_field')
    identifiers = body.get('ids')
    images = [image for image in active_images(attempt.id) if image.answer_field == field]
    if (
        not isinstance(field, str) or field not in essay_answer_fields(attempt)
        or not isinstance(identifiers, list)
        or not all(isinstance(identifier, str) for identifier in identifiers)
        or len(identifiers) != len(images) or set(identifiers) != {image.id for image in images}
    ):
        return jsonify({'error': 'Thứ tự ảnh không hợp lệ.'}), 400
    for image in images:
        image.position = identifiers.index(image.id)
    db.session.commit()
    return jsonify({'saved': True})


@click.command('cleanup-essay-images')
@with_appcontext
def cleanup_essay_images():
    """Remove deleted attachments, week-old abandoned images, and day-old orphan files."""
    now = datetime.utcnow()
    abandoned = EssayImage.query.join(ExamAttempt).filter(
        ExamAttempt.status == 'in_progress',
        EssayImage.created_at < now - timedelta(days=7),
    ).with_for_update(of=ExamAttempt).all()
    deleted = EssayImage.query.filter(
        EssayImage.deleted_at < now - timedelta(hours=1),
    ).all()
    for image in {image.id: image for image in abandoned + deleted}.values():
        for thumbnail in (False, True):
            image_path(image.id, thumbnail).unlink(missing_ok=True)
        db.session.delete(image)
    db.session.commit()
    root = storage_root()
    removed = 0
    if root.is_dir():
        known = {image.id for image in EssayImage.query.all()}
        for path in root.iterdir():
            name = re.fullmatch(r'([0-9a-f]{32})(?:-thumb)?\.jpg', path.name)
            if (
                name and path.is_file() and name.group(1) not in known
                and path.stat().st_mtime < time.time() - 86400
            ):
                path.unlink()
                removed += 1
    click.echo(f'Removed abandoned/deleted images and {removed} orphan files.')
