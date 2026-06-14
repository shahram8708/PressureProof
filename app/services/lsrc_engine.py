import logging

from app.extensions import db
from app.models import Assessment, LsrcScore
from app.utils import nlp_helpers


logger = logging.getLogger(__name__)


def _safe_compute(calculation_fn, default_value, *args, **kwargs):
    try:
        return calculation_fn(*args, **kwargs)
    except Exception:
        logger.exception("LSRC calculation failed for %s", calculation_fn.__name__)
        return default_value


def _get_baseline_mattr(user_id):
    baseline_assessment = (
        Assessment.query.filter_by(
            user_id=user_id,
            assessment_type="baseline",
            status="completed",
        )
        .order_by(Assessment.created_at.asc())
        .first()
    )
    if baseline_assessment is None:
        return None

    baseline_prepared_score = (
        LsrcScore.query.filter_by(
            user_id=user_id,
            source_type="assessment",
            source_id=baseline_assessment.id,
            condition="prepared",
        )
        .order_by(LsrcScore.scored_at.asc())
        .first()
    )

    if baseline_prepared_score is None or baseline_prepared_score.lexical_diversity is None:
        return None

    lexical_score = float(baseline_prepared_score.lexical_diversity)
    if lexical_score <= 0:
        return None
    return lexical_score / 100.0


def compute_lsrc_scores(
    analysis_result: dict,
    user_id: int,
    source_type: str,
    source_id: int,
    condition: str,
) -> LsrcScore:
    transcript = (analysis_result or {}).get("transcript", "")
    word_timestamps = (analysis_result or {}).get("word_timestamps", [])
    audio_features = (analysis_result or {}).get("audio_features")

    baseline_mattr = _get_baseline_mattr(user_id)

    lexical_diversity = _safe_compute(
        nlp_helpers.compute_lexical_diversity,
        None,
        transcript,
        baseline_mattr,
    )
    syntactic_complexity = _safe_compute(
        nlp_helpers.compute_syntactic_complexity,
        None,
        transcript,
    )
    disfluency_rate = _safe_compute(
        nlp_helpers.compute_disfluency_rate,
        None,
        word_timestamps,
        transcript,
    )
    sentence_completion = _safe_compute(
        nlp_helpers.compute_sentence_completion,
        None,
        word_timestamps,
        transcript,
    )
    prosodic_confidence = _safe_compute(
        nlp_helpers.compute_prosodic_confidence,
        None,
        audio_features,
    )
    recovery_speed_tuple = _safe_compute(
        nlp_helpers.compute_recovery_speed,
        (None, None),
        word_timestamps,
    )

    recovery_speed_seconds = None
    recovery_speed_score = None
    if recovery_speed_tuple is not None:
        try:
            recovery_speed_seconds, recovery_speed_score = recovery_speed_tuple
        except (TypeError, ValueError):
            logger.exception("Recovery speed tuple had unexpected shape")

    score_record = LsrcScore(
        user_id=user_id,
        source_type=source_type,
        source_id=source_id,
        condition=condition,
        lexical_diversity=lexical_diversity,
        syntactic_complexity=syntactic_complexity,
        prosodic_confidence=prosodic_confidence,
        disfluency_rate=disfluency_rate,
        sentence_completion=sentence_completion,
        recovery_speed_seconds=recovery_speed_seconds,
        recovery_speed_score=recovery_speed_score,
    )

    db.session.add(score_record)
    db.session.commit()
    return score_record


def compute_lsrc_dimensions(*args, **kwargs):
    return compute_lsrc_scores(*args, **kwargs)
