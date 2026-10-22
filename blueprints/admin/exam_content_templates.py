from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required

from blueprints.admin import admin_bp, require_admin
from extensions import db
from models import ExamContentTemplate

MAX_CONTENT_LENGTH = 200_000


def _template_fields():
    name = request.form.get('name', '').strip()
    content = request.form.get('content', '')
    errors = {}
    if not name:
        errors['name'] = 'Vui lòng nhập tên mẫu.'
    elif len(name) > 200:
        errors['name'] = 'Tên mẫu không được vượt quá 200 ký tự.'
    if not content.strip():
        errors['content'] = 'Vui lòng nhập nội dung mẫu.'
    elif len(content) > MAX_CONTENT_LENGTH:
        errors['content'] = 'Nội dung mẫu không được vượt quá 200.000 ký tự.'
    return {'name': name, 'content': content}, errors


@admin_bp.get('/exam/content-templates')
@login_required
@require_admin
def exam_content_templates():
    templates = ExamContentTemplate.query.order_by(
        ExamContentTemplate.name, ExamContentTemplate.id
    ).all()
    return render_template('exams/content_templates.html', templates=templates)


@admin_bp.route('/exam/content-templates/new', methods=['GET', 'POST'])
@login_required
@require_admin
def exam_content_template_new():
    fields, errors = {'name': '', 'content': ''}, {}
    if request.method == 'POST':
        fields, errors = _template_fields()
        if not errors:
            db.session.add(ExamContentTemplate(**fields))
            db.session.commit()
            flash('Đã tạo mẫu nội dung dùng chung.', 'success')
            return redirect(url_for('admin.exam_content_templates'))
    return render_template(
        'exams/content_template_form.html', item=None, fields=fields, errors=errors
    ), 400 if errors else 200


@admin_bp.route('/exam/content-templates/<int:template_id>/edit', methods=['GET', 'POST'])
@login_required
@require_admin
def exam_content_template_edit(template_id):
    item = ExamContentTemplate.query.get_or_404(template_id)
    fields, errors = {'name': item.name, 'content': item.content}, {}
    if request.method == 'POST':
        fields, errors = _template_fields()
        if not errors:
            item.name = fields['name']
            item.content = fields['content']
            db.session.commit()
            flash('Đã cập nhật mẫu nội dung dùng chung.', 'success')
            return redirect(url_for('admin.exam_content_templates'))
    return render_template(
        'exams/content_template_form.html', item=item, fields=fields, errors=errors
    ), 400 if errors else 200


@admin_bp.post('/exam/content-templates/<int:template_id>/delete')
@login_required
@require_admin
def exam_content_template_delete(template_id):
    item = ExamContentTemplate.query.get_or_404(template_id)
    db.session.delete(item)
    db.session.commit()
    flash('Đã xóa mẫu nội dung. Các đề thi đã sử dụng mẫu không bị thay đổi.', 'success')
    return redirect(url_for('admin.exam_content_templates'))
