"""Shared object-level authorization for class-document download routes."""
from flask import abort
from flask_login import current_user

from services.auth_context import get_active_role


def require_document_access(document):
    if not current_user.is_active or current_user.is_deleted:
        abort(403)
    if not document.is_active:
        abort(404)
    role = get_active_role(current_user)
    if role == 'admin' and current_user.is_admin:
        if not current_user.can_access('documents'):
            abort(403)
        return
    if role == 'teacher' and (current_user.is_teacher or current_user.is_teacher_linked):
        from blueprints.teacher import _teacher_can_access_class
        if not current_user.can_access('documents_teacher') or not _teacher_can_access_class(
            current_user.teacher_profile, document.class_,
        ):
            abort(403)
        return
    if role == 'student' and current_user.is_student:
        student = current_user.student_profile
        if (
            student and student.is_active and not student.is_deleted
            and document.class_.is_student_enrolled(student.id)
        ):
            return
    elif role == 'parent' and current_user.is_parent:
        children = current_user.children.filter_by(is_active=True, is_deleted=False).all()
        if any(document.class_.is_student_enrolled(child.id) for child in children):
            return
    abort(403)
