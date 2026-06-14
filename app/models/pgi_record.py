from datetime import date, datetime, timedelta

from app.extensions import db


class PgiRecord(db.Model):
    __tablename__ = "pgi_records"
    __table_args__ = (
        db.UniqueConstraint("user_id", "week_start_date", name="uq_user_week_pgi"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    week_start_date = db.Column(db.Date, nullable=False, index=True)
    pgi_score = db.Column(db.Numeric(5, 2), nullable=True)
    prepared_composite = db.Column(db.Numeric(5, 2), nullable=True)
    spontaneous_composite = db.Column(db.Numeric(5, 2), nullable=True)
    sessions_count = db.Column(db.Integer, default=0, nullable=False)
    snapspeak_count = db.Column(db.Integer, default=0, nullable=False)
    topic_matched = db.Column(db.Boolean, default=False, nullable=False)
    calculated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship(
        "User",
        backref=db.backref("pgi_records", lazy="dynamic", order_by="PgiRecord.week_start_date"),
    )

    @classmethod
    def get_user_trend(cls, user_id, weeks=12):
        window = max(1, int(weeks or 12))
        records = (
            cls.query.filter_by(user_id=user_id)
            .order_by(cls.week_start_date.desc())
            .limit(window)
            .all()
        )
        return list(reversed(records))

    @classmethod
    def get_current_week_record(cls, user_id):
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        return cls.query.filter_by(user_id=user_id, week_start_date=week_start).first()

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "week_start_date": (
                self.week_start_date.strftime("%Y-%m-%d") if self.week_start_date else None
            ),
            "pgi_score": float(self.pgi_score) if self.pgi_score is not None else None,
            "prepared_composite": (
                float(self.prepared_composite) if self.prepared_composite is not None else None
            ),
            "spontaneous_composite": (
                float(self.spontaneous_composite)
                if self.spontaneous_composite is not None
                else None
            ),
            "sessions_count": self.sessions_count,
            "snapspeak_count": self.snapspeak_count,
            "topic_matched": self.topic_matched,
            "calculated_at": self.calculated_at.isoformat() if self.calculated_at else None,
        }
