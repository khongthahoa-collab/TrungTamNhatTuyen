"""
Teacher-side online exam screens — separate routes and templates from the
admin ones (blueprints/admin/exams.py), sharing only the underlying models
and the parsing/validation logic in blueprints/exams_shared.py.
"""
import json
from urllib.parse import quote
from flask import abort, render_template, redirect, url_for, flash, request, session, Response
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from extensions import db
from models import Exam, ExamLog, ExamAttempt, ExamFolder, Class, Course, User
from blueprints.teacher import _teacher_score_class_ids, teacher_bp, require_teacher
from blueprints.exams_shared import (
    EXAM_TYPES, DURATION_OPTIONS, SESSION_KEY,
    parse_folder_fields, parse_groups_payload, require_owns_or_admin, require_teacher_exam_access,
    publish_exam, reset_student_exam_attempts,
    session_draft, parse_confirm_settings, posted_exam_draft,
)
from blueprints.pagination_utils import paginate_list


def _teacher_accessible_classes():
    teacher = current_user.teacher_profile
    if not teacher:
        return []
    class_ids = _teacher_score_class_ids(teacher)
    if not class_ids:
        return []
    return (Class.query.filter(Class.is_active.is_(True), Class.id.in_(class_ids))
            .order_by(Class.name).all())


def _validate_teacher_class_ids(class_ids):
    allowed_ids = {cls.id for cls in _teacher_accessible_classes()}
    try:
        selected_ids = {int(class_id) for class_id in class_ids}
    except (TypeError, ValueError):
        abort(403)
    if not selected_ids.issubset(allowed_ids):
        abort(403)


@teacher_bp.route('/exams')
@login_required
@require_teacher
def exams_list():
    folder_id = request.args.get('folder_id', type=int)
    subject = request.args.get('subject', '').strip()
    exam_type = request.args.get('exam_type', '').strip()
    class_id = request.args.get('class_id', type=int)
    status = request.args.get('status', '').strip()
    reuse_mode = request.args.get('reuse') == '1'
    search = request.args.get('q', '').strip()

    # Each teacher only sees exams they created themselves — not other teachers'/admin's.
    query = Exam.query.filter_by(created_by=current_user.id)
    if reuse_mode:
        query = Exam.query.filter(db.or_(
            Exam.created_by == current_user.id,
            db.and_(Exam.is_shared_with_teachers.is_(True), Exam.is_draft.is_(False)),
        ))
        if search:
            query = query.filter(db.or_(Exam.title.ilike(f'%{search}%'),
                                        Exam.subject.ilike(f'%{search}%'),
                                        Exam.creator.has(User.full_name.ilike(f'%{search}%'))))
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

    exams = query.order_by(Exam.created_at.desc()).all()
    if class_id:
        exams = [e for e in exams if class_id in e.class_list]

    folders = ExamFolder.query.filter_by(created_by=current_user.id).order_by(ExamFolder.name).all()
    classes = _teacher_accessible_classes()
    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()

    return render_template('teacher/exams_list.html', exams=exams, folders=folders, classes=classes,
                           courses=courses, exam_types=EXAM_TYPES,
                           folder_id=folder_id, subject=subject, exam_type=exam_type,
                           class_id=class_id, status=status, reuse_mode=reuse_mode, search=search)


@teacher_bp.route('/exams/folders/new', methods=['POST'])
@login_required
@require_teacher
def exam_folder_create():
    fields, error = parse_folder_fields(request.form)
    if error:
        flash(error, 'danger')
    else:
        if fields['scope_type'] == 'class':
            _validate_teacher_class_ids([fields['class_id']])
        folder = ExamFolder(created_by=current_user.id, **fields)
        db.session.add(folder)
        db.session.commit()
        flash(f'Đã tạo thư mục "{folder.name}".', 'success')
    return redirect(url_for('teacher.exams_list'))


@teacher_bp.route('/exams/<int:exam_id>/duplicate', methods=['POST'])
@login_required
@require_teacher
def exam_duplicate(exam_id):
    original = Exam.query.get_or_404(exam_id)
    require_teacher_exam_access(original)

    new_exam = Exam(
        title=f'{original.title} (bản sao)',
        subject=original.subject,
        exam_type=original.exam_type,
        description=original.description,
        scoring_mode=original.scoring_mode,
        class_ids='',
        folder_id=original.folder_id if original.created_by == current_user.id else None,
        duration_minutes=original.duration_minutes,
        availability_mode='always',
        allow_attempts=original.allow_attempts,
        scoring_config_json=original.scoring_config_json,
        shuffle_questions=True,
        shuffle_answers=True,
        is_draft=True,
        is_shared_with_teachers=False,
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
    return redirect(url_for('teacher.exams_confirm'))


@teacher_bp.route('/exams/<int:exam_id>/students/<int:student_id>/reset-attempts', methods=['POST'])
@login_required
@require_teacher
def exam_reset_attempts(exam_id, student_id):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)
    attempt_count, student_name = reset_student_exam_attempts(exam, student_id, current_user.id)
    if attempt_count:
        flash(
            f'Đã xóa {attempt_count} lượt làm bài của {student_name}. '
            'Học sinh có thể làm lại đề từ đầu.',
            'success',
        )
    else:
        flash('Học sinh không còn lịch sử làm bài của đề này.', 'info')
    return redirect(url_for('teacher.exams_results', exam_id=exam.id))


@teacher_bp.route('/exams/<int:exam_id>/sharing', methods=['POST'])
@login_required
@require_teacher
def exam_toggle_sharing(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)
    should_share = request.form.get('shared') == '1'

    if should_share and exam.is_draft:
        flash('Chỉ có thể công khai đề đã đăng cho các giáo viên khác.', 'warning')
    else:
        exam.is_shared_with_teachers = should_share
        db.session.add(ExamLog(
            user_id=current_user.id,
            action='share_exam' if should_share else 'unshare_exam',
            target_type='exam',
            target_id=exam.id,
            detail=f'{"Công khai đề" if should_share else "Gỡ công khai đề"} "{exam.title}" với giáo viên',
        ))
        db.session.commit()
        flash(
            f'Đã {"công khai" if should_share else "gỡ công khai"} đề "{exam.title}" '
            'với thư viện giáo viên.',
            'success',
        )

    if request.form.get('return_to') == 'preview':
        return redirect(url_for('teacher.exams_preview', exam_id=exam.id))
    list_args = {'reuse': '1'} if request.form.get('reuse') == '1' else {}
    return redirect(url_for('teacher.exams_list', **list_args))


@teacher_bp.route('/exams/<int:exam_id>/publish', methods=['POST'])
@login_required
@require_teacher
def exam_publish(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)
    published, message = publish_exam(exam, current_user.id)
    flash(message, 'success' if published else 'warning')
    return redirect(url_for('teacher.exams_list'))


@teacher_bp.route('/exams/<int:exam_id>/results')
@login_required
@require_teacher
def exams_results(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)

    attempts = ExamAttempt.query.options(joinedload(ExamAttempt.student)).filter_by(exam_id=exam.id).filter(
        ExamAttempt.student_id.isnot(None)).order_by(ExamAttempt.started_at.desc()).all()

    by_student = {}
    for a in attempts:
        row = by_student.setdefault(a.student_id, {
            'student': a.student, 'submitted_count': 0, 'latest': None, 'max_cheat': 0, 'flagged': False,
            'pending_essay_attempts': [],
        })
        if a.status == 'submitted':
            row['submitted_count'] += 1
            if a.result.get('pending_essay_count', 0) > 0:
                row['pending_essay_attempts'].append(a)
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
            'attempt': latest,
            'pending_essay_attempts': data['pending_essay_attempts'],
            'result': latest.result if latest else {},
            'attempts_count': data['submitted_count'],
            'duration_seconds': duration_seconds,
            'cheat_count': data['max_cheat'],
            'flagged': data['flagged'],
        })
    rows.sort(key=lambda r: r['student'].full_name if r['student'] else '')

    page = request.args.get('page', 1, type=int)
    pagination = paginate_list(rows, page, per_page=50)

    return render_template('teacher/exams_results.html', exam=exam, rows=pagination.items, pagination=pagination)


@teacher_bp.route('/exams/create', methods=['GET', 'POST'])
@login_required
@require_teacher
def exams_new():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        groups = parse_groups_payload(request.form.get('groups_json', '{}'))

        if not title or not groups:
            flash('Vui lòng nhập tên đề thi và ít nhất 1 câu hỏi hợp lệ trong các phần thi.', 'danger')
            return render_template('teacher/exams_form.html', prefill={'title': title, 'groups': groups})

        return _render_exam_confirm({'title': title, 'groups': groups})

    if request.args.get('mode') != 'compose':
        has_reusable_exams = Exam.query.filter(db.or_(
            Exam.created_by == current_user.id,
            db.and_(Exam.is_shared_with_teachers.is_(True), Exam.is_draft.is_(False)),
        )).first() is not None
        return render_template('teacher/exams_create.html', has_existing_exams=has_reusable_exams)

    draft = session_draft()
    return render_template('teacher/exams_form.html', prefill=draft)


@teacher_bp.route('/exams/edit/<int:exam_id>', methods=['GET', 'POST'])
@login_required
@require_teacher
def exams_edit(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        groups = parse_groups_payload(request.form.get('groups_json', '{}'))

        if not title or not groups:
            flash('Vui lòng nhập tên đề thi và ít nhất 1 câu hỏi hợp lệ trong các phần thi.', 'danger')
            return render_template('teacher/exams_form.html', prefill={'title': title, 'groups': groups},
                                   editing=True, exam=exam)

        return _render_exam_confirm(
            {'title': title, 'groups': groups, 'edit_exam_id': exam.id}, existing=exam,
        )

    draft = session_draft()
    if not draft or draft.get('edit_exam_id') != exam.id:
        draft = {'title': exam.title, 'groups': exam.question_groups}
    return render_template('teacher/exams_form.html', prefill=draft, editing=True, exam=exam)


def _render_exam_confirm(draft, existing=None, form=None):
    classes = _teacher_accessible_classes()
    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()
    folders = ExamFolder.query.filter_by(created_by=current_user.id).order_by(ExamFolder.name).all()
    return render_template(
        'teacher/exams_confirm.html', payload=draft, classes=classes, courses=courses,
        folders=folders, exam_types=EXAM_TYPES, durations=DURATION_OPTIONS, form=form,
        editing=bool(existing), existing=existing,
    )


@teacher_bp.route('/exams/confirm', methods=['GET', 'POST'])
@login_required
@require_teacher
def exams_confirm():
    """Handle exam settings with the draft carried in the POST body, falling back to old sessions."""
    has_posted_draft = request.method == 'POST' and 'groups_json' in request.form
    draft = posted_exam_draft(request.form) if has_posted_draft else session_draft()
    if not draft or not draft.get('groups'):
        flash('Vui lòng nhập nội dung đề thi trước.', 'warning')
        return redirect(url_for('teacher.exams_new', mode='compose'))

    existing = None
    edit_exam_id = draft.get('edit_exam_id')
    if edit_exam_id:
        existing = Exam.query.get_or_404(edit_exam_id)
        require_owns_or_admin(existing)

    if request.method == 'POST':
        settings, error = parse_confirm_settings(request.form, draft['groups'])
        if error:
            flash(error, 'danger')
            return _render_exam_confirm(draft, existing=existing, form=request.form)
        _validate_teacher_class_ids(settings['class_ids'])
        if settings['folder_id']:
            folder = ExamFolder.query.get(settings['folder_id'])
            if not folder or folder.created_by != current_user.id:
                abort(403)

        if existing:
            had_attempts = existing.attempts.count() > 0
            existing.title = draft['title']
            existing.subject = settings['subject']
            existing.exam_type = settings['exam_type']
            existing.scoring_mode = settings['scoring_mode']
            existing.scoring_config_json = json.dumps(settings['scoring_config'])
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
                scoring_mode=settings['scoring_mode'],
                scoring_config_json=json.dumps(settings['scoring_config']),
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

        return redirect(url_for('teacher.exams_list'))

    return _render_exam_confirm(draft, existing=existing)


@teacher_bp.route('/exams/<int:exam_id>/delete', methods=['POST'])
@login_required
@require_teacher
def exams_delete(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)
    db.session.delete(exam)
    db.session.add(ExamLog(user_id=current_user.id, action='delete_exam', target_type='exam', target_id=exam.id,
                           detail=f'Xóa đề "{exam.title}"'))
    db.session.commit()
    flash('Đã xóa đề thi.', 'success')
    return redirect(url_for('teacher.exams_list'))


@teacher_bp.route('/exams/<int:exam_id>/preview')
@login_required
@require_teacher
def exams_preview(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    require_teacher_exam_access(exam)
    is_shared_source = exam.created_by != current_user.id
    classes = (
        Class.query.filter(Class.id.in_(exam.class_list)).all()
        if exam.class_list and not is_shared_source else []
    )
    return render_template('teacher/exams_preview.html', exam=exam, classes=classes,
                           can_edit_exam=not is_shared_source, is_shared_source=is_shared_source)


@teacher_bp.route('/exams/<int:exam_id>/export')
@login_required
@require_teacher
def exams_export(exam_id):
    """Print-friendly export. fmt=pdf opens the browser print dialog (Save as PDF);
    fmt=doc downloads an HTML file Word can open directly."""
    exam = Exam.query.get_or_404(exam_id)
    require_teacher_exam_access(exam)
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
