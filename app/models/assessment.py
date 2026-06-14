from datetime import datetime

from app.extensions import db


class Assessment(db.Model):
    __tablename__ = "assessments"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    assessment_type = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    audio_path_prepared = db.Column(db.String(500), nullable=True)
    audio_path_spontaneous = db.Column(db.String(500), nullable=True)

    transcript_prepared = db.Column(db.Text, nullable=True)
    transcript_spontaneous = db.Column(db.Text, nullable=True)

    duration_prepared = db.Column(db.Integer, nullable=True)
    duration_spontaneous = db.Column(db.Integer, nullable=True)

    topic_vector_prepared = db.Column(db.Text, nullable=True)
    topic_vector_spontaneous = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(20), nullable=False, default="pending")
    error_message = db.Column(db.Text, nullable=True)
    celery_task_id = db.Column(db.String(100), nullable=True)

    user = db.relationship("User", backref=db.backref("assessments", lazy="dynamic"))

    @property
    def is_complete(self):
        return self.status == "completed"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "assessment_type": self.assessment_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "audio_path_prepared": self.audio_path_prepared,
            "audio_path_spontaneous": self.audio_path_spontaneous,
            "transcript_prepared": self.transcript_prepared,
            "transcript_spontaneous": self.transcript_spontaneous,
            "duration_prepared": self.duration_prepared,
            "duration_spontaneous": self.duration_spontaneous,
            "topic_vector_prepared": self.topic_vector_prepared,
            "topic_vector_spontaneous": self.topic_vector_spontaneous,
            "status": self.status,
            "error_message": self.error_message,
            "celery_task_id": self.celery_task_id,
            "is_complete": self.is_complete,
        }
