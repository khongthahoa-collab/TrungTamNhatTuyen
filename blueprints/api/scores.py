from datetime import date
from flask import request, g
from extensions import db
from models import Score
from blueprints.api import (api_bp, api_ok, api_error, api_login_required, api_require_module,
                            get_page_args, pagination_meta, get_body, body_int)
from services.reward_service import create_suggested_reward


@api_bp.route('/scores', methods=['GET'])
@api_login_required
@api_require_module('students')  # no dedicated admin "scores" module — gated same as the student record itself
def scores_list():
    student_id = request.args.get('student_id', type=int)
    class_id = request.args.get('class_id', type=int)
    query = Score.query
    if student_id:
        query = query.filter_by(student_id=student_id)
    if class_id:
        query = query.filter_by(class_id=class_id)

    page, per_page = get_page_args()
    pagination = query.order_by(Score.exam_date.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return api_ok([s.to_dict() for s in pagination.items], meta=pagination_meta(pagination))


@api_bp.route('/scores/<int:score_id>', methods=['GET'])
@api_login_required
@api_require_module('students')
def scores_detail(score_id):
    score = Score.query.get(score_id)
    if not score:
        return api_error('Không tìm thấy điểm số.', 404, code='not_found')
    return api_ok(score.to_dict())


@api_bp.route('/scores', methods=['POST'])
@api_login_required
@api_require_module('students', write=True)
def scores_create():
    body = get_body()
    student_id = body_int(body, 'student_id')
    class_id = body_int(body, 'class_id')
    score_type = (body.get('score_type') or '').strip()
    score_value = body.get('score_value')

    if not student_id or not class_id or not score_type or score_value is None:
        return api_error('student_id, class_id, score_type, score_value là bắt buộc.', 400, code='validation_error')

    score = Score(
        student_id=student_id,
        class_id=class_id,
        score_type=score_type,
        score_source=body.get('score_source', 'center'),
        score_value=float(score_value),
        max_score=float(body.get('max_score') or 10.0),
        exam_date=date.fromisoformat(body['exam_date']) if body.get('exam_date') else date.today(),
        school_name=body.get('school_name'),
        note=body.get('note'),
        entered_by=g.api_user.id,
    )
    db.session.add(score)
    db.session.flush()

    reward = create_suggested_reward(score, g.api_user.id)

    db.session.commit()
    data = score.to_dict()
    data['suggested_reward'] = reward.to_dict() if reward else None
    return api_ok(data, status=201)


@api_bp.route('/scores/<int:score_id>', methods=['PUT'])
@api_login_required
@api_require_module('students', write=True)
def scores_update(score_id):
    score = Score.query.get(score_id)
    if not score:
        return api_error('Không tìm thấy điểm số.', 404, code='not_found')

    body = get_body()
    for field in ('score_type', 'score_source', 'school_name', 'note'):
        if field in body:
            setattr(score, field, body.get(field))
    if 'score_value' in body:
        score.score_value = float(body.get('score_value'))
    if 'max_score' in body:
        score.max_score = float(body.get('max_score'))
    if body.get('exam_date'):
        score.exam_date = date.fromisoformat(body['exam_date'])

    db.session.commit()
    return api_ok(score.to_dict())


@api_bp.route('/scores/<int:score_id>', methods=['DELETE'])
@api_login_required
@api_require_module('students', write=True)
def scores_delete(score_id):
    score = Score.query.get(score_id)
    if not score:
        return api_error('Không tìm thấy điểm số.', 404, code='not_found')
    db.session.delete(score)
    db.session.commit()
    return api_ok({'message': 'Đã xoá điểm số.'})
