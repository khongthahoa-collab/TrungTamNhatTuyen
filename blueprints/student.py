from flask import Blueprint, abort, redirect, url_for
from flask_login import current_user, login_required

from models import Exam
from blueprints import parent

student_bp = Blueprint('student', __name__)


def _current_student():
    if (not current_user.is_authenticated or not current_user.is_active
            or not current_user.is_student):
        abort(403)
    student = current_user.student_profile
    if not student or not student.is_active or student.is_deleted:
        abort(403)
    return student


def _assigned_exam_or_404(exam_id):
    student = _current_student()
    exam = Exam.query.get_or_404(exam_id)
    if exam not in parent._exams_for_student(student):
        abort(404)
    return student, exam


@student_bp.route('/exams')
@login_required
def exams_list():
    student = _current_student()
    return parent.exams(student.id)


@student_bp.route('/exams/<int:exam_id>')
@login_required
def exam_take(exam_id):
    student, _exam = _assigned_exam_or_404(exam_id)
    return parent.exam_take(student.id, exam_id)


@student_bp.route('/exams/<int:exam_id>/submit', methods=['POST'])
@login_required
def exam_submit(exam_id):
    student, _exam = _assigned_exam_or_404(exam_id)
    return parent.exam_submit(student.id, exam_id)


@student_bp.route('/exams/<int:exam_id>/save', methods=['POST'])
@login_required
def exam_save_progress(exam_id):
    student, _exam = _assigned_exam_or_404(exam_id)
    return parent.exam_save_progress(student.id, exam_id)


@student_bp.route('/exams/<int:exam_id>/result')
@login_required
def exam_result(exam_id):
    student, _exam = _assigned_exam_or_404(exam_id)
    return parent.exam_result(student.id, exam_id)
