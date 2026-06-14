from datetime import date, datetime

from flask import current_app, url_for

from app.extensions import db
from app.models.session import TrainingSession


class Certificate(db.Model):
    __tablename__ = "certificates"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)

    generated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    baseline_pgi = db.Column(db.Numeric(5, 2), nullable=True)
    current_pgi = db.Column(db.Numeric(5, 2), nullable=True)
    pgi_improvement_pct = db.Column(db.Numeric(5, 2), nullable=True)

    strongest_dimension = db.Column(db.String(50), nullable=True)
    strongest_dimension_improvement = db.Column(db.Numeric(5, 2), nullable=True)

    cohort_percentile = db.Column(db.Numeric(5, 2), nullable=True)

    date_range_start = db.Column(db.Date, nullable=True)
    date_range_end = db.Column(db.Date, nullable=True)

    months_active = db.Column(db.Integer, nullable=True)

    pdf_path = db.Column(db.String(500), nullable=True)
    pdf_generated_at = db.Column(db.DateTime, nullable=True)

    linkedin_share_token = db.Column(db.String(100), nullable=True, unique=True)
    is_public = db.Column(db.Boolean, default=True, nullable=False)

    user = db.relationship("User", backref=db.backref("certificate", uselist=False))

    @property
    def is_eligible(self):
        if self.user is None:
            return False

        first_session = (
            TrainingSession.query.filter_by(user_id=self.user_id, status="completed")
            .order_by(TrainingSession.created_at.asc())
            .first()
        )
        if first_session is None:
            return False

        session_count = TrainingSession.query.filter_by(user_id=self.user_id, status="completed").count()
        if session_count < 20:
            return False

        days_elapsed = (datetime.utcnow().date() - first_session.created_at.date()).days
        return days_elapsed > 180

    @property
    def share_url(self):
        if not self.linkedin_share_token:
            return None
        try:
            return url_for("certificate.public_share", token=self.linkedin_share_token, _external=True)
        except RuntimeError:
            base_url = current_app.config.get("PUBLIC_BASE_URL", "").rstrip("/")
            if not base_url:
                return None
            return f"{base_url}/certificate/share/{self.linkedin_share_token}"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "baseline_pgi": float(self.baseline_pgi) if self.baseline_pgi is not None else None,
            "current_pgi": float(self.current_pgi) if self.current_pgi is not None else None,
            "pgi_improvement_pct": (
                float(self.pgi_improvement_pct) if self.pgi_improvement_pct is not None else None
            ),
            "strongest_dimension": self.strongest_dimension,
            "strongest_dimension_improvement": (
                float(self.strongest_dimension_improvement)
                if self.strongest_dimension_improvement is not None
                else None
            ),
            "cohort_percentile": float(self.cohort_percentile) if self.cohort_percentile is not None else None,
            "date_range_start": self.date_range_start.isoformat() if isinstance(self.date_range_start, date) else None,
            "date_range_end": self.date_range_end.isoformat() if isinstance(self.date_range_end, date) else None,
            "months_active": self.months_active,
            "pdf_path": self.pdf_path,
            "pdf_generated_at": self.pdf_generated_at.isoformat() if self.pdf_generated_at else None,
            "linkedin_share_token": self.linkedin_share_token,
            "is_public": self.is_public,
            "share_url": self.share_url,
            "is_eligible": self.is_eligible,
        }
