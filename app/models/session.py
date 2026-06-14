from datetime import date, datetime, time, timedelta

from app.extensions import db


class TrainingSession(db.Model):
    __tablename__ = "training_sessions"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)

    session_type = db.Column(db.String(50), nullable=False)
    prompt_text = db.Column(db.Text, nullable=False)

    stress_injection_type = db.Column(db.String(50), nullable=False)
    stress_injection_intensity = db.Column(db.Numeric(3, 2), nullable=False)
    injection_timestamp_seconds = db.Column(db.Integer, nullable=False)
    injection_actually_fired = db.Column(db.Boolean, default=False, nullable=False)

    early_exit = db.Column(db.Boolean, default=False, nullable=False)
    early_exit_reason = db.Column(db.String(100), nullable=True)

    audio_path = db.Column(db.String(500), nullable=True)
    transcript = db.Column(db.Text, nullable=True)

    session_number = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default="pending", nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    celery_task_id = db.Column(db.String(100), nullable=True)

    topic_vector = db.Column(db.Text, nullable=True)

    user = db.relationship(
        "User",
        backref=db.backref(
            "training_sessions",
            lazy="dynamic",
            order_by="TrainingSession.created_at.desc()",
        ),
    )
    injection_events = db.relationship("InjectionEvent", backref="session", lazy="dynamic")

    @property
    def session_number_label(self):
        return f"Session {self.session_number}"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "session_type": self.session_type,
            "prompt_text": self.prompt_text,
            "stress_injection_type": self.stress_injection_type,
            "stress_injection_intensity": (
                float(self.stress_injection_intensity)
                if self.stress_injection_intensity is not None
                else None
            ),
            "injection_timestamp_seconds": self.injection_timestamp_seconds,
            "injection_actually_fired": self.injection_actually_fired,
            "early_exit": self.early_exit,
            "early_exit_reason": self.early_exit_reason,
            "audio_path": self.audio_path,
            "transcript": self.transcript,
            "session_number": self.session_number,
            "session_number_label": self.session_number_label,
            "status": self.status,
            "error_message": self.error_message,
            "celery_task_id": self.celery_task_id,
            "topic_vector": self.topic_vector,
        }

    @classmethod
    def get_user_session_count(cls, user_id):
        return cls.query.filter_by(user_id=user_id, status="completed").count()

    @classmethod
    def get_last_session(cls, user_id):
        return cls.query.filter_by(user_id=user_id).order_by(cls.created_at.desc()).first()

    @classmethod
    def get_today_sessions(cls, user_id):
        today = date.today()
        day_start = datetime.combine(today, time.min)
        day_end = day_start + timedelta(days=1)
        return (
            cls.query.filter(
                cls.user_id == user_id,
                cls.created_at >= day_start,
                cls.created_at < day_end,
            )
            .order_by(cls.created_at.desc())
            .all()
        )


class InjectionEvent(db.Model):
    __tablename__ = "injection_events"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(
        db.Integer,
        db.ForeignKey("training_sessions.id"),
        nullable=False,
        index=True,
    )
    injection_type = db.Column(db.String(50), nullable=False)
    fired_at_seconds = db.Column(db.Numeric(6, 2), nullable=False)
    pressure_meter_value = db.Column(db.Numeric(3, 2), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "injection_type": self.injection_type,
            "fired_at_seconds": (
                float(self.fired_at_seconds) if self.fired_at_seconds is not None else None
            ),
            "pressure_meter_value": (
                float(self.pressure_meter_value)
                if self.pressure_meter_value is not None
                else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Drill(db.Model):
    __tablename__ = "drills"

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    difficulty_level = db.Column(db.Integer, nullable=False)
    estimated_seconds = db.Column(db.Integer, nullable=False)
    filler_phrases = db.Column(db.Text, nullable=False)
