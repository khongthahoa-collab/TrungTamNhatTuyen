from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from datetime import date, datetime
from extensions import db
from models import Reward, Student
from blueprints.admin import admin_bp, require_admin


@admin_bp.route('/khen-thuong')
@login_required
@require_admin
def rewards():
    show = request.args.get('show', 'pending')  # pending / confirmed / all

    query = Reward.query
    if show == 'pending':
        query = query.filter_by(is_suggested=True, is_confirmed=False)
    elif show == 'confirmed':
        query = query.filter_by(is_confirmed=True)

    records = query.order_by(Reward.reward_date.desc()).all()
    total_confirmed = sum(r.amount for r in Reward.query.filter_by(is_confirmed=True).all())

    return render_template('admin/rewards/list.html',
                           records=records, show=show, total_confirmed=total_confirmed)


@admin_bp.route('/khen-thuong/<int:reward_id>/xac-nhan', methods=['POST'])
@login_required
@require_admin
def reward_confirm(reward_id):
    reward = Reward.query.get_or_404(reward_id)
    reward.is_confirmed = True
    reward.confirmed_by = current_user.id
    reward.confirmed_at = datetime.utcnow()

    # Override amount if admin adjusted
    new_amount = request.form.get('amount', type=float)
    if new_amount is not None:
        reward.amount = new_amount

    db.session.commit()

    # Notify parent via Zalo
    if reward.score_id:
        from services.zalo_service import ZaloService
        score = reward.score
        ZaloService.send_score_notification(reward.student, score, reward)

    flash(f'Đã xác nhận thưởng cho {reward.student.full_name}.', 'success')
    return redirect(url_for('admin.rewards', show='pending'))


@admin_bp.route('/khen-thuong/<int:reward_id>/huy', methods=['POST'])
@login_required
@require_admin
def reward_cancel(reward_id):
    reward = Reward.query.get_or_404(reward_id)
    db.session.delete(reward)
    db.session.commit()
    flash('Đã hủy đề xuất thưởng.', 'success')
    return redirect(url_for('admin.rewards', show='pending'))


@admin_bp.route('/khen-thuong/them', methods=['POST'])
@login_required
@require_admin
def reward_add():
    """Admin thêm thưởng thủ công (dịp lễ, tết, đặc biệt)."""
    student_id = request.form.get('student_id', type=int)
    reason = request.form.get('reason', '').strip()
    amount = request.form.get('amount', 0, type=float)
    reward_type = request.form.get('reward_type', 'cash')
    date_str = request.form.get('reward_date', '')
    note = request.form.get('note', '').strip()

    if not student_id or not reason:
        flash('Vui lòng chọn học sinh và nhập lý do.', 'danger')
        return redirect(url_for('admin.rewards'))

    today = date.today()
    try:
        reward_date = date.fromisoformat(date_str) if date_str else today
    except ValueError:
        reward_date = today

    reward = Reward(
        student_id=student_id,
        reason=reason,
        amount=amount,
        reward_type=reward_type,
        reward_date=reward_date,
        note=note,
        is_suggested=False,
        is_confirmed=True,
        created_by=current_user.id,
        confirmed_by=current_user.id,
        confirmed_at=datetime.utcnow(),
    )
    db.session.add(reward)
    db.session.commit()
    flash(f'Đã ghi nhận thưởng cho {reward.student.full_name}.', 'success')
    return redirect(url_for('admin.rewards', show='confirmed'))
