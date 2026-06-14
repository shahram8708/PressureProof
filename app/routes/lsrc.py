from datetime import date, datetime, time, timedelta

from flask import Blueprint, render_template, request
from flask_login import current_user, login_required

from app.models import FailureMode, LsrcScore, PgiRecord
from app.services.pgi_calculator import (
    compute_pgi_projection,
    compute_weekly_pgi,
    get_pgi_trend_data,
)
from app.utils.helpers import (
    generate_dimension_narrative,
    generate_focus_recommendation,
    get_sidebar_context,
)


lsrc_bp = Blueprint("lsrc", __name__, url_prefix="/")


DIMENSIONS = [
    ("lexical_diversity", "Lexical Diversity", "lexical_diversity"),
    ("syntactic_complexity", "Syntactic Complexity", "syntactic_complexity"),
    ("prosodic_confidence", "Prosodic Confidence", "prosodic_confidence"),
    ("disfluency_rate", "Disfluency Rate", "disfluency_rate"),
    ("sentence_completion", "Sentence Completion", "sentence_completion"),
    ("recovery_speed", "Recovery Speed", "recovery_speed_score"),
]


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_week_param(week_start):
    iso_year, iso_week, _ = week_start.isocalendar()
    return f"{iso_year}-{iso_week:02d}"


def _parse_week_param(week_param):
    today = date.today()
    current_week_start = today - timedelta(days=today.weekday())

    if not week_param:
        return current_week_start

    try:
        year_text, week_text = week_param.split("-")
        year = int(year_text)
        week = int(week_text)
        parsed = date.fromisocalendar(year, week, 1)
        if parsed > current_week_start:
            return current_week_start
        return parsed
    except (ValueError, TypeError):
        return current_week_start


def _week_bounds(week_start):
    start_dt = datetime.combine(week_start, time.min)
    end_dt = start_dt + timedelta(days=7)
    return start_dt, end_dt


def _average(records, field_name):
    values = []
    for record in records:
        value = _safe_float(getattr(record, field_name, None))
        if value is not None:
            values.append(value)
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _build_condition_averages(prepared_scores, spontaneous_scores):
    prepared = {}
    spontaneous = {}
    for dimension_name, _, field_name in DIMENSIONS:
        prepared[dimension_name] = _average(prepared_scores, field_name)
        spontaneous[dimension_name] = _average(spontaneous_scores, field_name)
    return prepared, spontaneous


def _gap_trend_direction(current_gap, prior_gap):
    if current_gap is None or prior_gap is None:
        return "stable"
    if current_gap < (prior_gap - 1.0):
        return "improving"
    if current_gap > (prior_gap + 1.0):
        return "declining"
    return "stable"


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


@lsrc_bp.get("/lsrc")
@login_required
def dashboard():
    selected_week = _parse_week_param(request.args.get("week"))
    current_week_start = date.today() - timedelta(days=date.today().weekday())
    selected_week_param = _to_week_param(selected_week)

    previous_week_start = selected_week - timedelta(days=7)
    previous_week_param = _to_week_param(previous_week_start)

    next_week_start = selected_week + timedelta(days=7)
    can_go_next = next_week_start <= current_week_start
    next_week_param = _to_week_param(next_week_start) if can_go_next else None

    week_start_dt, week_end_dt = _week_bounds(selected_week)
    week_scores = (
        LsrcScore.query.filter(
            LsrcScore.user_id == current_user.id,
            LsrcScore.scored_at >= week_start_dt,
            LsrcScore.scored_at < week_end_dt,
        )
        .order_by(LsrcScore.scored_at.asc())
        .all()
    )

    prepared_scores = [score for score in week_scores if score.condition == "prepared"]
    spontaneous_scores = [score for score in week_scores if score.condition == "spontaneous"]
    has_data = bool(week_scores)

    prior_start_dt, prior_end_dt = _week_bounds(previous_week_start)
    prior_scores = (
        LsrcScore.query.filter(
            LsrcScore.user_id == current_user.id,
            LsrcScore.scored_at >= prior_start_dt,
            LsrcScore.scored_at < prior_end_dt,
        )
        .order_by(LsrcScore.scored_at.asc())
        .all()
    )
    prior_prepared_scores = [score for score in prior_scores if score.condition == "prepared"]
    prior_spontaneous_scores = [score for score in prior_scores if score.condition == "spontaneous"]

    prepared_averages, spontaneous_averages = _build_condition_averages(
        prepared_scores,
        spontaneous_scores,
    )
    prior_prepared_averages, prior_spontaneous_averages = _build_condition_averages(
        prior_prepared_scores,
        prior_spontaneous_scores,
    )

    recovery_prepared_seconds = _average(prepared_scores, "recovery_speed_seconds")
    recovery_spontaneous_seconds = _average(spontaneous_scores, "recovery_speed_seconds")
    prior_recovery_prepared_seconds = _average(prior_prepared_scores, "recovery_speed_seconds")
    prior_recovery_spontaneous_seconds = _average(prior_spontaneous_scores, "recovery_speed_seconds")

    pgi_record = PgiRecord.query.filter_by(
        user_id=current_user.id,
        week_start_date=selected_week,
    ).first()
    if pgi_record is None:
        pgi_record = compute_weekly_pgi(current_user.id, selected_week)

    week_pgi = _safe_float(pgi_record.pgi_score) if pgi_record else None

    radar_chart_data = {
        "labels": [display_name for _, display_name, _ in DIMENSIONS],
        "datasets": [
            {
                "label": "Prepared English",
                "data": [prepared_averages.get(dimension) or 0 for dimension, _, _ in DIMENSIONS],
                "borderColor": "#4F46E5",
                "backgroundColor": "rgba(79,70,229,0.15)",
                "pointBackgroundColor": "#4F46E5",
            },
            {
                "label": "English Under Pressure",
                "data": [
                    spontaneous_averages.get(dimension) or 0 for dimension, _, _ in DIMENSIONS
                ],
                "borderColor": "#F59E0B",
                "backgroundColor": "rgba(245,158,11,0.15)",
                "pointBackgroundColor": "#F59E0B",
            },
        ],
        "has_data": has_data,
    }

    dimension_details = []
    current_gaps = {}

    for dimension_name, display_name, _ in DIMENSIONS:
        prepared_score = prepared_averages.get(dimension_name)
        spontaneous_score = spontaneous_averages.get(dimension_name)
        prior_prepared = prior_prepared_averages.get(dimension_name)
        prior_spontaneous = prior_spontaneous_averages.get(dimension_name)

        current_gap = None
        prior_gap = None
        if prepared_score is not None and spontaneous_score is not None:
            current_gap = round(prepared_score - spontaneous_score, 2)
            current_gaps[dimension_name] = current_gap
        if prior_prepared is not None and prior_spontaneous is not None:
            prior_gap = round(prior_prepared - prior_spontaneous, 2)

        trend_direction = _gap_trend_direction(current_gap, prior_gap)

        if dimension_name == "recovery_speed":
            narrative = generate_dimension_narrative(
                dimension_name,
                recovery_prepared_seconds,
                recovery_spontaneous_seconds,
                prior_recovery_prepared_seconds,
                prior_recovery_spontaneous_seconds,
            )
        else:
            narrative = generate_dimension_narrative(
                dimension_name,
                prepared_score,
                spontaneous_score,
                prior_prepared,
                prior_spontaneous,
            )

        dimension_details.append(
            {
                "dimension_name": dimension_name,
                "display_name": display_name,
                "prepared_score": prepared_score,
                "spontaneous_score": spontaneous_score,
                "gap": current_gap,
                "prior_week_prepared": prior_prepared,
                "prior_week_spontaneous": prior_spontaneous,
                "trend_direction": trend_direction,
                "narrative": narrative,
                "prepared_seconds": (
                    recovery_prepared_seconds if dimension_name == "recovery_speed" else None
                ),
                "spontaneous_seconds": (
                    recovery_spontaneous_seconds if dimension_name == "recovery_speed" else None
                ),
            }
        )

    failure_mode = FailureMode.query.filter_by(user_id=current_user.id).first()
    if current_gaps:
        focus_dimension = max(current_gaps.items(), key=lambda item: item[1])[0]
        focus_gap = current_gaps[focus_dimension]
    elif failure_mode and failure_mode.primary_dimension:
        focus_dimension = failure_mode.primary_dimension
        focus_gap = 0.0
    else:
        focus_dimension = "lexical_diversity"
        focus_gap = 0.0

    focus_recommendation = generate_focus_recommendation(focus_dimension, focus_gap)
    week_label = f"Week of {selected_week.strftime('%B')} {selected_week.day}, {selected_week.year}"

    return render_template(
        "lsrc/dashboard.html",
        title="My LSRC",
        has_data=has_data,
        selected_week_start=selected_week,
        selected_week_param=selected_week_param,
        previous_week_param=previous_week_param,
        next_week_param=next_week_param,
        can_go_next=can_go_next,
        week_label=week_label,
        radar_chart_data=radar_chart_data,
        week_pgi=week_pgi,
        failure_mode=failure_mode,
        dimension_details=dimension_details,
        focus_recommendation=focus_recommendation,
        **_sidebar_payload(current_user.id),
    )


def _trend_direction_from_values(trend_data):
    valid_values = [entry["pgi_score"] for entry in trend_data if entry.get("pgi_score") is not None]
    if len(valid_values) < 2:
        return "stable"
    previous_value = float(valid_values[-2])
    latest_value = float(valid_values[-1])
    if latest_value < previous_value:
        return "improving"
    if latest_value > previous_value:
        return "declining"
    return "stable"


@lsrc_bp.get("/pgi")
@login_required
def pgi():
    trend_data = get_pgi_trend_data(current_user.id, weeks=12)
    projection_data = compute_pgi_projection(trend_data)

    latest_record = (
        PgiRecord.query.filter_by(user_id=current_user.id)
        .order_by(PgiRecord.week_start_date.desc())
        .first()
    )
    current_pgi = _safe_float(latest_record.pgi_score) if latest_record else None
    trend_direction = _trend_direction_from_values(trend_data)

    current_week_start = date.today() - timedelta(days=date.today().weekday())
    week_start_dt, week_end_dt = _week_bounds(current_week_start)
    week_scores = (
        LsrcScore.query.filter(
            LsrcScore.user_id == current_user.id,
            LsrcScore.scored_at >= week_start_dt,
            LsrcScore.scored_at < week_end_dt,
        )
        .order_by(LsrcScore.scored_at.asc())
        .all()
    )

    prepared_scores = [score for score in week_scores if score.condition == "prepared"]
    spontaneous_scores = [score for score in week_scores if score.condition == "spontaneous"]

    dimension_rows = []
    for dimension_name, display_name, field_name in DIMENSIONS:
        prepared_avg = _average(prepared_scores, field_name)
        spontaneous_avg = _average(spontaneous_scores, field_name)
        gap = 0.0
        if prepared_avg is not None and spontaneous_avg is not None:
            gap = max(0.0, round(prepared_avg - spontaneous_avg, 2))

        dimension_rows.append(
            {
                "dimension": dimension_name,
                "display_name": display_name,
                "gap": gap,
            }
        )

    dimension_rows.sort(key=lambda row: row["gap"], reverse=True)
    dimension_contribution_data = {
        "labels": [row["display_name"] for row in dimension_rows],
        "data": [row["gap"] for row in dimension_rows],
    }

    largest_gap_dimension = dimension_rows[0] if dimension_rows else None

    return render_template(
        "lsrc/pgi.html",
        title="PGI Tracker",
        trend_data=trend_data,
        projection_data=projection_data,
        current_pgi=current_pgi,
        trend_direction=trend_direction,
        dimension_contribution_data=dimension_contribution_data,
        largest_gap_dimension=largest_gap_dimension,
        **_sidebar_payload(current_user.id),
    )
