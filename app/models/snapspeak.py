from datetime import date, datetime, time, timedelta

from sqlalchemy import func

from app.extensions import db


class SnapSpeakRecord(db.Model):
    __tablename__ = "snapspeak_records"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    captured_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    prompt_text = db.Column(db.Text, nullable=False)
    prompt_type = db.Column(db.String(20), nullable=False, default="random")
    context_tag = db.Column(db.String(20), nullable=True)

    audio_path = db.Column(db.String(500), nullable=True)
    transcript = db.Column(db.Text, nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)

    status = db.Column(db.String(20), nullable=False, default="pending")
    error_message = db.Column(db.Text, nullable=True)
    celery_task_id = db.Column(db.String(100), nullable=True)

    topic_vector = db.Column(db.Text, nullable=True)

    analysis_line_1 = db.Column(db.Text, nullable=True)
    analysis_line_2 = db.Column(db.Text, nullable=True)
    analysis_line_3 = db.Column(db.Text, nullable=True)

    is_notable = db.Column(db.Boolean, nullable=False, default=False)
    notable_annotation = db.Column(db.String(200), nullable=True)

    user = db.relationship(
        "User",
        backref=db.backref(
            "snapspeak_records",
            lazy="dynamic",
            order_by="SnapSpeakRecord.captured_at.desc()",
        ),
    )

    @property
    def short_prompt(self):
        text = (self.prompt_text or "").strip()
        if len(text) <= 70:
            return text
        return f"{text[:70].rstrip()}..."

    @property
    def prompt(self):
        return self.prompt_text

    @property
    def created_at(self):
        return self.captured_at

    @classmethod
    def get_user_history(cls, user_id, tag_filter=None, limit=50):
        query = cls.query.filter_by(user_id=user_id)
        if tag_filter:
            query = query.filter(cls.context_tag == tag_filter)
        return query.order_by(cls.captured_at.desc()).limit(limit).all()

    @classmethod
    def get_today_count(cls, user_id):
        today_start = datetime.combine(date.today(), time.min)
        tomorrow_start = today_start + timedelta(days=1)
        return (
            cls.query.filter(
                cls.user_id == user_id,
                cls.captured_at >= today_start,
                cls.captured_at < tomorrow_start,
            ).count()
        )

    @classmethod
    def get_user_baseline_snapspeaks(cls, user_id, limit=10):
        return (
            cls.query.filter_by(user_id=user_id, status="completed")
            .order_by(cls.captured_at.desc())
            .limit(limit)
            .all()
        )

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "prompt_text": self.prompt_text,
            "prompt_type": self.prompt_type,
            "context_tag": self.context_tag,
            "audio_path": self.audio_path,
            "transcript": self.transcript,
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "error_message": self.error_message,
            "celery_task_id": self.celery_task_id,
            "topic_vector": self.topic_vector,
            "analysis_line_1": self.analysis_line_1,
            "analysis_line_2": self.analysis_line_2,
            "analysis_line_3": self.analysis_line_3,
            "is_notable": self.is_notable,
            "notable_annotation": self.notable_annotation,
            "short_prompt": self.short_prompt,
        }


class DrillCompletion(db.Model):
    __tablename__ = "drill_completions"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    drill_id = db.Column(db.Integer, db.ForeignKey("drills.id"), nullable=False)
    completed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    recovery_time_seconds = db.Column(db.Numeric(5, 2), nullable=True)
    pathway_used = db.Column(db.String(50), nullable=True)
    transcript_excerpt = db.Column(db.Text, nullable=True)
    audio_path = db.Column(db.String(500), nullable=True)
    session_id = db.Column(db.Integer, db.ForeignKey("training_sessions.id"), nullable=True)

    user = db.relationship("User", backref=db.backref("drill_completions", lazy="dynamic"))
    drill = db.relationship("Drill", backref=db.backref("completions", lazy="dynamic"))

    @classmethod
    def get_user_stats(cls, user_id):
        from app.models.session import Drill

        completions = (
            cls.query.filter_by(user_id=user_id)
            .order_by(cls.completed_at.desc())
            .all()
        )
        total_completions = len(completions)

        recovery_values = [
            float(item.recovery_time_seconds)
            for item in completions
            if item.recovery_time_seconds is not None
        ]

        average_recovery_time = None
        best_recovery_time = None
        if recovery_values:
            average_recovery_time = round(sum(recovery_values) / len(recovery_values), 2)
            best_recovery_time = round(min(recovery_values), 2)

        category_rows = (
            db.session.query(Drill.category, func.count(cls.id))
            .join(Drill, Drill.id == cls.drill_id)
            .filter(cls.user_id == user_id)
            .group_by(Drill.category)
            .all()
        )
        completions_by_category = {category: int(count) for category, count in category_rows}

        latest_with_recovery = []
        for item in completions:
            if item.recovery_time_seconds is not None:
                latest_with_recovery.append(round(float(item.recovery_time_seconds), 2))
            if len(latest_with_recovery) >= 7:
                break
        latest_with_recovery.reverse()

        return {
            "total_completions": total_completions,
            "average_recovery_time": average_recovery_time,
            "best_recovery_time": best_recovery_time,
            "completions_by_category": completions_by_category,
            "recent_trend": latest_with_recovery,
        }

    @classmethod
    def get_category_stats(cls, user_id, category):
        from app.models.session import Drill

        rows = (
            cls.query.join(Drill, Drill.id == cls.drill_id)
            .filter(cls.user_id == user_id, Drill.category == category)
            .all()
        )

        values = [
            float(item.recovery_time_seconds)
            for item in rows
            if item.recovery_time_seconds is not None
        ]

        avg_value = round(sum(values) / len(values), 2) if values else None
        return {
            "average_recovery_time": avg_value,
            "completion_count": len(rows),
        }

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "drill_id": self.drill_id,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "recovery_time_seconds": (
                float(self.recovery_time_seconds) if self.recovery_time_seconds is not None else None
            ),
            "pathway_used": self.pathway_used,
            "transcript_excerpt": self.transcript_excerpt,
            "audio_path": self.audio_path,
            "session_id": self.session_id,
        }


SnapSpeakCapture = SnapSpeakRecord
