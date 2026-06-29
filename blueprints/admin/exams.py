import json
import re
from datetime import datetime
from urllib.parse import quote
from flask import render_template, redirect, url_for, flash, request, session, Response, abort
from flask_login import login_required, current_user
from extensions import db
from models import Exam, ExamLog, ExamAttempt, ExamFolder, Class, Course, User, UserRole
from blueprints.admin import admin_bp, require_admin_or_teacher

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


def _parse_groups_payload(raw):
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


def _require_owns_or_admin(exam):
    if current_user.is_teacher and exam.created_by != current_user.id:
        abort(403)


def _session_draft():
    """Read the exam_draft session value, discarding it if missing or malformed — e.g. a stale
    shape left over from a previous schema version (session cookies persist across deploys)."""
    draft = session.get(SESSION_KEY)
    if not isinstance(draft, dict) or not isinstance(draft.get('groups'), list):
        session.pop(SESSION_KEY, None)
        return None
    return draft


def _parse_confirm_settings(form):
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


@admin_bp.route('/exam')
@login_required
@require_admin_or_teacher
def exams_list():
    folder_id = request.args.get('folder_id', type=int)
    subject = request.args.get('subject', '').strip()
    exam_type = request.args.get('exam_type', '').strip()
    class_id = request.args.get('class_id', type=int)
    status = request.args.get('status', '').strip()
    creator_id = request.args.get('creator_id', type=int)

    query = Exam.query
    if folder_id:
        query = query.filter_by(folder_id=folder_id)
    if subject:
        query = query.filter_by(subject=subject)
    if exam_type:
        query = query.filter_by(exam_type=exam_type)
    if status == 'draft':
        query = query.filter_by(is_draft=True)
    elif status == 'published':
        query = query.filter_by(is_draft=False)
    if creator_id:
        query = query.filter_by(created_by=creator_id)

    exams = query.order_by(Exam.created_at.desc()).all()
    if class_id:
        exams = [e for e in exams if class_id in e.class_list]

    folders = ExamFolder.query.order_by(ExamFolder.name).all()
    classes = Class.query.filter_by(is_active=True).order_by(Class.name).all()
    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()
    creators = User.query.filter(User.role.in_([UserRole.ADMIN, UserRole.TEACHER])).order_by(User.full_name).all()

    return render_template('exams/admin_list.html', exams=exams, folders=folders, classes=classes,
                           courses=courses, creators=creators, exam_types=EXAM_TYPES,
                           folder_id=folder_id, subject=subject, exam_type=exam_type,
                           class_id=class_id, status=status, creator_id=creator_id)


def _parse_folder_fields(form):
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


@admin_bp.route('/exam/folders/new', methods=['POST'])
@login_required
@require_admin_or_teacher
def exam_folder_create():
    fields, error = _parse_folder_fields(request.form)
    if error:
        flash(error, 'danger')
        return redirect(url_for('admin.documents'))

    folder = ExamFolder(created_by=current_user.id, **fields)
    db.session.add(folder)
    db.session.commit()
    flash(f'Đã tạo thư mục "{folder.name}".', 'success')
    return redirect(url_for('admin.documents'))


@admin_bp.route('/exam/folders/<int:folder_id>/edit', methods=['POST'])
@login_required
@require_admin_or_teacher
def exam_folder_edit(folder_id):
    folder = ExamFolder.query.get_or_404(folder_id)
    if current_user.is_teacher and folder.created_by != current_user.id:
        abort(403)

    fields, error = _parse_folder_fields(request.form)
    if error:
        flash(error, 'danger')
        return redirect(url_for('admin.documents'))

    folder.name = fields['name']
    folder.scope_type = fields['scope_type']
    folder.class_id = fields['class_id']
    folder.subject = fields['subject']
    db.session.commit()
    flash(f'Đã cập nhật thư mục "{folder.name}".', 'success')
    return redirect(url_for('admin.documents'))


@admin_bp.route('/exam/folders/<int:folder_id>/delete', methods=['POST'])
@login_required
@require_admin_or_teacher
def exam_folder_delete(folder_id):
    folder = ExamFolder.query.get_or_404(folder_id)
    if current_user.is_teacher and folder.created_by != current_user.id:
        abort(403)
    Exam.query.filter_by(folder_id=folder.id).update({'folder_id': None})
    db.session.delete(folder)
    db.session.commit()
    flash('Đã xóa thư mục (các đề thi trong thư mục vẫn được giữ lại).', 'success')
    return redirect(url_for('admin.documents'))


@admin_bp.route('/exam/<int:exam_id>/duplicate', methods=['POST'])
@login_required
@require_admin_or_teacher
def exam_duplicate(exam_id):
    original = Exam.query.get_or_404(exam_id)

    new_exam = Exam(
        title=f'{original.title} (bản sao)',
        subject=original.subject,
        exam_type=original.exam_type,
        description=original.description,
        class_ids='',
        folder_id=original.folder_id,
        duration_minutes=original.duration_minutes,
        availability_mode='always',
        allow_attempts=original.allow_attempts,
        shuffle_questions=True,
        shuffle_answers=True,
        is_draft=True,
        created_by=current_user.id,
        questions_json=original.questions_json,
    )
    db.session.add(new_exam)
    db.session.flush()
    db.session.add(ExamLog(user_id=current_user.id, action='duplicate_exam', target_type='exam',
                           target_id=new_exam.id, detail=f'Sao chép từ đề "{original.title}" (#{original.id})'))
    db.session.commit()

    session[SESSION_KEY] = {'title': new_exam.title, 'groups': new_exam.question_groups, 'edit_exam_id': new_exam.id}
    flash(f'Đã tạo bản sao "{new_exam.title}". Vui lòng kiểm tra nội dung và gán lớp học.', 'success')
    return redirect(url_for('admin.exams_confirm'))


@admin_bp.route('/exam/<int:exam_id>/results')
@login_required
@require_admin_or_teacher
def exams_results(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    _require_owns_or_admin(exam)

    attempts = ExamAttempt.query.filter_by(exam_id=exam.id).filter(
        ExamAttempt.student_id.isnot(None)).order_by(ExamAttempt.started_at.desc()).all()

    by_student = {}
    for a in attempts:
        row = by_student.setdefault(a.student_id, {
            'student': a.student, 'submitted_count': 0, 'latest': None, 'max_cheat': 0, 'flagged': False,
        })
        if a.status == 'submitted':
            row['submitted_count'] += 1
            if row['latest'] is None or a.started_at > row['latest'].started_at:
                row['latest'] = a
        row['max_cheat'] = max(row['max_cheat'], a.cheat_count or 0)
        row['flagged'] = row['flagged'] or bool(a.was_flagged)

    rows = []
    for data in by_student.values():
        latest = data['latest']
        duration_seconds = None
        if latest and latest.submitted_at and latest.started_at:
            duration_seconds = int((latest.submitted_at - latest.started_at).total_seconds())
        rows.append({
            'student': data['student'],
            'result': latest.result if latest else {},
            'attempts_count': data['submitted_count'],
            'duration_seconds': duration_seconds,
            'cheat_count': data['max_cheat'],
            'flagged': data['flagged'],
        })
    rows.sort(key=lambda r: r['student'].full_name if r['student'] else '')

    return render_template('exams/results.html', exam=exam, rows=rows)


@admin_bp.route('/exam/create', methods=['GET', 'POST'])
@login_required
@require_admin_or_teacher
def exams_new():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        groups = _parse_groups_payload(request.form.get('groups_json', '{}'))

        if not title or not groups:
            flash('Vui lòng nhập tên đề thi và ít nhất 1 câu hỏi hợp lệ trong các phần thi.', 'danger')
            return render_template('exams/admin_form.html', prefill={'title': title, 'groups': groups})

        session[SESSION_KEY] = {'title': title, 'groups': groups}
        return redirect(url_for('admin.exams_confirm'))

    draft = _session_draft()
    return render_template('exams/admin_form.html', prefill=draft)


@admin_bp.route('/exam/edit/<int:exam_id>', methods=['GET', 'POST'])
@login_required
@require_admin_or_teacher
def exams_edit(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    _require_owns_or_admin(exam)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        groups = _parse_groups_payload(request.form.get('groups_json', '{}'))

        if not title or not groups:
            flash('Vui lòng nhập tên đề thi và ít nhất 1 câu hỏi hợp lệ trong các phần thi.', 'danger')
            return render_template('exams/admin_form.html', prefill={'title': title, 'groups': groups},
                                   editing=True, exam=exam)

        session[SESSION_KEY] = {'title': title, 'groups': groups, 'edit_exam_id': exam.id}
        return redirect(url_for('admin.exams_confirm'))

    draft = _session_draft()
    if not draft or draft.get('edit_exam_id') != exam.id:
        draft = {'title': exam.title, 'groups': exam.question_groups}
    return render_template('exams/admin_form.html', prefill=draft, editing=True, exam=exam)


@admin_bp.route('/exam/confirm', methods=['GET', 'POST'])
@login_required
@require_admin_or_teacher
def exams_confirm():
    """Shared step-2 settings page for both creating a new exam and editing an existing one —
    which mode is active is tracked entirely via the session draft's 'edit_exam_id'."""
    draft = _session_draft()
    if not draft or not draft.get('groups'):
        flash('Vui lòng nhập nội dung đề thi trước.', 'warning')
        return redirect(url_for('admin.exams_new'))

    existing = None
    edit_exam_id = draft.get('edit_exam_id')
    if edit_exam_id:
        existing = Exam.query.get_or_404(edit_exam_id)
        _require_owns_or_admin(existing)

    classes = Class.query.filter_by(is_active=True).order_by(Class.name).all()
    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()
    folders = ExamFolder.query.order_by(ExamFolder.name).all()

    if request.method == 'POST':
        settings, error = _parse_confirm_settings(request.form)
        if error:
            flash(error, 'danger')
            return render_template('exams/confirm.html', payload=draft, classes=classes, courses=courses,
                                   folders=folders, exam_types=EXAM_TYPES, durations=DURATION_OPTIONS,
                                   form=request.form, editing=bool(existing), existing=existing)

        if existing:
            had_attempts = existing.attempts.count() > 0
            existing.title = draft['title']
            existing.subject = settings['subject']
            existing.exam_type = settings['exam_type']
            existing.description = settings['description']
            existing.class_ids = ','.join(settings['class_ids'])
            existing.folder_id = settings['folder_id']
            existing.duration_minutes = settings['duration_minutes']
            existing.availability_mode = settings['availability_mode']
            existing.available_from = settings['available_from']
            existing.available_to = settings['available_to']
            existing.allow_attempts = settings['allow_attempts']
            existing.is_draft = settings['is_draft']
            existing.questions_json = json.dumps({'groups': draft['groups']})

            detail = f'Cập nhật đề "{existing.title}"'
            if had_attempts:
                detail += ' (đề đã có học sinh làm bài — các kết quả cũ vẫn được giữ nguyên, chỉ áp dụng cho lượt làm mới)'
            db.session.add(ExamLog(user_id=current_user.id, action='update_exam', target_type='exam',
                                   target_id=existing.id, detail=detail))
            db.session.commit()
            session.pop(SESSION_KEY, None)
            flash('Đã lưu thay đổi đề thi.', 'success')
        else:
            exam = Exam(
                title=draft['title'],
                subject=settings['subject'],
                exam_type=settings['exam_type'],
                description=settings['description'],
                class_ids=','.join(settings['class_ids']),
                folder_id=settings['folder_id'],
                duration_minutes=settings['duration_minutes'],
                availability_mode=settings['availability_mode'],
                available_from=settings['available_from'],
                available_to=settings['available_to'],
                allow_attempts=settings['allow_attempts'],
                shuffle_questions=True,
                shuffle_answers=True,
                is_draft=settings['is_draft'],
                created_by=current_user.id,
                questions_json=json.dumps({'groups': draft['groups']}),
            )
            db.session.add(exam)
            db.session.flush()
            db.session.add(ExamLog(user_id=current_user.id, action='create_exam', target_type='exam', target_id=exam.id,
                                   detail=f'Tạo đề "{exam.title}" ({"nháp" if settings["is_draft"] else "đã đăng"})'))
            db.session.commit()
            session.pop(SESSION_KEY, None)
            flash('Đã tạo đề thi thành công.', 'success')

        return redirect(url_for('admin.exams_list'))

    return render_template('exams/confirm.html', payload=draft, classes=classes, courses=courses,
                           folders=folders, exam_types=EXAM_TYPES, durations=DURATION_OPTIONS, form=None,
                           editing=bool(existing), existing=existing)


@admin_bp.route('/exam/<int:exam_id>/delete', methods=['POST'])
@login_required
@require_admin_or_teacher
def exams_delete(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    _require_owns_or_admin(exam)
    db.session.delete(exam)
    db.session.add(ExamLog(user_id=current_user.id, action='delete_exam', target_type='exam', target_id=exam.id,
                           detail=f'Xóa đề "{exam.title}"'))
    db.session.commit()
    flash('Đã xóa đề thi.', 'success')
    return redirect(url_for('admin.exams_list'))


@admin_bp.route('/exam/<int:exam_id>/preview')
@login_required
@require_admin_or_teacher
def exams_preview(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    classes = Class.query.filter(Class.id.in_(exam.class_list)).all() if exam.class_list else []
    return render_template('exams/preview.html', exam=exam, classes=classes)


@admin_bp.route('/exam/<int:exam_id>/export')
@login_required
@require_admin_or_teacher
def exams_export(exam_id):
    """Print-friendly export. fmt=pdf opens the browser print dialog (Save as PDF);
    fmt=doc downloads an HTML file Word can open directly."""
    exam = Exam.query.get_or_404(exam_id)
    fmt = request.args.get('fmt', 'pdf')
    html = render_template('exams/export_print.html', exam=exam, fmt=fmt)

    if fmt == 'doc':
        ascii_title = exam.title.encode('ascii', 'ignore').decode('ascii')
        ascii_name = ''.join(c for c in ascii_title if c.isalnum() or c in (' ', '-', '_')).strip() or 'de-thi'
        encoded_name = quote(f'{exam.title}.doc')
        return Response(
            html,
            mimetype='application/msword',
            headers={'Content-Disposition': f'attachment; filename="{ascii_name}.doc"; filename*=UTF-8\'\'{encoded_name}'},
        )
    return Response(html, mimetype='text/html')
