"""
Shared business logic for the online exam builder, used by both the admin
exam screens (blueprints/admin/exams.py) and the teacher exam screens
(blueprints/teacher_exams.py). The two sides have separate routes/templates
by design — only this parsing/validation layer and the underlying DB models
are shared.
"""
import json
import re
from datetime import datetime
from flask_login import current_user
from flask import abort, session
from models import ExamFolder

EXAM_TYPES = [
    ('practice', 'Ôn tập'),
    ('quiz_15', 'Kiểm tra 15 phút'),
    ('periodic', 'Kiểm tra định kì'),
    ('midterm_1', 'Giữa kì 1'),
    ('final_1', 'Cuối kì 1'),
    ('midterm_2', 'Giữa kì 2'),
    ('final_2', 'Cuối kì 2'),
    ('other', 'Khác'),
]
DURATION_OPTIONS = [15, 20, 30, 60, 90]
SESSION_KEY = 'exam_draft'

GROUP_TYPES = {'mcq', 'true_false', 'short_answer', 'error_id'}
ERROR_ID_PATTERN = re.compile(r'\[(\*?)([A-F]):([^\]]*)\]')


def _parse_mcq_question(item):
    text = str(item.get('text', '')).strip()
    options = [str(opt).strip() for opt in item.get('options', []) if str(opt).strip()]
    try:
        correct_index = int(item.get('correct_index', -1))
    except (ValueError, TypeError):
        correct_index = -1
    if not text or len(options) < 2 or not (0 <= correct_index < len(options)):
        return None
    return {
        'text': text, 'options': options, 'correct_index': correct_index,
        'explanation': str(item.get('explanation', '')).strip(),
    }


def _parse_true_false_question(item):
    text = str(item.get('text', '')).strip()
    statements = []
    for st in item.get('statements', []):
        if not isinstance(st, dict):
            continue
        st_text = str(st.get('text', '')).strip()
        if not st_text:
            continue
        statements.append({'text': st_text, 'correct': bool(st.get('correct'))})
    if not text or len(statements) < 2:
        return None
    return {'text': text, 'statements': statements, 'explanation': str(item.get('explanation', '')).strip()}


def _parse_short_answer_question(item):
    text = str(item.get('text', '')).strip()
    answers = [str(a).strip() for a in item.get('accepted_answers', []) if str(a).strip()]
    if not text or not answers:
        return None
    return {
        'text': text, 'accepted_answers': answers,
        'explanation': str(item.get('explanation', '')).strip(),
    }


def _parse_error_id_question(item):
    text = str(item.get('text', '')).strip()
    matches = ERROR_ID_PATTERN.findall(text)
    correct_label = next((label for star, label, _ in matches if star == '*'), None)
    if not text or len(matches) < 2 or not correct_label:
        return None
    return {
        'text': text, 'correct_label': correct_label,
        'explanation': str(item.get('explanation', '')).strip(),
    }


QUESTION_PARSERS = {
    'mcq': _parse_mcq_question,
    'true_false': _parse_true_false_question,
    'short_answer': _parse_short_answer_question,
    'error_id': _parse_error_id_question,
}


def parse_groups_payload(raw):
    """Validate/normalize the grouped, multi-type question builder payload sent from step 1."""
    try:
        data = json.loads(raw or '{}')
    except (ValueError, TypeError):
        return []
    raw_groups = data.get('groups') if isinstance(data, dict) else None
    if not isinstance(raw_groups, list):
        return []
    groups = []
    for g in raw_groups:
        if not isinstance(g, dict):
            continue
        gtype = g.get('type') if g.get('type') in GROUP_TYPES else 'mcq'
        parser = QUESTION_PARSERS[gtype]
        questions = []
        for item in g.get('questions', []):
            if not isinstance(item, dict):
                continue
            parsed = parser(item)
            if parsed:
                questions.append(parsed)
        if not questions:
            continue
        groups.append({
            'title': str(g.get('title', '')).strip() or 'Phần thi',
            'type': gtype,
            'instruction': str(g.get('instruction', '')).strip(),
            'questions': questions,
        })
    return groups


def require_owns_or_admin(exam):
    if current_user.is_teacher and exam.created_by != current_user.id:
        abort(403)


def session_draft():
    """Read the exam_draft session value, discarding it if missing or malformed — e.g. a stale
    shape left over from a previous schema version (session cookies persist across deploys)."""
    draft = session.get(SESSION_KEY)
    if not isinstance(draft, dict) or not isinstance(draft.get('groups'), list):
        session.pop(SESSION_KEY, None)
        return None
    return draft


def parse_confirm_settings(form):
    """Parse & validate exam settings from the confirm-step form.
    Returns (settings_dict, None) on success, or (None, error_message) on validation failure."""
    subject = form.get('subject', '').strip()
    if subject == '__other__':
        subject = form.get('subject_other', '').strip()
    exam_type = form.get('exam_type', 'practice')
    description = form.get('description', '').strip()
    class_ids = form.getlist('class_ids')
    is_draft = form.get('is_draft') == 'on'

    try:
        duration_minutes = int(form.get('duration_minutes', 30))
    except (ValueError, TypeError):
        duration_minutes = 30
    if duration_minutes not in DURATION_OPTIONS:
        duration_minutes = 30

    availability_mode = form.get('availability_mode', 'always')
    if availability_mode not in ('always', 'range', 'class_schedule'):
        availability_mode = 'always'
    available_from = available_to = None
    if availability_mode == 'range':
        raw_from = form.get('available_from', '').strip()
        raw_to = form.get('available_to', '').strip()
        try:
            available_from = datetime.fromisoformat(raw_from) if raw_from else None
            available_to = datetime.fromisoformat(raw_to) if raw_to else None
        except ValueError:
            available_from = available_to = None
        if available_from and available_to and available_from >= available_to:
            return None, 'Thời gian "đến ngày" phải sau thời gian "từ ngày".'

    try:
        allow_attempts = int(form.get('allow_attempts', 1))
    except (ValueError, TypeError):
        allow_attempts = 1

    folder_id = form.get('folder_id', type=int) or None
    if folder_id and not ExamFolder.query.get(folder_id):
        folder_id = None

    if not is_draft and not class_ids:
        return None, 'Vui lòng chọn ít nhất 1 lớp để giao đề, hoặc lưu dưới dạng nháp.'

    return {
        'subject': subject or 'Chung', 'exam_type': exam_type, 'description': description,
        'class_ids': class_ids, 'is_draft': is_draft, 'duration_minutes': duration_minutes,
        'availability_mode': availability_mode, 'available_from': available_from, 'available_to': available_to,
        'allow_attempts': allow_attempts, 'folder_id': folder_id,
    }, None


def parse_folder_fields(form):
    """Returns (fields_dict, error_message)."""
    name = form.get('name', '').strip()
    scope_type = form.get('scope_type', 'class')
    if scope_type not in ('class', 'subject'):
        scope_type = 'class'
    class_id = form.get('class_id', type=int)
    subject = form.get('subject', '').strip()

    if not name:
        return None, 'Vui lòng nhập tên thư mục.'
    if scope_type == 'class' and not class_id:
        return None, 'Vui lòng chọn lớp cho thư mục.'
    if scope_type == 'subject' and not subject:
        return None, 'Vui lòng nhập môn học cho thư mục.'

    return {
        'name': name, 'scope_type': scope_type,
        'class_id': class_id if scope_type == 'class' else None,
        'subject': subject if scope_type == 'subject' else None,
    }, None
