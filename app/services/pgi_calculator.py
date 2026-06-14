from datetime import date, datetime, time, timedelta
import math
import re
from collections import Counter

import numpy as np

from app.extensions import db
from app.models import Assessment, LsrcScore, PgiRecord


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _week_bounds(week_start):
    week_start_datetime = datetime.combine(week_start, time.min)
    week_end_datetime = week_start_datetime + timedelta(days=7)
    return week_start_datetime, week_end_datetime


def _to_composite_values(score_records):
    values = []
    for score in score_records:
        composite = _safe_float(getattr(score, "composite_score", None))
        if composite is not None:
            values.append(composite)
    return values


def _mean(values):
    valid_values = [value for value in values if value is not None]
    if not valid_values:
        return None
    return sum(valid_values) / len(valid_values)


def _extract_topic_text(score):
    if score.source_type == "assessment":
        assessment = Assessment.query.get(score.source_id)
        if assessment is None:
            return None
        if score.condition == "prepared":
            return (
                assessment.topic_vector_prepared
                or assessment.transcript_prepared
                or ""
            )
        return (
            assessment.topic_vector_spontaneous
            or assessment.transcript_spontaneous
            or ""
        )

    if score.source_type == "session":
        try:
            from app.models import TrainingSession

            training_session = TrainingSession.query.get(score.source_id)
            if training_session is None:
                return None
            for attribute in [
                "topic_vector",
                "topic",
                "prompt_text",
                "prompt",
                "transcript",
                "notes",
            ]:
                candidate = getattr(training_session, attribute, None)
                if candidate:
                    return str(candidate)
        except Exception:
            return None

    if score.source_type in {"snapspeak", "snapspeak_capture"}:
        try:
            from app.models import SnapSpeakRecord

            capture = SnapSpeakRecord.query.get(score.source_id)
            if capture is None:
                return None
            return getattr(capture, "prompt", None) or getattr(capture, "transcript", None)
        except Exception:
            return None

    return None


def _topic_weights(text):
    tokens = re.findall(r"[a-z0-9']+", str(text or "").lower())
    if not tokens:
        return {}

    terms = list(tokens)
    terms.extend(f"{tokens[index]} {tokens[index + 1]}" for index in range(len(tokens) - 1))

    counts = Counter(terms)
    total = float(sum(counts.values()))
    if total == 0:
        return {}

    return {token: (count / total) for token, count in counts.items()}


def _token_cosine_similarity(left_weights, right_weights):
    if not left_weights or not right_weights:
        return 0.0

    shared_tokens = set(left_weights).intersection(right_weights)
    dot_product = sum(left_weights[token] * right_weights[token] for token in shared_tokens)
    left_norm = math.sqrt(sum(value * value for value in left_weights.values()))
    right_norm = math.sqrt(sum(value * value for value in right_weights.values()))

    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0

    return float(dot_product / (left_norm * right_norm))


def _match_topic_sets(prepared_scores, spontaneous_scores):
    used_spontaneous_ids = set()
    matched_pairs = []

    for prepared in prepared_scores:
        prepared_topic = _extract_topic_text(prepared)
        if not prepared_topic:
            continue
        prepared_weights = _topic_weights(prepared_topic)
        if not prepared_weights:
            continue

        best_candidate = None
        best_similarity = 0.0

        for spontaneous in spontaneous_scores:
            if spontaneous.id in used_spontaneous_ids:
                continue

            spontaneous_topic = _extract_topic_text(spontaneous)
            if not spontaneous_topic:
                continue

            spontaneous_weights = _topic_weights(spontaneous_topic)
            similarity = _token_cosine_similarity(prepared_weights, spontaneous_weights)

            if similarity > best_similarity:
                best_similarity = similarity
                best_candidate = spontaneous

        if best_candidate is not None and best_similarity >= 0.4:
            matched_pairs.append((prepared, best_candidate))
            used_spontaneous_ids.add(best_candidate.id)

    if not matched_pairs:
        return prepared_scores, spontaneous_scores, False

    matched_prepared = [pair[0] for pair in matched_pairs]
    matched_spontaneous = [pair[1] for pair in matched_pairs]
    return matched_prepared, matched_spontaneous, True


def _count_source_records(records, source_type_values):
    source_set = set(source_type_values)
    return len([record for record in records if getattr(record, "source_type", None) in source_set])


def compute_weekly_pgi(user_id: int, week_start: date = None) -> PgiRecord:
    if week_start is None:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

    week_start_datetime, week_end_datetime = _week_bounds(week_start)

    week_scores = (
        LsrcScore.query.filter(
            LsrcScore.user_id == user_id,
            LsrcScore.scored_at >= week_start_datetime,
            LsrcScore.scored_at < week_end_datetime,
        )
        .order_by(LsrcScore.scored_at.asc())
        .all()
    )

    prepared_scores = [score for score in week_scores if score.condition == "prepared"]
    spontaneous_scores = [score for score in week_scores if score.condition == "spontaneous"]

    existing_record = PgiRecord.query.filter_by(
        user_id=user_id,
        week_start_date=week_start,
    ).first()

    if not prepared_scores or not spontaneous_scores:
        if existing_record is not None:
            return existing_record

        fallback_record = PgiRecord(
            user_id=user_id,
            week_start_date=week_start,
            pgi_score=None,
            prepared_composite=None,
            spontaneous_composite=None,
            sessions_count=0,
            snapspeak_count=0,
            topic_matched=False,
            calculated_at=datetime.utcnow(),
        )
        db.session.add(fallback_record)
        db.session.commit()
        return fallback_record

    matched_prepared, matched_spontaneous, topic_matched = _match_topic_sets(
        prepared_scores,
        spontaneous_scores,
    )

    prepared_values = _to_composite_values(matched_prepared)
    spontaneous_values = _to_composite_values(matched_spontaneous)

    prepared_composite = _mean(prepared_values)
    spontaneous_composite = _mean(spontaneous_values)

    pgi_score = None
    if prepared_composite not in (None, 0.0) and spontaneous_composite is not None:
        raw_gap = ((prepared_composite - spontaneous_composite) / prepared_composite) * 100.0
        pgi_score = round(max(0.0, min(100.0, raw_gap)), 2)

    sessions_count = _count_source_records(matched_prepared, {"session", "training_session"})
    snapspeak_count = _count_source_records(matched_spontaneous, {"snapspeak", "snapspeak_capture"})

    record = existing_record
    if record is None:
        record = PgiRecord(user_id=user_id, week_start_date=week_start)
        db.session.add(record)

    record.pgi_score = pgi_score
    record.prepared_composite = (
        round(prepared_composite, 2) if prepared_composite is not None else None
    )
    record.spontaneous_composite = (
        round(spontaneous_composite, 2) if spontaneous_composite is not None else None
    )
    record.sessions_count = sessions_count
    record.snapspeak_count = snapspeak_count
    record.topic_matched = topic_matched
    record.calculated_at = datetime.utcnow()

    db.session.commit()
    return record


def _week_label(week_start_date):
    if week_start_date is None:
        return ""
    week_in_month = ((week_start_date.day - 1) // 7) + 1
    return f"{week_start_date.strftime('%b')} W{week_in_month}"


def get_pgi_trend_data(user_id: int, weeks: int = 12) -> list:
    window = max(1, int(weeks or 12))
    current_week_start = date.today() - timedelta(days=date.today().weekday())
    first_week_start = current_week_start - timedelta(days=(window - 1) * 7)

    existing_records = PgiRecord.get_user_trend(user_id, window)
    records_by_week = {record.week_start_date: record for record in existing_records}

    trend_data = []
    for offset in range(window):
        week_start = first_week_start + timedelta(days=offset * 7)
        record = records_by_week.get(week_start)

        trend_data.append(
            {
                "week_label": _week_label(week_start),
                "week_start": week_start.strftime("%Y-%m-%d"),
                "pgi_score": _safe_float(record.pgi_score) if record else None,
                "prepared_composite": _safe_float(record.prepared_composite) if record else None,
                "spontaneous_composite": (
                    _safe_float(record.spontaneous_composite) if record else None
                ),
            }
        )

    return trend_data


def _weeks_to_target(slope, intercept, current_index, target_value):
    if slope >= 0:
        return None

    target_index = (target_value - intercept) / slope
    remaining = target_index - current_index
    if remaining <= 0:
        return 0
    return int(math.ceil(remaining))


def compute_pgi_projection(trend_data: list) -> dict:
    non_null_points = [
        (index, float(point["pgi_score"]))
        for index, point in enumerate(trend_data or [])
        if point.get("pgi_score") is not None
    ]

    if len(non_null_points) < 2:
        return {"projection_available": False}

    recent_points = non_null_points[-4:]
    x_indices = np.array([point[0] for point in recent_points], dtype=float)
    pgi_values = np.array([point[1] for point in recent_points], dtype=float)

    slope, intercept = np.polyfit(x_indices, pgi_values, 1)
    slope = float(slope)
    intercept = float(intercept)

    if slope < -0.3:
        trend_direction = "improving"
    elif slope > 0.3:
        trend_direction = "declining"
    else:
        trend_direction = "stable"

    current_index = float(recent_points[-1][0])
    weeks_to_20 = _weeks_to_target(slope, intercept, current_index, 20.0)
    weeks_to_10 = _weeks_to_target(slope, intercept, current_index, 10.0)

    return {
        "projection_available": True,
        "weeks_to_20": weeks_to_20,
        "weeks_to_10": weeks_to_10,
        "slope": round(slope, 4),
        "trend_direction": trend_direction,
    }


def calculate_preparation_gap_index(lsrc_snapshot):
    prepared_composite = _safe_float((lsrc_snapshot or {}).get("prepared_composite"))
    spontaneous_composite = _safe_float((lsrc_snapshot or {}).get("spontaneous_composite"))
    if prepared_composite in (None, 0.0) or spontaneous_composite is None:
        return None
    raw_gap = ((prepared_composite - spontaneous_composite) / prepared_composite) * 100.0
    return round(max(0.0, min(100.0, raw_gap)), 2)
