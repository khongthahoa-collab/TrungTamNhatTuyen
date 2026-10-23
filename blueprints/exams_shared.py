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
from models import ExamAttempt, ExamFolder, ExamLog
from extensions import db

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
DURATION_OPTIONS = [15, 20, 30, 40, 45, 60, 90]
DEFAULT_TRUE_FALSE_WEIGHTS = [10, 25, 50, 100]
SESSION_KEY = 'exam_draft'

GROUP_TYPES = {'mcq', 'true_false', 'short_answer', 'essay', 'error_id'}
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


def _parse_essay_question(item):
    text = str(item.get('text', '')).strip()
    if not text:
        return None
    return {'text': text, 'explanation': str(item.get('explanation', '')).strip()}


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
    'essay': _parse_essay_question,
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


def posted_exam_draft(form):
    """Read a validated exam draft carried in the confirmation form instead of a session cookie."""
    title = form.get('title', '').strip()
    groups = parse_groups_payload(form.get('groups_json', ''))
    if not title or not groups:
        return None
    draft = {'title': title, 'groups': groups}
    edit_exam_id = form.get('edit_exam_id', type=int)
    if edit_exam_id:
        draft['edit_exam_id'] = edit_exam_id
    return draft


def require_owns_or_admin(exam):
    from services.auth_context import get_active_role
    if get_active_role(current_user) == 'teacher' and exam.created_by != current_user.id:
        abort(403)


def require_teacher_exam_access(exam, allow_shared=True):
    from services.auth_context import get_active_role
    if get_active_role(current_user) != 'teacher' or exam.created_by == current_user.id:
        return
    if allow_shared and exam.is_shared_with_teachers and not exam.is_draft:
        return
    abort(404)


def reset_student_exam_attempts(exam, student_id, actor_id):
    """Delete all attempts for one student/exam while preserving an audit log."""
    attempts = ExamAttempt.query.filter_by(exam_id=exam.id, student_id=student_id).all()
    if not attempts:
        return 0, None

    student_name = attempts[0].student.full_name if attempts[0].student else 'Học sinh đã xóa'
    attempt_count = len(attempts)
    ExamAttempt.query.filter_by(exam_id=exam.id, student_id=student_id).delete(
        synchronize_session=False
    )
    db.session.add(ExamLog(
        user_id=actor_id,
        action='reset_exam_attempts',
        target_type='exam',
        target_id=exam.id,
        detail=(
            f'Xóa {attempt_count} lượt làm bài của {student_name} '
            f'(student_id={student_id}) khỏi đề "{exam.title}" để cho phép làm lại'
        ),
    ))
    db.session.commit()
    return attempt_count, student_name


def publish_exam(exam, actor_id):
    """Publish a draft exam after verifying it is assigned to at least one class."""
    if not exam.class_list:
        return False, 'Hãy chọn ít nhất một lớp trước khi đăng đề.'
    if not exam.is_draft:
        return False, 'Đề thi này đã được đăng.'

    exam.is_draft = False
    db.session.add(ExamLog(
        user_id=actor_id,
        action='publish_exam',
        target_type='exam',
        target_id=exam.id,
        detail=f'Đăng đề "{exam.title}" từ danh sách đề thi',
    ))
    db.session.commit()
    return True, f'Đã đăng đề "{exam.title}".'


def session_draft():
    """Read the exam_draft session value, discarding it if missing or malformed — e.g. a stale
    shape left over from a previous schema version (session cookies persist across deploys)."""
    draft = session.get(SESSION_KEY)
    if not isinstance(draft, dict) or not isinstance(draft.get('groups'), list):
        session.pop(SESSION_KEY, None)
        return None
    return draft


def parse_confirm_settings(form, groups=None):
    """Parse & validate exam settings from the confirm-step form.
    Returns (settings_dict, None) on success, or (None, error_message) on validation failure."""
    subject = form.get('subject', '').strip()
    if subject == '__other__':
        subject = form.get('subject_other', '').strip()
    exam_type = form.get('exam_type', 'practice')
    scoring_mode = form.get('scoring_mode', 'question')
    if scoring_mode not in ('question', 'section', 'question_custom', 'section_custom'):
        return None, 'Vui lòng chọn cách chia điểm hợp lệ.'
    description = form.get('description', '').strip()
    class_ids = form.getlist('class_ids')
    draft_value = form.get('is_draft', 'draft')
    if draft_value in ('draft', 'published'):
        is_draft = draft_value == 'draft'
    elif draft_value in (None, 'on'):
        is_draft = True
    else:
        return None, 'Vui lòng chọn trạng thái đề hợp lệ.'

    raw_duration = form.get('duration_minutes', '40')
    if raw_duration == 'custom':
        raw_custom_duration = form.get('duration_custom', '').strip()
        match = re.fullmatch(r'(\d{1,2}):([0-5]\d)', raw_custom_duration)
        if not match:
            return None, 'Nhập thời lượng tùy chỉnh theo định dạng HH:MM, ví dụ 00:50 hoặc 01:15.'
        duration_minutes = int(match.group(1)) * 60 + int(match.group(2))
        if not 1 <= duration_minutes <= 1440:
            return None, 'Thời lượng làm bài phải từ 00:01 đến 24:00.'
    else:
        try:
            duration_minutes = int(raw_duration)
        except (ValueError, TypeError):
            return None, 'Vui lòng chọn thời lượng làm bài hợp lệ.'
        if duration_minutes not in DURATION_OPTIONS:
            return None, 'Vui lòng chọn thời lượng làm bài hợp lệ.'

    groups = groups if isinstance(groups, list) else []

    def parse_points(field_name, label):
        raw_value = form.get(field_name, '').strip().replace(',', '.')
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return None, f'Nhập điểm hợp lệ cho {label}.'
        if not 0 < value <= 1000:
            return None, f'Điểm của {label} phải lớn hơn 0 và không quá 1000.'
        return round(value, 4), None

    question_points = []
    section_points = []
    for group_index, group in enumerate(groups):
        section_point, error = parse_points(
            f'section_points_{group_index}', f'phần {group_index + 1}'
        )
        if error:
            return None, error
        section_points.append(section_point)

        points_for_group = []
        for question_index, _question in enumerate(group.get('questions', [])):
            point, error = parse_points(
                f'question_points_{group_index}_{question_index}',
                f'câu {question_index + 1} phần {group_index + 1}',
            )
            if error:
                return None, error
            points_for_group.append(point)
        question_points.append(points_for_group)

    true_false_weights = []
    for correct_count, default in enumerate(DEFAULT_TRUE_FALSE_WEIGHTS, start=1):
        raw_weight = form.get(f'true_false_weight_{correct_count}', str(default)).strip().replace(',', '.')
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError):
            return None, f'Nhập trọng số hợp lệ khi trả lời đúng {correct_count} ý.'
        if not 0 <= weight <= 100:
            return None, 'Trọng số câu đúng/sai phải nằm trong khoảng 0% đến 100%.'
        true_false_weights.append(round(weight, 4))
    if true_false_weights != sorted(true_false_weights):
        return None, 'Trọng số đúng/sai phải tăng dần theo số ý trả lời đúng.'

    scoring_config = {
        'question_points': question_points,
        'section_points': section_points,
        'true_false_weights': true_false_weights,
    }

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
        'scoring_mode': scoring_mode, 'scoring_config': scoring_config,
        'class_ids': class_ids, 'is_draft': is_draft, 'duration_minutes': duration_minutes,
        'availability_mode': availability_mode, 'available_from': available_from, 'available_to': available_to,
        'allow_attempts': allow_attempts, 'folder_id': folder_id,
    }, None


def apply_manual_essay_scores(result, scores):
    """Recompute a stored result after updating weighted essay points."""
    questions = result.get('essay_questions', [])
    question_keys = {question['key'] for question in questions}
    essay_scores = {
        key: float(value)
        for key, value in scores.items()
        if key in question_keys
    }
    breakdown = [dict(group) for group in result.get('auto_breakdown', result.get('breakdown', []))]
    for question in questions:
        if question['key'] in essay_scores:
            group_index = question['group_index']
            breakdown[group_index]['earned'] += essay_scores[question['key']]
    for group in breakdown:
        group['earned'] = round(group['earned'], 2)

    total_earned = result.get('auto_earned', result.get('earned', 0)) + sum(essay_scores.values())
    total_weight = result.get('total', 0)
    result.update({
        'earned': round(total_earned, 2),
        'percent': int(round(total_earned / total_weight * 100)) if total_weight else 0,
        'score_10': round(total_earned / total_weight * 10, 1) if total_weight else 0,
        'breakdown': breakdown,
        'essay_scores': essay_scores,
        'pending_essay_count': len(questions) - len(essay_scores),
    })
    return result


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
    if len(name) > 200:
        return None, 'Tên thư mục không được vượt quá 200 ký tự.'
    if scope_type == 'class' and not class_id:
        return None, 'Vui lòng chọn lớp cho thư mục.'
    if scope_type == 'subject' and not subject:
        return None, 'Vui lòng nhập môn học cho thư mục.'

    return {
        'name': name, 'scope_type': scope_type,
        'class_id': class_id if scope_type == 'class' else None,
        'subject': subject if scope_type == 'subject' else None,
    }, None


def review_attempt_answers(exam, attempt):
    """Build submitted answers and correct answers in the order the student saw them."""
    order_data = attempt.order_data
    submitted_answers = attempt.answers
    groups_order = order_data.get('groups') or []
    answer_groups = []
    for gi, group in enumerate(exam.question_groups):
        questions = group.get('questions', [])
        go = groups_order[gi] if gi < len(groups_order) else {}
        group_type = group.get('type')
        q_order = go.get('q_order') or list(range(len(questions)))
        opt_orders = go.get('opt_orders') or {}
        reviewed_questions = []
        for position, orig_qi in enumerate(q_order, start=1):
            if orig_qi >= len(questions):
                continue
            question = questions[orig_qi]
            field = f'g{gi}_q{position}'
            reviewed = {
                'position': position,
                'text': question.get('text', ''),
                'explanation': (question.get('explanation') or '').strip(),
            }
            if group_type == 'mcq':
                options = question.get('options', [])
                option_order = opt_orders.get(str(orig_qi)) or list(range(len(options)))
                raw_choice = submitted_answers.get(field, '')
                try:
                    selected_position = int(raw_choice) if raw_choice else None
                except (ValueError, TypeError):
                    selected_position = None
                correct_index = question.get('correct_index')
                correct_position = next(
                    (i for i, original_index in enumerate(option_order, start=1)
                     if original_index == correct_index),
                    None,
                )
                reviewed['options'] = [
                    {
                        'label': chr(ord('A') + display_index),
                        'text': options[original_index],
                        'selected': selected_position == display_index + 1,
                        'correct': correct_position == display_index + 1,
                    }
                    for display_index, original_index in enumerate(option_order)
                    if original_index < len(options)
                ]
            elif group_type == 'true_false':
                statements = question.get('statements', [])
                option_order = opt_orders.get(str(orig_qi)) or list(range(len(statements)))
                submitted = submitted_answers.get(field, {})
                if not isinstance(submitted, dict):
                    submitted = {}
                reviewed['statements'] = [
                    {
                        'label': chr(ord('a') + display_index),
                        'text': statements[original_index].get('text', ''),
                        'selected': submitted.get(str(display_index + 1), ''),
                        'correct': bool(statements[original_index].get('correct')),
                    }
                    for display_index, original_index in enumerate(option_order)
                    if original_index < len(statements)
                ]
            elif group_type == 'short_answer':
                reviewed['student_answer'] = submitted_answers.get(field, '')
                reviewed['correct_answers'] = question.get('accepted_answers', [])
            elif group_type == 'essay':
                reviewed['student_answer'] = submitted_answers.get(field, '')
                reviewed['key'] = f'g{gi}_q{orig_qi}'
            elif group_type == 'error_id':
                reviewed['student_answer'] = submitted_answers.get(field, '')
                reviewed['correct_answer'] = question.get('correct_label', '')
            reviewed_questions.append(reviewed)

        if reviewed_questions:
            answer_groups.append({
                'title': group.get('title', ''),
                'type': group_type,
                'questions': reviewed_questions,
            })
    return answer_groups
