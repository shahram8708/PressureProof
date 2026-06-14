from datetime import datetime
from io import BytesIO
from uuid import uuid4

from flask import render_template
from weasyprint import HTML

from app.extensions import db
from app.models import Certificate, LsrcScore, PgiRecord, TrainingSession, User
from . import cohort_service
from app.services.audio_storage import upload_pdf


DIMENSION_FIELDS = {
    "lexical_diversity": "lexical_diversity",
    "syntactic_complexity": "syntactic_complexity",
    "prosodic_confidence": "prosodic_confidence",
    "disfluency_rate": "disfluency_rate",
    "sentence_completion": "sentence_completion",
    "recovery_speed": "recovery_speed_score",
}


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _months_active_from_first_session(first_session):
    if first_session is None:
        return 0
    return max(0, (datetime.utcnow().date() - first_session.created_at.date()).days // 30)


def check_eligibility(user_id: int) -> dict:
    first_session = (
        TrainingSession.query.filter_by(user_id=user_id, status="completed")
        .order_by(TrainingSession.created_at.asc())
        .first()
    )
    session_count = TrainingSession.query.filter_by(user_id=user_id, status="completed").count()
    months_active = _months_active_from_first_session(first_session)

    if first_session is None:
        return {
            "eligible": False,
            "reason": "Complete your first training sessions to start certificate eligibility tracking.",
            "months_active": 0,
            "session_count": session_count,
            "weeks_until_eligible": 24,
        }

    if months_active < 6:
        days_remaining = max(0, 180 - (datetime.utcnow().date() - first_session.created_at.date()).days)
        weeks_until_eligible = (days_remaining + 6) // 7
        return {
            "eligible": False,
            "reason": "You need six months of active training before certificate generation unlocks.",
            "months_active": months_active,
            "session_count": session_count,
            "weeks_until_eligible": weeks_until_eligible,
        }

    if session_count < 20:
        remaining = 20 - session_count
        return {
            "eligible": False,
            "reason": f"Complete {remaining} more sessions to unlock your certificate.",
            "months_active": months_active,
            "session_count": session_count,
            "weeks_until_eligible": None,
        }

    return {
        "eligible": True,
        "reason": "Eligible",
        "months_active": months_active,
        "session_count": session_count,
        "weeks_until_eligible": None,
    }


def _compute_strongest_dimension(user_id):
    scores = (
        LsrcScore.query.filter_by(user_id=user_id, condition="spontaneous")
        .order_by(LsrcScore.scored_at.asc())
        .all()
    )
    if len(scores) < 3:
        return None, None

    strongest_dimension = None
    strongest_delta = None

    for dimension_key, field_name in DIMENSION_FIELDS.items():
        values = [_safe_float(getattr(score, field_name, None)) for score in scores]
        values = [value for value in values if value is not None]
        if len(values) < 3:
            continue

        first_avg = sum(values[:3]) / min(3, len(values))
        last_avg = sum(values[-3:]) / min(3, len(values))
        delta = last_avg - first_avg

        if strongest_delta is None or delta > strongest_delta:
            strongest_delta = delta
            strongest_dimension = dimension_key

    if strongest_dimension is None:
        return None, None
    return strongest_dimension, round(strongest_delta, 2)


def _build_certificate_data(user_id):
    user = User.query.get(user_id)
    if user is None:
        raise ValueError("User not found")

    first_session = (
        TrainingSession.query.filter_by(user_id=user_id, status="completed")
        .order_by(TrainingSession.created_at.asc())
        .first()
    )
    if first_session is None:
        raise ValueError("No completed sessions found")

    first_pgi = (
        PgiRecord.query.filter_by(user_id=user_id)
        .order_by(PgiRecord.week_start_date.asc())
        .first()
    )
    latest_pgi = (
        PgiRecord.query.filter_by(user_id=user_id)
        .order_by(PgiRecord.week_start_date.desc())
        .first()
    )

    baseline_pgi = _safe_float(first_pgi.pgi_score) if first_pgi else None
    current_pgi = _safe_float(latest_pgi.pgi_score) if latest_pgi else None

    improvement_pct = None
    if baseline_pgi not in (None, 0.0) and current_pgi is not None:
        improvement_pct = round(((baseline_pgi - current_pgi) / baseline_pgi) * 100.0, 2)

    strongest_dimension, strongest_delta = _compute_strongest_dimension(user_id)
    cohort_percentiles = cohort_service.get_user_cohort_percentiles(user_id)
    overall_percentile = _safe_float(cohort_percentiles.get("overall_percentile"))

    months_active = _months_active_from_first_session(first_session)
    share_token = str(uuid4())
    date_start = first_session.created_at.date()
    date_end = datetime.utcnow().date()

    data = {
        "user_id": user.id,
        "baseline_pgi": baseline_pgi,
        "current_pgi": current_pgi,
        "pgi_improvement_pct": improvement_pct,
        "strongest_dimension": strongest_dimension,
        "strongest_dimension_improvement": strongest_delta,
        "cohort_percentile": overall_percentile,
        "date_range_start": date_start,
        "date_range_end": date_end,
        "months_active": months_active,
        "linkedin_share_token": share_token,
    }
    return user, data


def generate_certificate(user_id: int) -> Certificate:
    eligibility = check_eligibility(user_id)
    if not eligibility.get("eligible"):
        raise ValueError(eligibility.get("reason") or "Not eligible")

    user, data = _build_certificate_data(user_id)

    rendered_html = render_template(
        "certificate/certificate_print.html",
        certificate_data=data,
        user=user,
    )

    pdf_buffer = BytesIO()
    HTML(string=rendered_html).write_pdf(target=pdf_buffer)
    pdf_bytes = pdf_buffer.getvalue()
    pdf_path = upload_pdf(pdf_bytes, user_id=user_id)

    certificate = Certificate.query.filter_by(user_id=user_id).first()
    if certificate is None:
        certificate = Certificate(user_id=user_id)
        db.session.add(certificate)

    certificate.generated_at = datetime.utcnow()
    certificate.baseline_pgi = data["baseline_pgi"]
    certificate.current_pgi = data["current_pgi"]
    certificate.pgi_improvement_pct = data["pgi_improvement_pct"]
    certificate.strongest_dimension = data["strongest_dimension"]
    certificate.strongest_dimension_improvement = data["strongest_dimension_improvement"]
    certificate.cohort_percentile = data["cohort_percentile"]
    certificate.date_range_start = data["date_range_start"]
    certificate.date_range_end = data["date_range_end"]
    certificate.months_active = data["months_active"]
    certificate.linkedin_share_token = data["linkedin_share_token"]
    certificate.is_public = True
    certificate.pdf_path = pdf_path
    certificate.pdf_generated_at = datetime.utcnow()

    db.session.commit()
    return certificate


def get_certificate_preview_data(user_id: int) -> dict:
    eligibility = check_eligibility(user_id)
    if not eligibility.get("eligible"):
        return {
            "eligible": False,
            "eligibility": eligibility,
        }

    user, data = _build_certificate_data(user_id)
    return {
        "eligible": True,
        "user": {
            "id": user.id,
            "display_name": user.display_name,
            "email": user.email,
        },
        "certificate_data": data,
        "eligibility": eligibility,
    }
