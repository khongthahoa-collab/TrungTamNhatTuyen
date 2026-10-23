import json
from datetime import datetime
from urllib.parse import quote
from flask import render_template, redirect, url_for, flash, request, session, Response, abort
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from extensions import db
from models import Exam, ExamLog, ExamAttempt, ExamFolder, Class, Course, User, UserRole
from blueprints.admin import admin_bp, require_admin, require_admin_or_teacher
from blueprints.exams_shared import (
    EXAM_TYPES, DURATION_OPTIONS, SESSION_KEY,
    apply_manual_essay_scores, parse_groups_payload, require_owns_or_admin,
    require_teacher_exam_access, reset_student_exam_attempts, session_draft,
    parse_confirm_settings, parse_folder_fields, posted_exam_draft, regrade_submitted_attempts, has_stale_scoring,
)
from blueprints.pagination_utils import paginate_list
from services.auth_context import get_active_role


@admin_bp.route('/exam')
@login_required
@require_admin_or_teacher
def exams_list():
    folder_id = request.args.get('folder_id', type=int)
    subject = request.args.get('subject', '').strip()
    exam_type = request.args.get('exam_type', '').strip()
    class_id = request.args.get('class_id', type=int)
    status = request.args.get('status', '').strip()
    sharing = request.args.get('sharing', '').strip()
    creator_id = request.args.get('creator_id', type=int)

    query = Exam.query.options(joinedload(Exam.folder), joinedload(Exam.creator))
    if get_active_role(current_user) == 'teacher':
        query = query.filter(db.or_(
            Exam.created_by == current_user.id,
            db.and_(Exam.is_shared_with_teachers.is_(True), Exam.is_draft.is_(False)),
        ))
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
    if sharing == 'shared':
        query = query.filter_by(is_shared_with_teachers=True)
    elif sharing == 'private':
        query = query.filter_by(is_shared_with_teachers=False)
    if creator_id:
        query = query.filter_by(created_by=creator_id)

    query = query.order_by(Exam.created_at.desc())
    page = request.args.get('page', 1, type=int)
    if class_id:
        # class_list is parsed from a comma-separated text column in Python,
        # not a real SQL-filterable column — can't paginate at the query
        # level since the true row count isn't known until after this
        # Python-side filter, so slice the already-filtered list instead.
        matched = [e for e in query.all() if class_id in e.class_list]
        pagination = paginate_list(matched, page, per_page=10)
    else:
        pagination = query.paginate(page=page, per_page=10, error_out=False)
    exams = pagination.items

    folders = ExamFolder.query.order_by(ExamFolder.name).all()
    classes = Class.query.filter_by(is_active=True).order_by(Class.name).all()
    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()
    creators = User.query.filter(User.role.in_([UserRole.ADMIN, UserRole.TEACHER])).order_by(User.full_name).all()

    # taken_exam_ids batched here instead of calling exam.taken_status per
    # row in the template — that property runs its own
    # attempts.filter_by(status='submitted').first() query per exam.
    non_draft_ids = [e.id for e in exams if not e.is_draft]
    taken_exam_ids = set()
    if non_draft_ids:
        taken_exam_ids = {
            r[0] for r in db.session.query(ExamAttempt.exam_id)
            .filter(ExamAttempt.exam_id.in_(non_draft_ids), ExamAttempt.status == 'submitted')
            .distinct().all()
        }

    return render_template('exams/admin_list.html', exams=exams, folders=folders, classes=classes,
                           courses=courses, creators=creators, exam_types=EXAM_TYPES,
                           folder_id=folder_id, subject=subject, exam_type=exam_type, sharing=sharing,
                           class_id=class_id, status=status, creator_id=creator_id,
                           pagination=pagination, taken_exam_ids=taken_exam_ids, now=datetime.utcnow(),
                           can_manage_exam_sharing=current_user.is_admin
                           and get_active_role(current_user) == 'admin')


@admin_bp.route('/exam/<int:exam_id>/sharing', methods=['POST'])
@login_required
@require_admin
def exam_toggle_sharing(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    should_share = request.form.get('shared') == '1'
    if should_share and exam.is_draft:
        flash('Chỉ có thể chia sẻ đề đã đăng cho giáo viên khác.', 'warning')
    else:
        exam.is_shared_with_teachers = should_share
        db.session.add(ExamLog(
            user_id=current_user.id,
            action='share_exam' if should_share else 'unshare_exam',
            target_type='exam',
            target_id=exam.id,
            detail=f'{"Chia sẻ đề" if should_share else "Gỡ chia sẻ đề"} "{exam.title}" với giáo viên',
        ))
        db.session.commit()
        flash(
            f'Đã {"chia sẻ" if should_share else "gỡ chia sẻ"} đề "{exam.title}" '
            'với thư viện giáo viên.',
            'success',
        )
    return redirect(url_for('admin.exams_list'))


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
    return redirect(url_for('admin.exams_confirm'))


@admin_bp.route('/exam/<int:exam_id>/results')
@login_required
@require_admin_or_teacher
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

    return render_template('exams/results.html', exam=exam, rows=pagination.items, pagination=pagination)


@admin_bp.route('/exam/<int:exam_id>/student/<int:student_id>/reset-attempts', methods=['POST'])
@login_required
@require_admin_or_teacher
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
    return redirect(url_for('admin.exams_results', exam_id=exam.id))


@admin_bp.route('/exam/<int:exam_id>/attempt/<int:attempt_id>/grade', methods=['GET', 'POST'])
@login_required
@require_admin_or_teacher
def exams_grade_attempt(exam_id, attempt_id):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)
    attempt = ExamAttempt.query.filter_by(id=attempt_id, exam_id=exam.id, status='submitted').first_or_404()
    result = attempt.result
    essay_questions = result.get('essay_questions', [])
    if not essay_questions:
        abort(404)

    answers = attempt.answers
    items = []
    for item in essay_questions:
        key = item['key']
        items.append({
            'key': key,
            'title': item.get('group_title', ''),
            'position': item.get('position', 1),
            'text': item.get('question_text', ''),
            'answer': answers.get(item.get('answer_field', ''), ''),
            'max_score': round(item['weight'], 4),
            'score': result.get('essay_scores', {}).get(key, ''),
        })

    if request.method == 'POST':
        updated_scores = dict(result.get('essay_scores', {}))
        errors = []
        for item in items:
            raw_score = request.form.get(f"score_{item['key']}", '').strip()
            item['score'] = raw_score
            if not raw_score:
                continue
            try:
                score = float(raw_score)
            except ValueError:
                errors.append(f"Câu {item['position']}: điểm phải là một số.")
                continue
            if not 0 <= score <= item['max_score'] + 1e-6:
                errors.append(
                    f"Câu {item['position']}: điểm phải từ 0 đến {item['max_score']:g}."
                )
                continue
            updated_scores[item['key']] = score

        if errors:
            for error in errors:
                flash(error, 'danger')
        else:
            result = apply_manual_essay_scores(result, updated_scores)
            attempt.result_json = json.dumps(result)
            attempt.score = result['percent'] if result['pending_essay_count'] == 0 else 0
            db.session.commit()
            flash(
                'Đã lưu điểm tự luận.' if result['pending_essay_count'] == 0
                else 'Đã lưu phần đã chấm; bài vẫn còn câu tự luận chờ chấm.',
                'success',
            )
            if get_active_role(current_user) == 'teacher':
                return redirect(url_for('teacher.exams_results', exam_id=exam.id))
            return redirect(url_for('admin.exams_results', exam_id=exam.id))

    return render_template(
        'exams/grade_attempt.html',
        exam=exam,
        attempt=attempt,
        items=items,
        result=result,
        base_template='teacher/base.html' if get_active_role(current_user) == 'teacher' else 'admin/base.html',
        results_url=url_for(
            'teacher.exams_results' if get_active_role(current_user) == 'teacher' else 'admin.exams_results',
            exam_id=exam.id,
        ),
    )


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

        return _render_admin_exam_confirm({'title': title, 'groups': groups})

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

        return _render_admin_exam_confirm(
            {'title': title, 'groups': groups, 'edit_exam_id': exam.id}, existing=exam,
        )

    draft = session_draft()
    if not draft or draft.get('edit_exam_id') != exam.id:
        draft = {'title': exam.title, 'groups': exam.question_groups}
    return render_template('exams/admin_form.html', prefill=draft, editing=True, exam=exam)


def _render_admin_exam_confirm(draft, existing=None, form=None):
    classes = Class.query.filter_by(is_active=True).order_by(Class.name).all()
    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()
    folders = ExamFolder.query.order_by(ExamFolder.name).all()
    return render_template(
        'exams/confirm.html', payload=draft, classes=classes, courses=courses,
        folders=folders, exam_types=EXAM_TYPES, durations=DURATION_OPTIONS, form=form,
        editing=bool(existing), existing=existing,
    )


@admin_bp.route('/exam/confirm', methods=['GET', 'POST'])
@login_required
@require_admin_or_teacher
def exams_confirm():
    """Handle exam settings with the draft carried in the POST body, falling back to old sessions."""
    has_posted_draft = request.method == 'POST' and 'groups_json' in request.form
    draft = posted_exam_draft(request.form) if has_posted_draft else session_draft()
    if not draft or not draft.get('groups'):
        flash('Vui lòng nhập nội dung đề thi trước.', 'warning')
        return redirect(url_for('admin.exams_new'))

    existing = None
    edit_exam_id = draft.get('edit_exam_id')
    if edit_exam_id:
        existing = Exam.query.get_or_404(edit_exam_id)
        require_owns_or_admin(existing)

    if request.method == 'POST':
        settings, error = parse_confirm_settings(request.form, draft['groups'])
        if error:
            flash(error, 'danger')
            return _render_admin_exam_confirm(draft, existing=existing, form=request.form)

        if existing:
            had_attempts = existing.attempts.count() > 0
            scoring_changed = (existing.scoring_mode, existing.scoring_config_json) != (
                settings['scoring_mode'], json.dumps(settings['scoring_config'])
            ) or (had_attempts and has_stale_scoring(existing, settings['scoring_mode']))
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
                regraded, skipped = regrade_submitted_attempts(existing) if scoring_changed else (0, 0)
                if scoring_changed:
                    detail += f' (đã tính lại điểm {regraded} bài đã nộp theo cách chia điểm mới'
                    detail += f', bỏ qua {skipped} bài do cấu trúc đề đã thay đổi)' if skipped else ')'
                else:
                    detail += ' (đề đã có học sinh làm bài — kết quả cũ được giữ nguyên)'
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

        return redirect(url_for('admin.exams_list'))

    return _render_admin_exam_confirm(draft, existing=existing)


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
    require_teacher_exam_access(exam)
    is_shared_source = get_active_role(current_user) == 'teacher' and exam.created_by != current_user.id
    classes = (
        Class.query.filter(Class.id.in_(exam.class_list)).all()
        if exam.class_list and not is_shared_source else []
    )
    return render_template('exams/preview.html', exam=exam, classes=classes,
                           can_edit_exam=get_active_role(current_user) != 'teacher'
                           or exam.created_by == current_user.id,
                           is_shared_source=is_shared_source)


@admin_bp.route('/exam/<int:exam_id>/export')
@login_required
@require_admin_or_teacher
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
