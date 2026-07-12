from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required
from extensions import db
from models import Room, Schedule
from blueprints.admin import admin_bp, require_admin
from datetime import date, time as time_type


@admin_bp.route('/rooms')
@login_required
@require_admin
def rooms():
    rooms = Room.query.order_by(Room.branch, Room.floor, Room.room_number).all()
    return render_template('admin/rooms/list.html', rooms=rooms)


@admin_bp.route('/rooms/add', methods=['GET', 'POST'])
@login_required
@require_admin
def room_add():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        branch = request.form.get('branch', '').strip()
        floor = request.form.get('floor', '').strip()
        room_number = request.form.get('room_number', '').strip()
        capacity = request.form.get('capacity', 20, type=int)

        if not name:
            flash('Vui lòng nhập tên phòng.', 'danger')
            return render_template('admin/rooms/form.html', action='add', form=request.form)

        room = Room(
            name=name,
            branch=branch,
            floor=floor,
            room_number=room_number,
            capacity=capacity,
        )
        db.session.add(room)
        db.session.commit()
        flash(f'Đã thêm phòng học {name}.', 'success')
        return redirect(url_for('admin.rooms'))

    return render_template('admin/rooms/form.html', action='add', form={})


@admin_bp.route('/rooms/<int:room_id>/edit', methods=['GET', 'POST'])
@login_required
@require_admin
def room_edit(room_id):
    room = Room.query.get_or_404(room_id)

    if request.method == 'POST':
        room.name = request.form.get('name', '').strip() or room.name
        room.branch = request.form.get('branch', '').strip()
        room.floor = request.form.get('floor', '').strip()
        room.room_number = request.form.get('room_number', '').strip()
        room.capacity = request.form.get('capacity', room.capacity, type=int)
        room.is_active = request.form.get('is_active') == '1'
        db.session.commit()
        flash('Đã cập nhật thông tin phòng học.', 'success')
        return redirect(url_for('admin.rooms'))

    return render_template('admin/rooms/form.html', action='edit', room=room, form=room)


@admin_bp.route('/rooms/<int:room_id>/delete', methods=['POST'])
@login_required
@require_admin
def room_delete(room_id):
    room = Room.query.get_or_404(room_id)
    # Soft delete
    room.is_active = False
    db.session.commit()
    flash(f'Đã vô hiệu hóa phòng học {room.name}.', 'success')
    return redirect(url_for('admin.rooms'))


@admin_bp.route('/rooms/available')
@login_required
@require_admin
def rooms_available():
    """API: return rooms available for a given date+time slot (JSON)."""
    date_str = request.args.get('date', '')
    start_str = request.args.get('start', '')
    end_str = request.args.get('end', '')
    exclude_id = request.args.get('exclude', type=int)

    if not date_str or not start_str or not end_str:
        return jsonify({'rooms': []})

    try:
        sched_date = date.fromisoformat(date_str)
        start_time = time_type.fromisoformat(start_str)
        end_time = time_type.fromisoformat(end_str)
    except ValueError:
        return jsonify({'rooms': []})

    # Find rooms that have a conflict
    conflict_subq = db.session.query(Schedule.room_id).filter(
        Schedule.room_id.isnot(None),
        Schedule.date == sched_date,
        Schedule.is_cancelled == False,
        Schedule.start_time < end_time,
        Schedule.end_time > start_time,
    )
    if exclude_id:
        conflict_subq = conflict_subq.filter(Schedule.id != exclude_id)
    booked_ids = {r[0] for r in conflict_subq.all()}

    available = Room.query.filter(
        Room.is_active == True,
        Room.id.notin_(booked_ids),
    ).order_by(Room.branch, Room.floor, Room.room_number).all()

    return jsonify({'rooms': [
        {'id': r.id, 'name': r.name, 'display': r.display_name, 'capacity': r.capacity}
        for r in available
    ]})
