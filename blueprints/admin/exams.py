import json
from urllib.parse import quote
from flask import render_template, redirect, url_for, flash, request, session, Response, abort
from flask_login import login_required, current_user
from extensions import db
from models import Exam, ExamLog, ExamAttempt, ExamFolder, Class, Course, User, UserRole
from blueprints.admin import admin_bp, require_admin_or_teacher
from blueprints.exams_shared import (
    EXAM_TYPES, DURATION_OPTIONS, SESSION_KEY,
    parse_groups_payload, require_owns_or_admin, session_draft,
    parse_confirm_settings, parse_folder_fields,
)


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


@admin_bp.route('/exam/folders/new', methods=['POST'])
@login_required
@require_admin_or_teacher
def exam_folder_create():
    fields, error = parse_folder_fields(request.form)
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

    fields, error = parse_folder_fields(request.form)
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
    require_owns_or_admin(exam)

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
        groups = parse_groups_payload(request.form.get('groups_json', '{}'))

        if not title or not groups:
            flash('Vui lòng nhập tên đề thi và ít nhất 1 câu hỏi hợp lệ trong các phần thi.', 'danger')
            return render_template('exams/admin_form.html', prefill={'title': title, 'groups': groups})

        session[SESSION_KEY] = {'title': title, 'groups': groups}
        return redirect(url_for('admin.exams_confirm'))

    draft = session_draft()
    return render_template('exams/admin_form.html', prefill=draft)


@admin_bp.route('/exam/edit/<int:exam_id>', methods=['GET', 'POST'])
@login_required
@require_admin_or_teacher
def exams_edit(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        groups = parse_groups_payload(request.form.get('groups_json', '{}'))

        if not title or not groups:
            flash('Vui lòng nhập tên đề thi và ít nhất 1 câu hỏi hợp lệ trong các phần thi.', 'danger')
            return render_template('exams/admin_form.html', prefill={'title': title, 'groups': groups},
                                   editing=True, exam=exam)

        session[SESSION_KEY] = {'title': title, 'groups': groups, 'edit_exam_id': exam.id}
        return redirect(url_for('admin.exams_confirm'))

    draft = session_draft()
    if not draft or draft.get('edit_exam_id') != exam.id:
        draft = {'title': exam.title, 'groups': exam.question_groups}
    return render_template('exams/admin_form.html', prefill=draft, editing=True, exam=exam)


@admin_bp.route('/exam/confirm', methods=['GET', 'POST'])
@login_required
@require_admin_or_teacher
def exams_confirm():
    """Shared step-2 settings page for both creating a new exam and editing an existing one —
    which mode is active is tracked entirely via the session draft's 'edit_exam_id'."""
    draft = session_draft()
    if not draft or not draft.get('groups'):
        flash('Vui lòng nhập nội dung đề thi trước.', 'warning')
        return redirect(url_for('admin.exams_new'))

    existing = None
    edit_exam_id = draft.get('edit_exam_id')
    if edit_exam_id:
        existing = Exam.query.get_or_404(edit_exam_id)
        require_owns_or_admin(existing)

    classes = Class.query.filter_by(is_active=True).order_by(Class.name).all()
    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()
    folders = ExamFolder.query.order_by(ExamFolder.name).all()

    if request.method == 'POST':
        settings, error = parse_confirm_settings(request.form)
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
    require_owns_or_admin(exam)
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
