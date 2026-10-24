from datetime import datetime
from app import db

class EssayImage(db.Model):
    __tablename__ = 'essay_images'

    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey('exam_attempts.id', ondelete='CASCADE'), nullable=False, index=True)
    question_id = db.Column(db.Integer, nullable=False, index=True)
    file_path = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)  # bytes
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)