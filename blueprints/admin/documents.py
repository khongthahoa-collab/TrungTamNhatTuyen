import os
import uuid
from flask import render_template, redirect, url_for, flash, request, current_app, send_from_directory
from flask_login import login_required, current_user
from sqlalchemy import func
from extensions import db
from models import ClassDocument, Class, Course, ExamFolder, Exam
from blueprints.admin import admin_bp, require_admin


@admin_bp.route('/documents')
@login_required
@require_admin
def documents():
    class_id = request.args.get('class_id', type=int)
    query = ClassDocument.query.filter_by(is_active=True)
    if class_id:
        query = query.filter_by(class_id=class_id)
    page = request.args.get('page', 1, type=int)
    pagination = query.order_by(ClassDocument.uploaded_at.desc()).paginate(page=page, per_page=10, error_out=False)
    docs = pagination.items
    classes = Class.query.filter_by(is_active=True).order_by(Class.name).all()
    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()
    exam_folders = ExamFolder.query.order_by(ExamFolder.name).all()
    # One grouped count query instead of folder.exams.count() per folder
    # (Exam.folder_id, ExamFolder.exams is lazy='dynamic') in the template.
    exam_counts = dict(
        db.session.query(Exam.folder_id, func.count(Exam.id))
        .filter(Exam.folder_id.in_([f.id for f in exam_folders]))
        .group_by(Exam.folder_id).all()
    ) if exam_folders else {}
    return render_template('admin/documents/list.html',
                           docs=docs, classes=classes, courses=courses,
                           exam_folders=exam_folders, selected_class_id=class_id,
                           is_filtered=bool(class_id), pagination=pagination,
                           exam_counts=exam_counts)


@admin_bp.route('/documents/upload', methods=['POST'])
@login_required
@require_admin
def document_upload():
    class_id = request.form.get('class_id', type=int)
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    file = request.files.get('file')

    if not class_id or not title or not file or file.filename == '':
        flash('Vui lòng chọn lớp, điền tiêu đề và chọn file.', 'danger')
        return redirect(url_for('admin.documents'))

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    allowed = current_app.config.get('ALLOWED_EXTENSIONS', set())
    if ext not in allowed:
        flash(f'Định dạng .{ext} không được hỗ trợ.', 'danger')
        return redirect(url_for('admin.documents'))

    stored_name = f"{uuid.uuid4().hex}.{ext}"
    upload_dir = current_app.config['UPLOAD_FOLDER']
    os.makedirs(upload_dir, exist_ok=True)
    save_path = os.path.join(upload_dir, stored_name)
    file.save(save_path)
    size = os.path.getsize(save_path)

    doc = ClassDocument(
        class_id=class_id,
        uploaded_by=current_user.id,
        title=title,
        description=description,
        original_filename=file.filename,
        stored_filename=stored_name,
        file_size=size,
        file_type=ext,
    )
    db.session.add(doc)
    db.session.commit()
    flash(f'Đã tải lên "{title}".', 'success')
    return redirect(url_for('admin.documents', class_id=class_id))


@admin_bp.route('/documents/<int:doc_id>/delete', methods=['POST'])
@login_required
@require_admin
def document_delete(doc_id):
    doc = ClassDocument.query.get_or_404(doc_id)
    doc.is_active = False
    db.session.commit()
    flash('Đã xóa tài liệu.', 'success')
    return redirect(request.referrer or url_for('admin.documents'))


@admin_bp.route('/documents/<int:doc_id>/download')
@login_required
def document_download(doc_id):
    doc = ClassDocument.query.get_or_404(doc_id)
    if not doc.is_active:
        flash('Tài liệu không còn tồn tại.', 'danger')
        return redirect(url_for('admin.documents'))
    upload_dir = current_app.config['UPLOAD_FOLDER']
    return send_from_directory(upload_dir, doc.stored_filename,
                               as_attachment=True,
                               download_name=doc.original_filename)
