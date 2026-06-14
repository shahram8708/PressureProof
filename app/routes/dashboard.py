from datetime import date, datetime, time, timedelta

from flask import Blueprint, render_template
from flask_login import current_user, login_required
from sqlalchemy import func

from app.extensions import db
from app.models import FailureMode, LsrcScore, PgiRecord, SessionCalibration
from app.services.calibration_engine import compute_next_session
from app.utils.helpers import get_sidebar_context, get_week_label


dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/")


DIMENSION_DISPLAY_MAP = {
    "lexical_diversity": "Lexical Diversity",
    "syntactic_complexity": "Syntactic Complexity",
    "prosodic_confidence": "Prosodic Confidence",
    "disfluency_rate": "Disfluency Rate",
    "sentence_completion": "Sentence Completion",
    "recovery_speed": "Recovery Speed",
}


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _current_week_bounds():
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    start = datetime.combine(week_start, time.min)
    end = start + timedelta(days=7)
    return week_start, start, end


def _readiness_score(user_id, current_pgi):
    recent_scores = (
        LsrcScore.query.filter_by(user_id=user_id)
        .order_by(LsrcScore.scored_at.desc())
        .limit(7)
        .all()
    )

    composite_values = [
        _safe_float(score.composite_score)
        for score in recent_scores
        if _safe_float(score.composite_score) is not None
    ]
    if not composite_values:
        return None

    mean_composite = sum(composite_values) / len(composite_values)
    if current_pgi is not None:
        mean_composite *= 1.0 - (current_pgi / 100.0)

    readiness = int(round(mean_composite))
    return max(0, min(100, readiness))


def _query_training_sessions_for_range(user_id, start_dt, end_dt):
    try:
        from app.models import TrainingSession

        timestamp_column = getattr(TrainingSession, "completed_at", None) or getattr(
            TrainingSession,
            "created_at",
            None,
        )
        if timestamp_column is None:
            return []

        return (
            TrainingSession.query.filter(
                TrainingSession.user_id == user_id,
                timestamp_column >= start_dt,
                timestamp_column < end_dt,
            )
            .order_by(timestamp_column.desc())
            .all()
        )
    except Exception:
        return []


def _query_snapspeaks_for_range(user_id, start_dt, end_dt):
    try:
        from app.models import SnapSpeakRecord

        timestamp_column = getattr(SnapSpeakRecord, "captured_at", None) or getattr(
            SnapSpeakRecord,
            "created_at",
            None,
        )
        if timestamp_column is None:
            return []

        return (
            SnapSpeakRecord.query.filter(
                SnapSpeakRecord.user_id == user_id,
                timestamp_column >= start_dt,
                timestamp_column < end_dt,
            )
            .order_by(timestamp_column.desc())
            .all()
        )
    except Exception:
        return []


def _recommended_action(user_id):
    today_start = datetime.combine(date.today(), time.min)
    tomorrow_start = today_start + timedelta(days=1)

    sessions_today = _query_training_sessions_for_range(user_id, today_start, tomorrow_start)
    snapspeaks_today = _query_snapspeaks_for_range(user_id, today_start, tomorrow_start)

    if len(sessions_today) == 0:
        return "session", len(sessions_today), len(snapspeaks_today)
    if len(snapspeaks_today) == 0:
        return "snapspeak", len(sessions_today), len(snapspeaks_today)
    return "complete", len(sessions_today), len(snapspeaks_today)


def _recent_snapspeaks(user_id, limit=3):
    try:
        from app.models import SnapSpeakRecord

        timestamp_column = getattr(SnapSpeakRecord, "captured_at", None) or getattr(
            SnapSpeakRecord,
            "created_at",
            None,
        )
        ordering_column = timestamp_column if timestamp_column is not None else SnapSpeakRecord.id

        return (
            SnapSpeakRecord.query.filter(SnapSpeakRecord.user_id == user_id)
            .order_by(ordering_column.desc())
            .limit(limit)
            .all()
        )
    except Exception:
        return []


def _sidebar_payload(user_id):
    sidebar_context = get_sidebar_context(user_id)
    return {
        "pgi_summary": {
            "current_pgi": sidebar_context.get("current_pgi"),
            "pgi_direction": sidebar_context.get("pgi_direction"),
        },
        "subscription_info": {
            "subscription_tier": sidebar_context.get("subscription_tier"),
            "trial_days_remaining": sidebar_context.get("trial_days_remaining"),
        },
    }


@dashboard_bp.get("/dashboard")
@login_required
def index():
    latest_pgi_record = (
        PgiRecord.query.filter_by(user_id=current_user.id)
        .order_by(PgiRecord.week_start_date.desc())
        .first()
    )
    current_pgi = _safe_float(latest_pgi_record.pgi_score) if latest_pgi_record else None

    pgi_trend_records = PgiRecord.get_user_trend(current_user.id, weeks=7)
    pgi_sparkline_data = [
        {
            "week_label": get_week_label(record.week_start_date),
            "pgi_score": _safe_float(record.pgi_score),
        }
        for record in pgi_trend_records
    ]

    readiness_score = _readiness_score(current_user.id, current_pgi)

    calibration = SessionCalibration.query.filter_by(user_id=current_user.id).first()
    is_stale = calibration is None or (
        calibration.computed_at and calibration.computed_at < (datetime.utcnow() - timedelta(hours=48))
    )
    if is_stale:
        calibration = compute_next_session(current_user.id)

    recommended_action, sessions_today, snapspeaks_today = _recommended_action(current_user.id)

    recent_snapspeaks = _recent_snapspeaks(current_user.id, limit=3)

    week_start, week_start_dt, week_end_dt = _current_week_bounds()
    sessions_this_week = len(_query_training_sessions_for_range(current_user.id, week_start_dt, week_end_dt))
    snapspeaks_this_week = len(_query_snapspeaks_for_range(current_user.id, week_start_dt, week_end_dt))

    days_active = (
        db.session.query(func.count(func.distinct(func.date(LsrcScore.scored_at))))
        .filter(LsrcScore.user_id == current_user.id)
        .scalar()
        or 0
    )

    failure_mode = FailureMode.query.filter_by(user_id=current_user.id).first()
    focus_dimension_key = (
        failure_mode.primary_dimension if failure_mode and failure_mode.primary_dimension else "lexical_diversity"
    )
    focus_dimension = DIMENSION_DISPLAY_MAP.get(focus_dimension_key, "Lexical Diversity")

    return render_template(
        "dashboard/index.html",
        title="Dashboard",
        current_pgi=current_pgi,
        pgi_sparkline_data=pgi_sparkline_data,
        readiness_score=readiness_score,
        recommended_action=recommended_action,
        recent_snapspeaks=recent_snapspeaks,
        sessions_this_week=sessions_this_week,
        snapspeaks_this_week=snapspeaks_this_week,
        days_active=days_active,
        focus_dimension=focus_dimension,
        sessions_today=sessions_today,
        snapspeaks_today=snapspeaks_today,
        **_sidebar_payload(current_user.id),
    )


@dashboard_bp.get("/dashboard/drills")
@login_required
def drills_library():
    return render_template(
        "drills/library.html",
        title="Drills Library",
        **_sidebar_payload(current_user.id),
    )


@dashboard_bp.get("/dashboard/drills/active")
@login_required
def drills_active():
    return render_template(
        "drills/active.html",
        title="Active Drill",
        **_sidebar_payload(current_user.id),
    )
