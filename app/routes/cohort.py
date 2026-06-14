from flask import Blueprint, render_template
from flask_login import current_user

from app.models import CohortAggregate
from app.services import cohort_service
from app.utils.helpers import get_sidebar_context
from app.utils.decorators import login_required


cohort_bp = Blueprint("cohort", __name__, url_prefix="/")


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


def _format_dimension_label(key):
    labels = {
        "lexical_diversity": "Lexical Diversity",
        "syntactic_complexity": "Syntactic Complexity",
        "prosodic_confidence": "Prosodic Confidence",
        "disfluency_rate": "Disfluency Rate",
        "sentence_completion": "Sentence Completion",
        "recovery_speed": "Recovery Speed",
    }
    return labels.get(key, key.replace("_", " ").title())


def _humanize_cohort_label(cohort_key):
    parts = (cohort_key or "").split("|")
    if len(parts) != 3:
        return cohort_key or "General Cohort"
    context, language, tier = [part.strip() for part in parts]
    if tier == "B2":
        tier = "B2-C1"
    return f"{context} | {language} | {tier}"


@cohort_bp.get("/cohort")
@login_required
def index():
    cohort_key = CohortAggregate.get_user_cohort_key(current_user)
    percentile_data = cohort_service.get_user_cohort_percentiles(current_user.id)
    distribution_data = cohort_service.get_cohort_distribution_data(cohort_key, "pgi")

    radar_labels = []
    user_scores = []
    cohort_medians = []

    for dimension in [
        "lexical_diversity",
        "syntactic_complexity",
        "prosodic_confidence",
        "disfluency_rate",
        "sentence_completion",
        "recovery_speed",
    ]:
        row = percentile_data.get(dimension, {})
        radar_labels.append(_format_dimension_label(dimension))
        user_scores.append(row.get("user_score") or 0)
        cohort_medians.append(row.get("cohort_median") or 0)

    radar_comparison_data = {
        "labels": radar_labels,
        "datasets": [
            {
                "label": "Your Scores",
                "data": user_scores,
                "borderColor": "#4F46E5",
                "backgroundColor": "rgba(79,70,229,0.15)",
                "pointBackgroundColor": "#4F46E5",
            },
            {
                "label": "Cohort Median",
                "data": cohort_medians,
                "borderColor": "#F59E0B",
                "backgroundColor": "rgba(245,158,11,0.10)",
                "pointBackgroundColor": "#F59E0B",
                "borderDash": [6, 4],
            },
        ],
        "has_data": True,
    }

    cohort_user_count = 0
    for key in ["pgi", "lexical_diversity"]:
        count_value = percentile_data.get(key, {}).get("cohort_user_count")
        if count_value:
            cohort_user_count = count_value
            break

    limited_data_message = None
    if cohort_user_count and cohort_user_count < 10:
        limited_data_message = (
            "Your cohort is small. Fewer than 10 users match your profile. "
            "Percentile data will become more accurate as PressureProof grows."
        )

    return render_template(
        "cohort/index.html",
        title="Cohort Benchmarking - PressureProof",
        cohort_label=_humanize_cohort_label(cohort_key),
        cohort_key=cohort_key,
        cohort_user_count=cohort_user_count,
        percentile_data=percentile_data,
        distribution_data=distribution_data,
        radar_comparison_data=radar_comparison_data,
        limited_data_message=limited_data_message,
        **_sidebar_payload(current_user.id),
    )
