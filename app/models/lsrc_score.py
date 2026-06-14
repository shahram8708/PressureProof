from datetime import datetime

from app.extensions import db
from app.models.assessment import Assessment


class LsrcScore(db.Model):
    __tablename__ = "lsrc_scores"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    source_type = db.Column(db.String(20), nullable=False)
    source_id = db.Column(db.Integer, nullable=False)
    scored_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    condition = db.Column(db.String(20), nullable=False)

    lexical_diversity = db.Column(db.Numeric(5, 2), nullable=True)
    syntactic_complexity = db.Column(db.Numeric(5, 2), nullable=True)
    prosodic_confidence = db.Column(db.Numeric(5, 2), nullable=True)
    disfluency_rate = db.Column(db.Numeric(5, 2), nullable=True)
    sentence_completion = db.Column(db.Numeric(5, 2), nullable=True)
    recovery_speed_seconds = db.Column(db.Numeric(5, 2), nullable=True)
    recovery_speed_score = db.Column(db.Numeric(5, 2), nullable=True)

    @property
    def composite_score(self):
        values = [
            self.lexical_diversity,
            self.syntactic_complexity,
            self.prosodic_confidence,
            self.disfluency_rate,
            self.sentence_completion,
            self.recovery_speed_score,
        ]
        valid_values = [float(value) for value in values if value is not None]
        if not valid_values:
            return None
        return round(sum(valid_values) / len(valid_values), 2)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "scored_at": self.scored_at.isoformat() if self.scored_at else None,
            "condition": self.condition,
            "lexical_diversity": (
                float(self.lexical_diversity) if self.lexical_diversity is not None else None
            ),
            "syntactic_complexity": (
                float(self.syntactic_complexity) if self.syntactic_complexity is not None else None
            ),
            "prosodic_confidence": (
                float(self.prosodic_confidence) if self.prosodic_confidence is not None else None
            ),
            "disfluency_rate": (
                float(self.disfluency_rate) if self.disfluency_rate is not None else None
            ),
            "sentence_completion": (
                float(self.sentence_completion) if self.sentence_completion is not None else None
            ),
            "recovery_speed_seconds": (
                float(self.recovery_speed_seconds)
                if self.recovery_speed_seconds is not None
                else None
            ),
            "recovery_speed_score": (
                float(self.recovery_speed_score)
                if self.recovery_speed_score is not None
                else None
            ),
            "composite_score": self.composite_score,
        }

    @classmethod
    def get_user_scores_by_week(cls, user_id, week_start, week_end):
        return (
            cls.query.filter(
                cls.user_id == user_id,
                cls.scored_at >= week_start,
                cls.scored_at <= week_end,
            )
            .order_by(cls.scored_at.asc())
            .all()
        )

    @classmethod
    def get_user_baseline_scores(cls, user_id):
        first_assessment = (
            Assessment.query.filter_by(user_id=user_id, assessment_type="baseline")
            .order_by(Assessment.created_at.asc())
            .first()
        )
        if first_assessment is None:
            return []

        return (
            cls.query.filter_by(
                user_id=user_id,
                source_type="assessment",
                source_id=first_assessment.id,
            )
            .order_by(cls.scored_at.asc())
            .all()
        )
