from datetime import datetime

from sqlalchemy import func

from app.extensions import db
from app.models.lsrc_score import LsrcScore


class Cohort(db.Model):
    __tablename__ = "cohorts"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class CohortAggregate(db.Model):
    __tablename__ = "cohort_aggregates"
    __table_args__ = (
        db.UniqueConstraint("cohort_key", "dimension", name="uq_cohort_dimension"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    cohort_key = db.Column(db.String(200), nullable=False, index=True)
    dimension = db.Column(db.String(50), nullable=False)

    percentile_10 = db.Column(db.Numeric(5, 2), nullable=True)
    percentile_25 = db.Column(db.Numeric(5, 2), nullable=True)
    percentile_50 = db.Column(db.Numeric(5, 2), nullable=True)
    percentile_75 = db.Column(db.Numeric(5, 2), nullable=True)
    percentile_90 = db.Column(db.Numeric(5, 2), nullable=True)

    user_count = db.Column(db.Integer, nullable=False, default=0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @classmethod
    def get_cohort_data(cls, cohort_key):
        rows = cls.query.filter_by(cohort_key=cohort_key).all()
        return {row.dimension: row for row in rows}

    @classmethod
    def get_user_cohort_key(cls, user):
        professional_context = (getattr(user, "professional_context", None) or "Other").strip()
        l1_language = (getattr(user, "l1_language", None) or "Other").strip()

        user_scores = (
            LsrcScore.query.filter_by(user_id=user.id)
            .order_by(LsrcScore.scored_at.desc())
            .limit(30)
            .all()
        )
        composites = [float(score.composite_score) for score in user_scores if score.composite_score is not None]
        avg_composite = sum(composites) / len(composites) if composites else 0.0

        if avg_composite >= 75:
            tier = "C1"
        elif avg_composite >= 55:
            tier = "B2"
        else:
            tier = "B1"

        return f"{professional_context}|{l1_language}|{tier}"

    @classmethod
    def list_cohort_keys(cls):
        rows = db.session.query(cls.cohort_key).distinct().order_by(func.lower(cls.cohort_key)).all()
        return [row[0] for row in rows]
