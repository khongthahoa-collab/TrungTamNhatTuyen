"""Shared grading screen behind role-specific routes and access checks."""
import json

from flask import abort, flash, redirect, render_template, request, url_for

from blueprints.exams_shared import apply_manual_essay_scores, require_owns_or_admin
from extensions import db
from models import Exam, ExamAttempt
from services.essay_images import images_by_answer


def grade_attempt(exam_id, attempt_id, *, role):
    exam = Exam.query.get_or_404(exam_id)
    require_owns_or_admin(exam)
    attempt = ExamAttempt.query.filter_by(id=attempt_id, exam_id=exam.id, status='submitted').first_or_404()
    result = attempt.result
    essay_questions = result.get('essay_questions', [])
    if not essay_questions:
        abort(404)
    answers = attempt.answers
    essay_images = images_by_answer(attempt.id)
    explanations = {
        f'g{gi}_q{qi}': (question.get('explanation') or '').strip()
        for gi, group in enumerate(exam.question_groups)
        if group.get('type') == 'essay'
        for qi, question in enumerate(group.get('questions', []))
    }
    items = [{
        'key': item['key'],
        'title': item.get('group_title', ''),
        'position': item.get('position', 1),
        'text': item.get('question_text', ''),
        'answer': answers.get(item.get('answer_field', ''), ''),
        'explanation': explanations.get(item['key'], ''),
        'images': essay_images.get(item.get('answer_field', ''), []),
        'max_score': round(item['weight'], 4),
        'score': result.get('essay_scores', {}).get(item['key'], ''),
    } for item in essay_questions]
    results_url = url_for(f'{role}.exams_results', exam_id=exam.id)
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
                errors.append(f"Câu {item['position']}: điểm phải từ 0 đến {item['max_score']:g}.")
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
            flash('Đã lưu điểm tự luận.' if result['pending_essay_count'] == 0
                  else 'Đã lưu phần đã chấm; bài vẫn còn câu tự luận chờ chấm.', 'success')
            return redirect(results_url)
    return render_template('exams/grade_attempt.html', exam=exam, attempt=attempt,
                           items=items, result=result, base_template=f'{role}/base.html',
                           results_url=results_url)
