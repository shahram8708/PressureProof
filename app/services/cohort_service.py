import logging
import math
from collections import defaultdict
from datetime import datetime

import numpy as np

from app.extensions import db
from app.models import CohortAggregate, LsrcScore, PgiRecord, User


logger = logging.getLogger(__name__)


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


def _estimate_percentile(aggregate_row, score_value):
    if aggregate_row is None or score_value is None:
        return None

    checkpoints = []
    for percentile, column in [
        (10.0, aggregate_row.percentile_10),
        (25.0, aggregate_row.percentile_25),
        (50.0, aggregate_row.percentile_50),
        (75.0, aggregate_row.percentile_75),
        (90.0, aggregate_row.percentile_90),
    ]:
        numeric = _safe_float(column)
        if numeric is not None:
            checkpoints.append((numeric, percentile))

    if not checkpoints:
        return None

    checkpoints.sort(key=lambda item: item[0])

    if len(checkpoints) == 1:
        base_value, base_pct = checkpoints[0]
        if base_value == 0:
            return round(base_pct, 2)
        return round(max(0.0, min(100.0, (score_value / base_value) * base_pct)), 2)

    first_value, first_pct = checkpoints[0]
    if score_value <= first_value:
        if first_value <= 0:
            return round(first_pct, 2)
        low_pct = max(0.0, first_pct * (score_value / first_value))
        return round(max(0.0, min(100.0, low_pct)), 2)

    for index in range(len(checkpoints) - 1):
        left_value, left_pct = checkpoints[index]
        right_value, right_pct = checkpoints[index + 1]
        if left_value <= score_value <= right_value:
            if right_value == left_value:
                return round(right_pct, 2)
            ratio = (score_value - left_value) / (right_value - left_value)
            return round(left_pct + ((right_pct - left_pct) * ratio), 2)

    last_value, last_pct = checkpoints[-1]
    if last_value >= 100:
        return round(last_pct, 2)
    high_ratio = (score_value - last_value) / max(1.0, (100.0 - last_value))
    estimated = last_pct + (100.0 - last_pct) * high_ratio
    return round(max(0.0, min(100.0, estimated)), 2)


def _latest_lsrc_scores(user_id):
    spontaneous = (
        LsrcScore.query.filter_by(user_id=user_id, condition="spontaneous")
        .order_by(LsrcScore.scored_at.desc())
        .first()
    )
    prepared = (
        LsrcScore.query.filter_by(user_id=user_id, condition="prepared")
        .order_by(LsrcScore.scored_at.desc())
        .first()
    )
    return spontaneous, prepared


def get_user_cohort_percentiles(user_id: int) -> dict:
    user = User.query.get(user_id)
    if user is None:
        return {"error": "user_not_found"}

    cohort_key = CohortAggregate.get_user_cohort_key(user)
    cohort_data = CohortAggregate.get_cohort_data(cohort_key)

    if not cohort_data:
        return {
            "cohort_key": cohort_key,
            "overall_percentile": None,
            "error": "cohort_data_unavailable",
        }

    spontaneous_score, prepared_score = _latest_lsrc_scores(user_id)
    latest_pgi = (
        PgiRecord.query.filter_by(user_id=user_id)
        .order_by(PgiRecord.week_start_date.desc())
        .first()
    )

    result = {"cohort_key": cohort_key}
    percentile_values = []

    for dimension, field in DIMENSION_FIELDS.items():
        score_value = None
        if spontaneous_score is not None:
            score_value = _safe_float(getattr(spontaneous_score, field, None))
        if score_value is None and prepared_score is not None:
            score_value = _safe_float(getattr(prepared_score, field, None))

        aggregate_row = cohort_data.get(dimension)
        percentile = _estimate_percentile(aggregate_row, score_value)
        if percentile is not None:
            percentile_values.append(percentile)

        result[dimension] = {
            "user_score": round(score_value, 2) if score_value is not None else None,
            "percentile": percentile,
            "cohort_median": (
                _safe_float(aggregate_row.percentile_50) if aggregate_row is not None else None
            ),
            "cohort_key": cohort_key,
            "cohort_user_count": aggregate_row.user_count if aggregate_row is not None else 0,
        }

    pgi_value = _safe_float(latest_pgi.pgi_score) if latest_pgi else None
    pgi_row = cohort_data.get("pgi")
    pgi_percentile = _estimate_percentile(pgi_row, pgi_value)
    if pgi_percentile is not None:
        percentile_values.append(pgi_percentile)

    result["pgi"] = {
        "user_score": round(pgi_value, 2) if pgi_value is not None else None,
        "percentile": pgi_percentile,
        "cohort_median": _safe_float(pgi_row.percentile_50) if pgi_row is not None else None,
        "cohort_key": cohort_key,
        "cohort_user_count": pgi_row.user_count if pgi_row is not None else 0,
    }

    result["overall_percentile"] = (
        round(sum(percentile_values) / len(percentile_values), 2)
        if percentile_values
        else None
    )
    return result


def _collect_user_metric_snapshot(user_id):
    spontaneous_score = (
        LsrcScore.query.filter_by(user_id=user_id, condition="spontaneous")
        .order_by(LsrcScore.scored_at.desc())
        .first()
    )
    latest_pgi = (
        PgiRecord.query.filter_by(user_id=user_id)
        .order_by(PgiRecord.week_start_date.desc())
        .first()
    )

    data = {}
    for dimension, field in DIMENSION_FIELDS.items():
        value = None
        if spontaneous_score is not None:
            value = _safe_float(getattr(spontaneous_score, field, None))
        if value is not None:
            data[dimension] = value

    pgi_value = _safe_float(latest_pgi.pgi_score) if latest_pgi else None
    if pgi_value is not None:
        data["pgi"] = pgi_value

    return data


def rebuild_cohort_aggregates():
    eligible_users = User.query.filter_by(email_verified=True, onboarding_complete=True).all()
    grouped = defaultdict(list)

    for user in eligible_users:
        cohort_key = CohortAggregate.get_user_cohort_key(user)
        grouped[cohort_key].append(user)

    updated_records = 0
    updated_cohort_keys = 0
    total_users_processed = 0

    for cohort_key, users in grouped.items():
        if len(users) < 3:
            continue

        metric_values = defaultdict(list)
        for user in users:
            snapshot = _collect_user_metric_snapshot(user.id)
            if snapshot:
                total_users_processed += 1
            for metric_name, metric_value in snapshot.items():
                metric_values[metric_name].append(metric_value)

        for metric_name in [
            "lexical_diversity",
            "syntactic_complexity",
            "prosodic_confidence",
            "disfluency_rate",
            "sentence_completion",
            "recovery_speed",
            "pgi",
        ]:
            scores = metric_values.get(metric_name, [])
            if len(scores) < 3:
                continue

            p10, p25, p50, p75, p90 = np.percentile(scores, [10, 25, 50, 75, 90])

            row = CohortAggregate.query.filter_by(cohort_key=cohort_key, dimension=metric_name).first()
            if row is None:
                row = CohortAggregate(cohort_key=cohort_key, dimension=metric_name)
                db.session.add(row)

            row.percentile_10 = round(float(p10), 2)
            row.percentile_25 = round(float(p25), 2)
            row.percentile_50 = round(float(p50), 2)
            row.percentile_75 = round(float(p75), 2)
            row.percentile_90 = round(float(p90), 2)
            row.user_count = len(users)
            row.last_updated = datetime.utcnow()

            updated_records += 1
            if updated_records % 50 == 0:
                db.session.commit()

        updated_cohort_keys += 1

    db.session.commit()
    logger.info(
        "Cohort rebuild complete. Updated cohort keys: %s, users processed: %s, records upserted: %s",
        updated_cohort_keys,
        total_users_processed,
        updated_records,
    )
    return {
        "updated_cohort_keys": updated_cohort_keys,
        "users_processed": total_users_processed,
        "records_upserted": updated_records,
    }


def get_cohort_distribution_data(cohort_key: str, dimension: str) -> dict:
    row = CohortAggregate.query.filter_by(cohort_key=cohort_key, dimension=dimension).first()

    labels = list(range(0, 101, 5))
    frequencies = [0.0 for _ in labels]
    percentile_map = {
        "10": None,
        "25": None,
        "50": None,
        "75": None,
        "90": None,
    }

    if row is not None:
        p25 = _safe_float(row.percentile_25)
        p50 = _safe_float(row.percentile_50)
        p75 = _safe_float(row.percentile_75)
        percentile_map = {
            "10": _safe_float(row.percentile_10),
            "25": p25,
            "50": p50,
            "75": p75,
            "90": _safe_float(row.percentile_90),
        }

        mean = p50 if p50 is not None else 50.0
        if p75 is not None and p25 is not None and p75 > p25:
            sigma = (p75 - p25) / 1.35
        else:
            sigma = 12.0
        sigma = max(2.5, sigma)

        pdf_values = []
        for x in labels:
            exponent = -0.5 * (((x - mean) / sigma) ** 2)
            pdf = (1.0 / (sigma * math.sqrt(2 * math.pi))) * math.exp(exponent)
            pdf_values.append(pdf)

        max_pdf = max(pdf_values) if pdf_values else 1.0
        if max_pdf <= 0:
            max_pdf = 1.0
        frequencies = [round((value / max_pdf) * 100.0, 2) for value in pdf_values]

    return {
        "labels": labels,
        "frequencies": frequencies,
        "percentiles": percentile_map,
        "cohort_key": cohort_key,
        "dimension": dimension,
    }


def fetch_cohort_aggregates(cohort_key):
    return CohortAggregate.get_cohort_data(cohort_key)
