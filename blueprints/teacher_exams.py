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
from models import Exam, ExamLog, ExamAttempt, ExamFolder, Class, Course, Enrollment, Student, User
from blueprints.teacher import _teacher_score_class_ids, teacher_bp, require_teacher
from blueprints.exams_shared import (
    EXAM_TYPES, DURATION_OPTIONS, SESSION_KEY,
    exam_assignment_options, exam_is_assigned_to_student,
    edited_question_from_form, parse_folder_fields, parse_groups_payload,
    require_owns_or_admin, require_teacher_exam_access,
    publish_exam, reset_student_exam_attempts,
    session_draft, parse_confirm_settings, posted_exam_draft, review_attempt_answers,
    apply_manual_essay_scores, regrade_submitted_attempts, has_stale_scoring,
    regrade_attempt_if_stale,
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


def _validate_teacher_assignment_targets(school_ids, student_ids):
    class_ids = [cls.id for cls in _teacher_accessible_classes()]
    allowed_schools, allowed_students = exam_assignment_options(class_ids)
    if not set(school_ids).issubset({school.id for school in allowed_schools}):
        abort(403)
    if not set(student_ids).issubset({student.id for student in allowed_students}):
        abort(403)


def _folder_matches_exam(folder, exam):
    return _folder_matches_assignment(folder, exam.subject, exam.class_list)


def _folder_matches_assignment(folder, subject, class_ids):
    if not folder:
        return True
    if folder.scope_type == 'class':
        return not class_ids or folder.class_id in class_ids
    return not subject or (folder.subject or '').casefold() == subject.casefold()


@teacher_bp.route('/exams')
@login_required
@require_teacher
def exams_list():
    folder_id = request.args.get('folder_id', type=int)
    reuse_mode = request.args.get('reuse') == '1'
    current_folder = None
    if folder_id and not reuse_mode:
        current_folder = ExamFolder.query.filter_by(
            id=folder_id, created_by=current_user.id
        ).first_or_404()
    subject = request.args.get('subject', '').strip()
    content_grade = request.args.get('content_grade', '').strip()
    exam_type = request.args.get('exam_type', '').strip()
    class_id = request.args.get('class_id', type=int)
    status = request.args.get('status', '').strip()
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
    if not reuse_mode and current_folder:
        query = query.filter_by(folder_id=current_folder.id)
    if subject:
        query = query.filter_by(subject=subject)
    if content_grade:
        query = query.filter_by(content_grade=content_grade)
    if exam_type:
        query = query.filter_by(exam_type=exam_type)
    if status == 'draft':
        query = query.filter_by(is_draft=True)
    elif status == 'published':
        query = query.filter_by(is_draft=False)

    query = query.order_by(Exam.created_at.desc(), Exam.id.desc())
    exams = query.all() if reuse_mode or class_id else query.limit(10).all()
    if class_id:
        exams = [e for e in exams if class_id in e.class_list]
        if not reuse_mode:
            exams = exams[:10]

    folders = ExamFolder.query.filter_by(created_by=current_user.id).order_by(ExamFolder.name).all()
    child_folders = [
        folder for folder in folders
        if folder.parent_id == (current_folder.id if current_folder else None)
    ]
    folder_exam_counts = {
        folder_row[0]: folder_row[1]
        for folder_row in db.session.query(Exam.folder_id, db.func.count(Exam.id)).filter(
            Exam.created_by == current_user.id,
            Exam.folder_id.isnot(None),
        ).group_by(Exam.folder_id).all()
    }
    classes = _teacher_accessible_classes()
    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()
    exam_ids = [exam.id for exam in exams]
    submission_counts = {}
    active_exam_ids = set()
    exams_with_attempts = set()
    if exam_ids:
        exams_with_attempts = {
            exam_id for exam_id, in db.session.query(ExamAttempt.exam_id).filter(
                ExamAttempt.exam_id.in_(exam_ids)
            ).distinct().all()
        }
        for row in db.session.query(
            ExamAttempt.exam_id,
            db.func.count(ExamAttempt.id),
            db.func.count(db.func.distinct(ExamAttempt.student_id)),
        ).filter(
            ExamAttempt.exam_id.in_(exam_ids),
            ExamAttempt.status == 'submitted',
            ExamAttempt.student_id.isnot(None),
        ).group_by(ExamAttempt.exam_id).all():
            submission_counts[row[0]] = {'attempts': row[1], 'students': row[2]}
        active_exam_ids = {
            exam_id for exam_id, in db.session.query(ExamAttempt.exam_id).filter(
                ExamAttempt.exam_id.in_(exam_ids),
                ExamAttempt.status == 'in_progress',
            ).distinct().all()
        }

    class_ids = {class_id for exam in exams for class_id in exam.class_list}
    classes_by_id = {
        cls.id: cls.name for cls in Class.query.filter(Class.id.in_(class_ids)).all()
    } if class_ids else {}

    accessible_class_ids = [cls.id for cls in classes]
    _schools, target_students = exam_assignment_options(accessible_class_ids)
    student_class_ids = {}
    if target_students and accessible_class_ids:
        for enrolled_class_id, student_id in db.session.query(
            Enrollment.class_id, Enrollment.student_id
        ).filter(
            Enrollment.class_id.in_(accessible_class_ids),
            Enrollment.student_id.in_([student.id for student in target_students]),
            Enrollment.is_active.is_(True),
        ).all():
            student_class_ids.setdefault(student_id, set()).add(enrolled_class_id)
    students_by_id = {student.id: student for student in target_students}

    exam_rows = []
    for exam in exams:
        submitted = submission_counts.get(exam.id, {'attempts': 0, 'students': 0})
        assigned_students = {
            student_id for student_id, student in students_by_id.items()
            if exam_is_assigned_to_student(
                exam, student, active_class_ids=student_class_ids.get(student_id, set()),
                teacher_class_ids=accessible_class_ids,
            )
        }
        class_names = [
            classes_by_id[class_id] for class_id in exam.class_list if class_id in classes_by_id
        ]
        school_names = {
            school.id: school.name for school in _schools
        }
        exam_rows.append({
            'exam': exam,
            'submission_count': submitted['attempts'],
            'submitted_students': submitted['students'],
            'assigned_students': len(assigned_students),
            'class_names': class_names,
            'school_names': [school_names[id_] for id_ in exam.school_list if id_ in school_names],
            'student_names': [
                students_by_id[id_].full_name for id_ in exam.student_list if id_ in students_by_id
            ],
            'active_attempts': exam.id in active_exam_ids,
            'has_attempts': exam.id in exams_with_attempts,
        })

    breadcrumbs = []
    folder = current_folder
    while folder:
        breadcrumbs.append(folder)
        folder = folder.parent
    breadcrumbs.reverse()

    return render_template('teacher/exams_list.html', exams=exams, exam_rows=exam_rows,
                           folders=folders, child_folders=child_folders, current_folder=current_folder,
                           folder_exam_counts=folder_exam_counts, breadcrumbs=breadcrumbs, classes=classes,
                           courses=courses, exam_types=EXAM_TYPES,
                           folder_id=folder_id, subject=subject, exam_type=exam_type,
                           class_id=class_id, status=status, reuse_mode=reuse_mode, search=search,
                           content_grade=content_grade)


@teacher_bp.route('/exams/folders/new', methods=['POST'])
@login_required
@require_teacher
def exam_folder_create():
    parent_id = request.form.get('parent_folder_id', type=int)
    parent_folder = None
    if parent_id:
        parent_folder = ExamFolder.query.filter_by(
            id=parent_id, created_by=current_user.id
        ).first_or_404()
        name = request.form.get('name', '').strip()
        if not name:
            fields, error = None, 'Vui lòng nhập tên thư mục.'
        elif len(name) > 200:
            fields, error = None, 'Tên thư mục không được vượt quá 200 ký tự.'
        else:
            fields, error = {
                'name': name,
                'parent_id': parent_folder.id,
                'scope_type': parent_folder.scope_type,
                'class_id': parent_folder.class_id,
                'subject': parent_folder.subject,
            }, None
    else:
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
        if parent_folder:
            return redirect(url_for('teacher.exams_list', folder_id=parent_folder.id))
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
        content_grade=original.content_grade,
        exam_type=original.exam_type,
        description=original.description,
        scoring_mode=original.scoring_mode,
        class_ids='',
        school_ids='',
        student_ids='',
        folder_id=original.folder_id if (
            original.created_by == current_user.id and original.folder
            and original.folder.scope_type != 'class'
        ) else None,
        duration_minutes=original.duration_minutes,
        availability_mode='always',
        allow_attempts=original.allow_attempts,
        scoring_config_json=original.scoring_config_json,
        shuffle_questions=original.shuffle_questions,
        shuffle_answers=original.shuffle_answers,
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
    list_args = {'reuse': '1'} if request.form.get('reuse') == '1' else {'folder_id': exam.folder_id}
    return redirect(url_for('teacher.exams_list', **list_args))


@teacher_bp.route('/exams/<int:exam_id>/publish', methods=['POST'])
@login_required
@require_teacher
def exam_publish(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)
    _validate_teacher_class_ids(exam.class_list)
    _validate_teacher_assignment_targets(exam.school_list, exam.student_list)
    published, message = publish_exam(exam, current_user.id)
    flash(message, 'success' if published else 'warning')
    return redirect(url_for('teacher.exams_list', folder_id=exam.folder_id))


@teacher_bp.route('/exams/<int:exam_id>/unpublish', methods=['POST'])
@login_required
@require_teacher
def exam_unpublish(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)
    active_attempts = ExamAttempt.query.filter_by(exam_id=exam.id, status='in_progress').count()
    if active_attempts:
        flash('Chưa thể hủy xuất bản khi học sinh đang làm bài.', 'warning')
    elif exam.is_draft:
        flash('Đề thi này hiện đang ở trạng thái nháp.', 'info')
    else:
        exam.is_draft = True
        db.session.add(ExamLog(
            user_id=current_user.id, action='unpublish_exam', target_type='exam',
            target_id=exam.id, detail=f'Hủy xuất bản đề "{exam.title}"',
        ))
        db.session.commit()
        flash('Đã hủy xuất bản đề. Lịch sử bài làm được giữ nguyên.', 'success')
    return redirect(url_for('teacher.exams_list', folder_id=exam.folder_id))


@teacher_bp.route('/exams/<int:exam_id>/settings', methods=['POST'])
@login_required
@require_teacher
def exam_settings(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)
    title = request.form.get('title', '').strip()
    folder_id = request.form.get('folder_id', type=int)
    folder = ExamFolder.query.filter_by(
        id=folder_id, created_by=current_user.id
    ).first() if folder_id else None
    if not title:
        flash('Tên đề thi không được để trống.', 'danger')
    elif len(title) > 200:
        flash('Tên đề thi không được vượt quá 200 ký tự.', 'danger')
    elif folder_id and not folder:
        abort(403)
    elif folder and folder.id != exam.folder_id and not _folder_matches_exam(folder, exam):
        flash('Thư mục không phù hợp với môn học hoặc lớp được giao của đề.', 'warning')
    else:
        old_title = exam.title
        exam.title = title
        exam.folder_id = folder.id if folder else None
        db.session.add(ExamLog(
            user_id=current_user.id, action='update_exam_settings', target_type='exam',
            target_id=exam.id, detail=f'Cập nhật cài đặt đề "{old_title}"',
        ))
        db.session.commit()
        flash('Đã cập nhật cài đặt đề thi.', 'success')
    return redirect(url_for('teacher.exams_list', folder_id=exam.folder_id))


@teacher_bp.route('/exams/<int:exam_id>/move', methods=['POST'])
@login_required
@require_teacher
def exam_move(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)
    folder_id = request.form.get('folder_id', type=int)
    folder = ExamFolder.query.filter_by(
        id=folder_id, created_by=current_user.id
    ).first() if folder_id else None
    if folder_id and not folder:
        abort(403)
    if folder and folder.id == exam.folder_id:
        flash('Đề thi hiện đã ở trong thư mục được chọn.', 'info')
    elif not _folder_matches_exam(folder, exam):
        flash('Không thể chuyển đề vào thư mục khác môn học hoặc lớp được giao.', 'warning')
    else:
        exam.folder_id = folder.id if folder else None
        db.session.add(ExamLog(
            user_id=current_user.id, action='move_exam_folder', target_type='exam',
            target_id=exam.id,
            detail=f'Chuyển đề "{exam.title}" đến {folder.path_label if folder else "Tất cả"}',
        ))
        db.session.commit()
        flash('Đã chuyển đề đến thư mục mới.', 'success')
    return redirect(url_for('teacher.exams_list', folder_id=exam.folder_id))


def _exam_submitted_attempts(exam):
    return ExamAttempt.query.options(joinedload(ExamAttempt.student)).filter_by(
        exam_id=exam.id, status='submitted'
    ).filter(ExamAttempt.student_id.isnot(None)).order_by(ExamAttempt.started_at.desc()).all()


@teacher_bp.route('/exams/<int:exam_id>/statistics')
@login_required
@require_teacher
def exams_statistics(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)
    attempts = _exam_submitted_attempts(exam)
    submitted_student_ids = {attempt.student_id for attempt in attempts}
    accessible_class_ids = [cls.id for cls in _teacher_accessible_classes()]
    _schools, target_students = exam_assignment_options(accessible_class_ids)
    student_class_ids = {}
    if target_students and accessible_class_ids:
        for class_id, student_id in db.session.query(
            Enrollment.class_id, Enrollment.student_id
        ).filter(
            Enrollment.class_id.in_(accessible_class_ids),
            Enrollment.student_id.in_([student.id for student in target_students]),
            Enrollment.is_active.is_(True),
        ).all():
            student_class_ids.setdefault(student_id, set()).add(class_id)
    assigned_student_ids = {
        student.id for student in target_students
        if exam_is_assigned_to_student(
            exam, student, active_class_ids=student_class_ids.get(student.id, set()),
            teacher_class_ids=accessible_class_ids,
        )
    }
    graded_scores = [
        attempt.result.get('score_10', 0)
        for attempt in attempts if not attempt.result.get('pending_essay_count', 0)
    ]
    metrics = {
        'submitted_attempts': len(attempts),
        'submitted_students': len(submitted_student_ids),
        'assigned_students': len(assigned_student_ids),
        'in_progress': ExamAttempt.query.filter_by(exam_id=exam.id, status='in_progress').count(),
        'pending_essay_questions': sum(
            attempt.result.get('pending_essay_count', 0) for attempt in attempts
        ),
        'average_score': round(sum(graded_scores) / len(graded_scores), 1) if graded_scores else None,
        'flagged_students': len({attempt.student_id for attempt in attempts if attempt.was_flagged}),
    }
    return render_template('teacher/exam_insights.html', exam=exam, metrics=metrics, rows=[],
                           leaderboard=False)


@teacher_bp.route('/exams/<int:exam_id>/leaderboard')
@login_required
@require_teacher
def exams_leaderboard(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)
    best_by_student = {}
    for attempt in _exam_submitted_attempts(exam):
        result = attempt.result
        if result.get('pending_essay_count', 0) or not attempt.student:
            continue
        duration = (
            (attempt.submitted_at - attempt.started_at).total_seconds()
            if attempt.submitted_at and attempt.started_at else float('inf')
        )
        candidate = {
            'student': attempt.student,
            'attempt': attempt,
            'score': result.get('score_10', 0),
            'duration': duration if duration != float('inf') else None,
        }
        previous = best_by_student.get(attempt.student_id)
        candidate_duration = candidate['duration'] if candidate['duration'] is not None else float('inf')
        previous_duration = previous['duration'] if previous and previous['duration'] is not None else float('inf')
        if not previous or (-candidate['score'], candidate_duration) < (
            -previous['score'], previous_duration
        ):
            best_by_student[attempt.student_id] = candidate
    rows = sorted(
        best_by_student.values(),
        key=lambda row: (
            -row['score'],
            row['duration'] if row['duration'] is not None else float('inf'),
            row['student'].full_name.casefold(),
        ),
    )
    return render_template('teacher/exam_insights.html', exam=exam, metrics=None, rows=rows,
                           leaderboard=True)


@teacher_bp.route('/exams/<int:exam_id>/attempts/<int:attempt_id>')
@login_required
@require_teacher
def exams_attempt_detail(exam_id, attempt_id):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)
    attempt = ExamAttempt.query.options(joinedload(ExamAttempt.student)).filter_by(
        id=attempt_id, exam_id=exam.id, status='submitted'
    ).first_or_404()
    if regrade_attempt_if_stale(exam, attempt):
        db.session.add(ExamLog(
            user_id=current_user.id,
            action='regrade_attempt',
            target_type='exam',
            target_id=exam.id,
            detail=f'Tính lại điểm lượt làm #{attempt.id} theo đáp án hiện tại',
        ))
        db.session.commit()
        flash('Điểm bài làm đã được cập nhật theo đáp án hiện tại.', 'info')
    result = attempt.result
    essay_scores = result.get('essay_scores', {})
    essay_max = {item['key']: item['weight'] for item in result.get('essay_questions', [])}
    groups = review_attempt_answers(exam, attempt)
    for group in groups:
        for question in group['questions']:
            key = question.get('key')
            if key:
                question['essay_score'] = essay_scores.get(key)
                question['essay_max'] = essay_max.get(key)
    duration = (
        int((attempt.submitted_at - attempt.started_at).total_seconds())
        if attempt.submitted_at and attempt.started_at else None
    )
    total = result.get('total') or 0
    scoring_labels = {
        'question': 'Mỗi câu 1 điểm',
        'section': 'Điểm chia đều theo phần',
        'question_custom': 'Điểm tùy chỉnh theo từng câu',
        'section_custom': 'Điểm tùy chỉnh theo từng phần',
    }
    sections = [
        {**part, 'scaled_earned': round(part.get('earned', 0) / total * 10, 2) if total else 0,
         'scaled_max': round(part.get('total', 0) / total * 10, 2) if total else 0}
        for part in result.get('breakdown', [])
    ]
    return render_template('teacher/exam_attempt_detail.html', exam=exam, attempt=attempt,
                           result=result, groups=groups, sections=sections, duration=duration,
                           scoring_label=scoring_labels.get(exam.scoring_mode or 'question'))


@teacher_bp.route(
    '/exams/<int:exam_id>/attempts/<int:attempt_id>/questions/<int:group_index>/<int:question_index>',
    methods=['POST'],
)
@login_required
@require_teacher
def exams_attempt_question_edit(exam_id, attempt_id, group_index, question_index):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)
    attempt = ExamAttempt.query.filter_by(
        id=attempt_id, exam_id=exam.id, status='submitted'
    ).first_or_404()
    groups = exam.question_groups
    if group_index >= len(groups) or question_index >= len(groups[group_index].get('questions', [])):
        abort(404)

    group = groups[group_index]
    group_type = group.get('type')
    question = group.get('questions', [])[question_index]
    parsed, error = edited_question_from_form(group_type, question, request.form)
    order_groups = attempt.order_data.get('groups') or []
    question_order = order_groups[group_index].get('q_order', []) if group_index < len(order_groups) else []
    display_position = question_order.index(question_index) + 1 if question_index in question_order else question_index + 1
    question_anchor = f'#attempt-question-g{group_index}-q{display_position}'
    if error:
        flash(error, 'danger')
        return redirect(url_for(
            'teacher.exams_attempt_detail', exam_id=exam.id,
            attempt_id=attempt.id,
        ) + question_anchor)

    if parsed == question:
        flash('Câu hỏi chưa có thay đổi nào.', 'info')
    else:
        groups[group_index]['questions'][question_index] = parsed
        exam.questions_json = json.dumps({'groups': groups}, ensure_ascii=False)
        regraded, skipped = regrade_submitted_attempts(exam)
        detail = (
            f'Cập nhật câu {display_position} của đề "{exam.title}" '
            f'(đã tính lại điểm {regraded} bài đã nộp'
        )
        if skipped:
            detail += f', bỏ qua {skipped} bài do cấu trúc đề đã thay đổi'
        detail += ')'
        db.session.add(ExamLog(
            user_id=current_user.id,
            action='update_exam_question',
            target_type='exam',
            target_id=exam.id,
            detail=detail,
        ))
        db.session.commit()
        flash(
            f'Đã lưu câu hỏi và tính lại điểm {regraded} bài phù hợp'
            f'{f"; bỏ qua {skipped} bài do cấu trúc đề đã thay đổi" if skipped else ""}.',
            'success',
        )

    return redirect(url_for(
        'teacher.exams_attempt_detail', exam_id=exam.id,
        attempt_id=attempt.id,
    ) + question_anchor)


@teacher_bp.route('/exams/<int:exam_id>/attempts/<int:attempt_id>/essay-scores', methods=['POST'])
@login_required
@require_teacher
def exams_attempt_essay_scores(exam_id, attempt_id):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)
    attempt = ExamAttempt.query.filter_by(
        id=attempt_id, exam_id=exam.id, status='submitted'
    ).first_or_404()
    result = attempt.result
    updated_scores = dict(result.get('essay_scores', {}))
    errors = []
    for item in result.get('essay_questions', []):
        raw_score = request.form.get(f"score_{item['key']}", '').strip().replace(',', '.')
        if not raw_score:
            continue
        try:
            score = float(raw_score)
        except ValueError:
            errors.append(f"Câu {item['position']}: điểm phải là một số.")
            continue
        max_score = round(item['weight'], 4)
        if not 0 <= score <= max_score + 1e-6:
            errors.append(f"Câu {item['position']}: điểm phải từ 0 đến {max_score:g}.")
            continue
        updated_scores[item['key']] = round(min(score, max_score), 4)
    if errors:
        for error in errors:
            flash(error, 'danger')
    else:
        result = apply_manual_essay_scores(result, updated_scores)
        attempt.result_json = json.dumps(result)
        attempt.score = result['percent'] if result['pending_essay_count'] == 0 else 0
        db.session.add(ExamLog(
            user_id=current_user.id, action='grade_essay', target_type='exam_attempt',
            target_id=attempt.id, detail=f'Chấm tự luận bài #{attempt.id} của đề "{exam.title}"',
        ))
        db.session.commit()
        flash('Đã lưu điểm tự luận.' if result['pending_essay_count'] == 0
              else 'Đã lưu phần đã chấm; bài vẫn còn câu tự luận chờ chấm.', 'success')
    return redirect(url_for('teacher.exams_attempt_detail', exam_id=exam.id, attempt_id=attempt.id) + '#pane-essay')


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
    folder_id = request.args.get('folder_id', type=int)
    if folder_id:
        ExamFolder.query.filter_by(id=folder_id, created_by=current_user.id).first_or_404()
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        groups = parse_groups_payload(request.form.get('groups_json', '{}'))

        if not title or not groups:
            flash('Vui lòng nhập tên đề thi và ít nhất 1 câu hỏi hợp lệ trong các phần thi.', 'danger')
            return render_template('teacher/exams_form.html', prefill={'title': title, 'groups': groups})

        return _render_exam_confirm({'title': title, 'groups': groups, 'folder_id': folder_id})

    if request.args.get('mode') != 'compose':
        has_reusable_exams = Exam.query.filter(db.or_(
            Exam.created_by == current_user.id,
            db.and_(Exam.is_shared_with_teachers.is_(True), Exam.is_draft.is_(False)),
        )).first() is not None
        return render_template(
            'teacher/exams_create.html', has_existing_exams=has_reusable_exams,
            folder_id=folder_id,
        )

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
        return_attempt_id = request.args.get('return_attempt_id', type=int)

        if not title or not groups:
            flash('Vui lòng nhập tên đề thi và ít nhất 1 câu hỏi hợp lệ trong các phần thi.', 'danger')
            return render_template('teacher/exams_form.html', prefill={'title': title, 'groups': groups},
                                   editing=True, exam=exam, return_attempt_id=return_attempt_id)

        def shape(group_list):
            return [len(g.get('questions', [])) for g in group_list]

        if request.form.get('quick_save'):
            if shape(groups) == shape(exam.question_groups):
                questions_changed = exam.question_groups != groups
                exam.title = title
                exam.questions_json = json.dumps({'groups': groups})
                regraded = skipped = 0
                if questions_changed and exam.attempts.filter_by(status='submitted').count():
                    regraded, skipped = regrade_submitted_attempts(exam)
                detail = f'Cập nhật nội dung đề "{exam.title}"'
                if questions_changed and (regraded or skipped):
                    detail += f' (đã tính lại điểm {regraded} bài đã nộp'
                    detail += f', bỏ qua {skipped} bài do cấu trúc đề đã thay đổi)' if skipped else ')'
                db.session.add(ExamLog(user_id=current_user.id, action='update_exam', target_type='exam',
                                       target_id=exam.id, detail=detail))
                db.session.commit()
                session.pop(SESSION_KEY, None)
                if questions_changed and (regraded or skipped):
                    flash(
                        f'Đã lưu đề và tính lại điểm {regraded} lượt làm phù hợp'
                        f'{f"; bỏ qua {skipped} lượt do cấu trúc đề đã thay đổi" if skipped else ""}.',
                        'success',
                    )
                else:
                    flash('Đã lưu thông tin đề thi.', 'success')
                if return_attempt_id:
                    return redirect(url_for(
                        'teacher.exams_attempt_detail', exam_id=exam.id,
                        attempt_id=return_attempt_id,
                    ))
                return redirect(url_for('teacher.exams_list'))
            flash('Số phần hoặc số câu đã thay đổi, hãy kiểm tra lại cách chia điểm rồi lưu.', 'info')

        return _render_exam_confirm(
            {'title': title, 'groups': groups, 'edit_exam_id': exam.id}, existing=exam,
            return_attempt_id=return_attempt_id,
        )

    draft = session_draft()
    if not draft or draft.get('edit_exam_id') != exam.id:
        draft = {'title': exam.title, 'groups': exam.question_groups}
    return render_template(
        'teacher/exams_form.html', prefill=draft, editing=True, exam=exam,
        return_attempt_id=request.args.get('return_attempt_id', type=int),
    )


def _render_exam_confirm(draft, existing=None, form=None, return_attempt_id=None):
    classes = _teacher_accessible_classes()
    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()
    schools, students = exam_assignment_options([cls.id for cls in classes])
    folders = ExamFolder.query.filter_by(created_by=current_user.id).order_by(ExamFolder.name).all()
    return render_template(
        'teacher/exams_confirm.html', payload=draft, classes=classes, courses=courses,
        schools=schools, students=students,
        folders=folders, exam_types=EXAM_TYPES, durations=DURATION_OPTIONS, form=form,
        editing=bool(existing), existing=existing, return_attempt_id=return_attempt_id,
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
        return_attempt_id = request.form.get('return_attempt_id', type=int)
        settings, error = parse_confirm_settings(request.form, draft['groups'])
        if error:
            flash(error, 'danger')
            return _render_exam_confirm(
                draft, existing=existing, form=request.form,
                return_attempt_id=return_attempt_id,
            )
        _validate_teacher_class_ids(settings['class_ids'])
        _validate_teacher_assignment_targets(settings['school_ids'], settings['student_ids'])
        if settings['folder_id']:
            folder = ExamFolder.query.get(settings['folder_id'])
            if not folder or folder.created_by != current_user.id:
                abort(403)
            if not _folder_matches_assignment(
                folder, settings['subject'], [int(class_id) for class_id in settings['class_ids']]
            ):
                flash('Thư mục phải cùng môn học hoặc thuộc một trong các lớp được giao.', 'warning')
                return _render_exam_confirm(
                    draft, existing=existing, form=request.form,
                    return_attempt_id=return_attempt_id,
                )

        if existing:
            was_published = not existing.is_draft
            from services.exam_push_notifications import (
                exam_assignment_user_ids, notify_exam_assignment,
            )
            previous_recipients = exam_assignment_user_ids(existing) if was_published else set()
            had_attempts = existing.attempts.count() > 0
            questions_changed = existing.question_groups != draft['groups']
            scoring_changed = (existing.scoring_mode, existing.scoring_config_json) != (
                settings['scoring_mode'], json.dumps(settings['scoring_config'])
            ) or (had_attempts and has_stale_scoring(existing, settings['scoring_mode']))
            existing.title = draft['title']
            existing.subject = settings['subject']
            existing.content_grade = settings['content_grade']
            existing.exam_type = settings['exam_type']
            existing.scoring_mode = settings['scoring_mode']
            existing.scoring_config_json = json.dumps(settings['scoring_config'])
            existing.description = settings['description']
            existing.class_ids = ','.join(settings['class_ids'])
            existing.school_ids = ','.join(map(str, settings['school_ids']))
            existing.student_ids = ','.join(map(str, settings['student_ids']))
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
                should_regrade = scoring_changed or questions_changed
                regraded, skipped = regrade_submitted_attempts(existing) if should_regrade else (0, 0)
                if should_regrade:
                    detail += f' (đã tính lại điểm {regraded} bài đã nộp sau khi cập nhật đề'
                    detail += f', bỏ qua {skipped} bài do cấu trúc đề đã thay đổi)' if skipped else ')'
                else:
                    detail += ' (đề đã có học sinh làm bài — kết quả cũ được giữ nguyên)'
            db.session.add(ExamLog(user_id=current_user.id, action='update_exam', target_type='exam',
                                   target_id=existing.id, detail=detail))
            db.session.commit()
            if not existing.is_draft:
                notify_exam_assignment(
                    existing,
                    exclude_user_ids=previous_recipients if was_published else None,
                )
            session.pop(SESSION_KEY, None)
            flash('Đã lưu thay đổi đề thi.', 'success')
        else:
            exam = Exam(
                title=draft['title'],
                subject=settings['subject'],
                content_grade=settings['content_grade'],
                exam_type=settings['exam_type'],
                scoring_mode=settings['scoring_mode'],
                scoring_config_json=json.dumps(settings['scoring_config']),
                description=settings['description'],
                class_ids=','.join(settings['class_ids']),
                school_ids=','.join(map(str, settings['school_ids'])),
                student_ids=','.join(map(str, settings['student_ids'])),
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
            if not exam.is_draft:
                from services.exam_push_notifications import notify_exam_assignment

                notify_exam_assignment(exam)
            session.pop(SESSION_KEY, None)
            flash('Đã tạo đề thi thành công.', 'success')

        if existing and return_attempt_id:
            return redirect(url_for(
                'teacher.exams_attempt_detail', exam_id=existing.id,
                attempt_id=return_attempt_id,
            ))
        return redirect(url_for(
            'teacher.exams_list', folder_id=existing.folder_id if existing else exam.folder_id,
        ))

    return _render_exam_confirm(draft, existing=existing)


@teacher_bp.route('/exams/<int:exam_id>/delete', methods=['POST'])
@login_required
@require_teacher
def exams_delete(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)
    folder_id = exam.folder_id
    if exam.attempts.count():
        flash('Không thể xóa đề đã có lịch sử làm bài. Hãy hủy xuất bản để ẩn đề và giữ kết quả.', 'warning')
        return redirect(url_for('teacher.exams_list', folder_id=folder_id))
    db.session.delete(exam)
    db.session.add(ExamLog(user_id=current_user.id, action='delete_exam', target_type='exam', target_id=exam.id,
                           detail=f'Xóa đề "{exam.title}"'))
    db.session.commit()
    flash('Đã xóa đề thi.', 'success')
    return redirect(url_for('teacher.exams_list', folder_id=folder_id))


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
