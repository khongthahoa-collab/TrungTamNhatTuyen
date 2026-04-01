"""
Zalo Notification Service
Phase 1: Mock mode — logs to ZaloLog table, không gửi thật.
Phase 2: Kết nối Zalo OA API / ZNS.
"""
from datetime import datetime
from extensions import db
from models import ZaloLog


class ZaloService:

    @staticmethod
    def _log(phone, name, msg_type, summary, status='mock', error=None):
        log = ZaloLog(
            recipient_phone=phone,
            recipient_name=name,
            message_type=msg_type,
            content_summary=summary,
            sent_at=datetime.utcnow(),
            status=status,
            error_msg=error,
        )
        db.session.add(log)
        db.session.commit()
        return log

    @classmethod
    def send_absence_notification(cls, student, schedule, status, note=''):
        """Gửi thông báo vắng học cho phụ huynh."""
        status_vn = {'absent': 'Vắng', 'late': 'Trễ'}.get(status, status)
        msg = (
            f"[Nhật Tuyền] Học sinh {student.full_name} "
            f"{'đi trễ' if status == 'late' else 'vắng học'} buổi học "
            f"{schedule.class_.name} ngày {schedule.date.strftime('%d/%m/%Y')} "
            f"{schedule.start_time.strftime('%H:%M')}"
        )
        if note:
            msg += f". Ghi chú: {note}"
        phone = student.parent_phone or ''
        name = student.parent_name or ''
        return cls._log(phone, name, 'attendance', msg)

    @classmethod
    def send_tuition_reminder(cls, student, class_, month, year, amount, bank_info=''):
        """Nhắc học phí."""
        msg = (
            f"[Nhật Tuyền] Nhắc đóng học phí: {student.full_name} - {class_.name} "
            f"tháng {month}/{year}. Số tiền: {int(amount):,}đ. {bank_info}"
        )
        phone = student.parent_phone or ''
        name = student.parent_name or ''
        return cls._log(phone, name, 'tuition', msg)

    @classmethod
    def send_intensive_schedule(cls, student, schedule):
        """Thông báo lịch tăng cường."""
        msg = (
            f"[Nhật Tuyền] Lịch tăng cường: {schedule.class_.name} "
            f"ngày {schedule.date.strftime('%d/%m/%Y')} "
            f"{schedule.start_time.strftime('%H:%M')}-{schedule.end_time.strftime('%H:%M')} "
            f"phòng {schedule.room or 'TBA'}"
        )
        phone = student.parent_phone or ''
        name = student.parent_name or ''
        return cls._log(phone, name, 'intensive_schedule', msg)

    @classmethod
    def send_cancel_notification(cls, student, schedule):
        """Thông báo hủy lịch."""
        msg = (
            f"[Nhật Tuyền] THÔNG BÁO: Buổi học {schedule.class_.name} "
            f"ngày {schedule.date.strftime('%d/%m/%Y')} bị HỦY. "
            f"Lý do: {schedule.cancel_reason or 'Có việc đột xuất'}."
        )
        phone = student.parent_phone or ''
        name = student.parent_name or ''
        return cls._log(phone, name, 'cancel', msg)

    @classmethod
    def send_score_notification(cls, student, score, reward=None):
        """Thông báo điểm số và thưởng."""
        msg = (
            f"[Nhật Tuyền] Điểm {score.score_type_label}: {student.full_name} - "
            f"{score.class_.course.name} đạt {score.score_value}/{score.max_score}"
        )
        if reward and reward.amount > 0:
            msg += f". Thưởng: {int(reward.amount):,}đ"
        phone = student.parent_phone or ''
        name = student.parent_name or ''
        return cls._log(phone, name, 'score', msg)

    @classmethod
    def send_bulk(cls, message, phones_names):
        """Gửi thông báo hàng loạt."""
        logs = []
        for phone, name in phones_names:
            log = cls._log(phone, name, 'general', message)
            logs.append(log)
        return logs
