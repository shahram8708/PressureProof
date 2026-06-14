from datetime import datetime

from app.extensions import db


class FailureMode(db.Model):
    __tablename__ = "failure_modes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)

    mode_code = db.Column(db.String(50), nullable=False)
    mode_label = db.Column(db.Text, nullable=False)
    mode_description = db.Column(db.Text, nullable=False)

    primary_dimension = db.Column(db.String(50), nullable=False)
    secondary_dimension = db.Column(db.String(50), nullable=True)

    confidence_score = db.Column(db.Numeric(3, 2), nullable=False, default=0.0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    evidence_session_count = db.Column(db.Integer, default=0, nullable=False)

    user = db.relationship("User", backref=db.backref("failure_mode", uselist=False))

    @property
    def confidence_label(self):
        score = float(self.confidence_score or 0.0)
        if score < 0.3:
            return "Estimated"
        if score <= 0.7:
            return "Likely"
        return "Confirmed"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "mode_code": self.mode_code,
            "mode_label": self.mode_label,
            "mode_description": self.mode_description,
            "primary_dimension": self.primary_dimension,
            "secondary_dimension": self.secondary_dimension,
            "confidence_score": float(self.confidence_score or 0.0),
            "confidence_label": self.confidence_label,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "evidence_session_count": self.evidence_session_count,
        }
