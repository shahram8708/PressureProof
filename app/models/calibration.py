from datetime import datetime

from app.extensions import db


class SessionCalibration(db.Model):
    __tablename__ = "session_calibrations"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    computed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    next_session_type = db.Column(db.String(50), nullable=False)
    next_injection_type = db.Column(db.String(50), nullable=False)
    next_injection_intensity = db.Column(db.Numeric(3, 2), nullable=False, default=0.3)
    next_injection_timing_seconds = db.Column(db.Integer, nullable=False, default=10)
    target_dimension = db.Column(db.String(50), nullable=False)
    algorithm_version = db.Column(db.String(20), nullable=False, default="1.0")

    last_session_early_exit = db.Column(db.Boolean, default=False, nullable=False)
    current_stress_threshold = db.Column(db.Numeric(3, 2), default=0.3)

    user = db.relationship("User", backref=db.backref("calibration", uselist=False))

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "computed_at": self.computed_at.isoformat() if self.computed_at else None,
            "next_session_type": self.next_session_type,
            "next_injection_type": self.next_injection_type,
            "next_injection_intensity": (
                float(self.next_injection_intensity)
                if self.next_injection_intensity is not None
                else None
            ),
            "next_injection_timing_seconds": self.next_injection_timing_seconds,
            "target_dimension": self.target_dimension,
            "algorithm_version": self.algorithm_version,
            "last_session_early_exit": self.last_session_early_exit,
            "current_stress_threshold": (
                float(self.current_stress_threshold)
                if self.current_stress_threshold is not None
                else None
            ),
        }


Calibration = SessionCalibration
