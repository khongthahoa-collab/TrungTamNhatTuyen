from datetime import date, datetime
from flask import request
from extensions import db
from models import TuitionPayment
from blueprints.api import (api_bp, api_ok, api_error, api_login_required, api_require_module,
                            get_page_args, pagination_meta, get_body, body_int)


@api_bp.route('/tuition-payments', methods=['GET'])
@api_login_required
@api_require_module('tuition')
def tuition_list():
    student_id = request.args.get('student_id', type=int)
    class_id = request.args.get('class_id', type=int)
    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)
    is_paid = request.args.get('is_paid')

    query = TuitionPayment.query
    if student_id:
        query = query.filter_by(student_id=student_id)
    if class_id:
        query = query.filter_by(class_id=class_id)
    if month:
        query = query.filter_by(month=month)
    if year:
        query = query.filter_by(year=year)
    if is_paid is not None:
        query = query.filter_by(is_paid=is_paid in ('1', 'true', 'True'))

    page, per_page = get_page_args()
    pagination = query.order_by(TuitionPayment.year.desc(), TuitionPayment.month.desc()) \
        .paginate(page=page, per_page=per_page, error_out=False)
    return api_ok([t.to_dict() for t in pagination.items], meta=pagination_meta(pagination))


@api_bp.route('/tuition-payments/<int:payment_id>', methods=['GET'])
@api_login_required
@api_require_module('tuition')
def tuition_detail(payment_id):
    payment = TuitionPayment.query.get(payment_id)
    if not payment:
        return api_error('Không tìm thấy bản ghi học phí.', 404, code='not_found')
    return api_ok(payment.to_dict())


@api_bp.route('/tuition-payments', methods=['POST'])
@api_login_required
@api_require_module('tuition', write=True)
def tuition_create():
    body = get_body()
    student_id = body_int(body, 'student_id')
    class_id = body_int(body, 'class_id')
    month = body_int(body, 'month')
    year = body_int(body, 'year')
    amount = body.get('amount')

    if not all([student_id, class_id, month, year]) or amount is None:
        return api_error('student_id, class_id, month, year, amount là bắt buộc.', 400, code='validation_error')

    payment = TuitionPayment(
        student_id=student_id,
        class_id=class_id,
        month=month,
        year=year,
        amount=float(amount),
        method=body.get('method', 'cash'),
        note=body.get('note'),
        is_paid=False,
    )
    db.session.add(payment)
    db.session.commit()
    return api_ok(payment.to_dict(), status=201)


@api_bp.route('/tuition-payments/<int:payment_id>', methods=['PUT'])
@api_login_required
@api_require_module('tuition', write=True)
def tuition_update(payment_id):
    payment = TuitionPayment.query.get(payment_id)
    if not payment:
        return api_error('Không tìm thấy bản ghi học phí.', 404, code='not_found')

    body = get_body()
    if 'amount' in body:
        payment.amount = float(body.get('amount'))
    if 'note' in body:
        payment.note = body.get('note')
    if 'method' in body:
        payment.method = body.get('method')
    is_paid = body.get('is_paid')
    if is_paid is not None:
        was_paid = payment.is_paid
        payment.is_paid = str(is_paid).lower() in ('1', 'true', 'yes')
        if payment.is_paid and not was_paid:
            payment.paid_at = datetime.utcnow()

    db.session.commit()
    return api_ok(payment.to_dict())
