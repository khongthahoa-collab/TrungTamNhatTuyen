"""Read-only shared content library for the admin and teacher exam editors."""
from flask import Blueprint, abort, jsonify
from flask_login import current_user, login_required

from blueprints.admin import require_admin_or_teacher
from models import ExamContentTemplate

exam_content_templates_bp = Blueprint('exam_content_templates', __name__)


@exam_content_templates_bp.get('/exam-content-templates')
@login_required
@require_admin_or_teacher
def list_templates():
    if not current_user.can_access('exams'):
        abort(403)
    templates = ExamContentTemplate.query.order_by(
        ExamContentTemplate.name, ExamContentTemplate.id
    ).all()
    response = jsonify(templates=[
        {'id': item.id, 'name': item.name, 'content': item.content}
        for item in templates
    ])
    response.headers['Cache-Control'] = 'no-store'
    return response
