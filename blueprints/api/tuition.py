from datetime import date, datetime
from flask import request, g
from extensions import db
from models import TuitionPayment, Class
from blueprints.api import (api_bp, api_ok, api_error, api_login_required, api_require_module,
                            get_page_args, pagination_meta, get_body, body_int)
from services.tuition_service import create_tuition_payment, record_payment


@api_bp.route('/tuition/overview', methods=['GET'])
@api_login_required
@api_require_module('tuition')
def tuition_overview():
    """KPI totals + per-class paid/unpaid summary for a month, reusing the
    exact same SQL aggregation the /admin/tuition web page uses (see
    blueprints/admin/finance.py::_tuition_overview_aggregate) so the two
    can't drift."""
    from blueprints.admin.finance import _tuition_overview_aggregate
    today = date.today()
    month = request.args.get('month', today.month, type=int)
    year = request.args.get('year', today.year, type=int)
    class_id = request.args.get('class_id', type=int)
    if class_id and not Class.query.get(class_id):
        return api_error('Không tìm thấy lớp học.', 404, code='not_found')

    _, class_summaries, total_collected, total_outstanding, total_expected = \
        _tuition_overview_aggregate(month, year, class_id)

    return api_ok({
        'month': month,
        'year': year,
        'total_expected': total_expected,
        'total_collected': total_collected,
        'total_outstanding': total_outstanding,
        'classes': [{
            'class_id': row['class'].id,
            'class_name': row['class'].name,
            'total_students': row['total'],
            'paid_count': row['paid_count'],
            'unpaid_count': row['unpaid_count'],
            'collected_amount': row['paid_amount'],
            'outstanding_amount': row['unpaid_amount'],
            'carried_debt_amount': row['carried_debt'],
        } for row in class_summaries],
    })


@api_bp.route('/tuition-payments', methods=['GET'])
@api_login_required
@api_require_module('tuition')
def tuition_list():
    student_id = request.args.get('student_id', type=int)
    class_id = request.args.get('class_id', type=int)
    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)
    is_paid = request.args.get('is_paid')

    if class_id and not Class.query.get(class_id):
        return api_error('Không tìm thấy lớp học.', 404, code='not_found')

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

    payment, created = create_tuition_payment(
        student_id, class_id, month, year, float(amount),
        method=body.get('method', 'cash'), note=body.get('note'),
    )
    if not created:
        return api_error('Đã có bản ghi học phí tháng này rồi.', 409, code='duplicate')
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

    # Flipping is_paid is a real money-changing operation — route it
    # through the same race-safe/amount_collected-aware path the web app's
    # tuition_mark_paid uses (services.tuition_service.record_payment),
    # rather than setting the boolean directly here.
    is_paid = body.get('is_paid')
    if is_paid is not None and str(is_paid).lower() in ('1', 'true', 'yes') and not payment.is_paid:
        db.session.commit()
        collected = body.get('amount_collected')
        payment = record_payment(payment_id, float(collected) if collected else None,
                                 payment.method, g.api_user.id)
    else:
        db.session.commit()
    return api_ok(payment.to_dict())
