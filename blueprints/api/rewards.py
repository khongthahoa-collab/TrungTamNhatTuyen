from datetime import date, datetime
from flask import request, g
from extensions import db
from models import Reward
from blueprints.api import (api_bp, api_ok, api_error, api_login_required, api_require_module,
                            get_page_args, pagination_meta, get_body, body_int)


@api_bp.route('/rewards', methods=['GET'])
@api_login_required
@api_require_module('rewards')
def rewards_list():
    student_id = request.args.get('student_id', type=int)
    show = request.args.get('show', '')  # pending / confirmed / all

    query = Reward.query
    if student_id:
        query = query.filter_by(student_id=student_id)
    if show == 'pending':
        query = query.filter_by(is_suggested=True, is_confirmed=False)
    elif show == 'confirmed':
        query = query.filter_by(is_confirmed=True)

    page, per_page = get_page_args()
    pagination = query.order_by(Reward.reward_date.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return api_ok([r.to_dict() for r in pagination.items], meta=pagination_meta(pagination))


@api_bp.route('/rewards/<int:reward_id>', methods=['GET'])
@api_login_required
@api_require_module('rewards')
def rewards_detail(reward_id):
    reward = Reward.query.get(reward_id)
    if not reward:
        return api_error('Không tìm thấy khen thưởng.', 404, code='not_found')
    return api_ok(reward.to_dict())


@api_bp.route('/rewards', methods=['POST'])
@api_login_required
@api_require_module('rewards', write=True)
def rewards_create():
    body = get_body()
    student_id = body_int(body, 'student_id')
    reason = (body.get('reason') or '').strip()
    if not student_id or not reason:
        return api_error('student_id và reason là bắt buộc.', 400, code='validation_error')

    reward = Reward(
        student_id=student_id,
        reason=reason,
        amount=float(body.get('amount') or 0),
        reward_type=body.get('reward_type', 'cash'),
        reward_date=date.fromisoformat(body['reward_date']) if body.get('reward_date') else date.today(),
        note=body.get('note'),
        is_suggested=False,
        is_confirmed=False,
        created_by=g.api_user.id,
    )
    db.session.add(reward)
    db.session.commit()
    return api_ok(reward.to_dict(), status=201)


@api_bp.route('/rewards/<int:reward_id>/confirm', methods=['POST'])
@api_login_required
@api_require_module('rewards', write=True)
def rewards_confirm(reward_id):
    reward = Reward.query.get(reward_id)
    if not reward:
        return api_error('Không tìm thấy khen thưởng.', 404, code='not_found')

    body = get_body()
    reward.is_confirmed = True
    reward.confirmed_by = g.api_user.id
    reward.confirmed_at = datetime.utcnow()
    if body.get('amount') is not None:
        reward.amount = float(body.get('amount'))

    db.session.commit()
    return api_ok(reward.to_dict())


@api_bp.route('/rewards/<int:reward_id>/cancel', methods=['POST'])
@api_login_required
@api_require_module('rewards', write=True)
def rewards_cancel(reward_id):
    reward = Reward.query.get(reward_id)
    if not reward:
        return api_error('Không tìm thấy khen thưởng.', 404, code='not_found')
    db.session.delete(reward)
    db.session.commit()
    return api_ok({'message': 'Đã hủy đề xuất thưởng.'})
