from datetime import datetime

from app.extensions import db
from app.models import FailureMode, LsrcScore


MODE_MAPPING = {
    "lexical_diversity": {
        "mode_code": "lexical_attrition_temporal",
        "mode_label": "Vocabulary narrows under pressure",
        "mode_description": "When stress hits, your vocabulary range drops significantly - you reach for simpler, safer words instead of the precise ones you know. This is the most common pattern in intermediate-to-advanced speakers and it is highly trainable.",
    },
    "prosodic_confidence": {
        "mode_code": "prosodic_collapse_social",
        "mode_label": "Voice confidence drops under social pressure",
        "mode_description": "Your vocal delivery - pitch stability, speaking pace, and tone - shows the biggest drop when you are under pressure. You sound less confident than you are, which affects how listeners perceive your competence.",
    },
    "disfluency_rate": {
        "mode_code": "disfluency_surge_stress",
        "mode_label": "Filler words surge under cognitive load",
        "mode_description": "Under pressure your use of filler words and mid-sentence pauses increases sharply. This signals to listeners that you are struggling even when the content of what you are saying is strong.",
    },
    "sentence_completion": {
        "mode_code": "sentence_fragmentation_distractor",
        "mode_label": "Sentences break down under divided attention",
        "mode_description": "When your attention is divided - by unexpected questions, emotional activation, or time pressure - you start sentences and abandon them before completing the thought. Recovery is slow.",
    },
    "syntactic_complexity": {
        "mode_code": "syntactic_simplification_social",
        "mode_label": "Grammar simplifies under pressure",
        "mode_description": "Under stress your sentence structures simplify significantly - complex clauses and embedded structures collapse into short, simple sentences. This makes you sound less articulate than your actual language knowledge supports.",
    },
    "recovery_speed": {
        "mode_code": "recovery_delay_temporal",
        "mode_label": "Recovery from breakdowns is slow",
        "mode_description": "When your English breaks down - a lost word, an incomplete sentence, a long pause - your recovery back to fluent output takes significantly longer under pressure than in calm conditions. Training recovery pathways directly will help.",
    },
}


def _mean_score(records, attribute):
    values = []
    for record in records:
        value = getattr(record, attribute, None)
        if value is not None:
            values.append(float(value))
    if not values:
        return None
    return sum(values) / len(values)


def _upsert_failure_mode(user_id, payload):
    failure_mode = FailureMode.query.filter_by(user_id=user_id).first()
    if failure_mode is None:
        failure_mode = FailureMode(user_id=user_id, **payload)
        db.session.add(failure_mode)
    else:
        for key, value in payload.items():
            setattr(failure_mode, key, value)
    db.session.commit()
    return failure_mode


def detect_primary_failure_mode(user_id: int) -> FailureMode:
    all_scores = LsrcScore.query.filter_by(user_id=user_id).all()
    prepared_scores = [score for score in all_scores if score.condition == "prepared"]
    spontaneous_scores = [score for score in all_scores if score.condition == "spontaneous"]

    if len(prepared_scores) < 1 or len(spontaneous_scores) < 1:
        return _upsert_failure_mode(
            user_id,
            {
                "mode_code": "insufficient_data",
                "mode_label": "Assessing your profile",
                "mode_description": "We need a few more sessions before we can identify your primary stress pattern. Keep going.",
                "primary_dimension": "lexical_diversity",
                "secondary_dimension": None,
                "confidence_score": 0.0,
                "last_updated": datetime.utcnow(),
                "evidence_session_count": 0,
            },
        )

    dimension_attribute_map = {
        "lexical_diversity": "lexical_diversity",
        "syntactic_complexity": "syntactic_complexity",
        "prosodic_confidence": "prosodic_confidence",
        "disfluency_rate": "disfluency_rate",
        "sentence_completion": "sentence_completion",
        "recovery_speed": "recovery_speed_score",
    }

    gaps = {}
    for dimension, attribute in dimension_attribute_map.items():
        prepared_mean = _mean_score(prepared_scores, attribute)
        spontaneous_mean = _mean_score(spontaneous_scores, attribute)

        if prepared_mean is None or spontaneous_mean is None:
            gaps[dimension] = 0.0
        else:
            gaps[dimension] = prepared_mean - spontaneous_mean

    ranked_dimensions = sorted(gaps.items(), key=lambda item: item[1], reverse=True)
    primary_dimension = ranked_dimensions[0][0]
    secondary_dimension = ranked_dimensions[1][0] if len(ranked_dimensions) > 1 else None

    mapping = MODE_MAPPING[primary_dimension]
    evidence_session_count = min(len(prepared_scores), len(spontaneous_scores))
    confidence_score = min(1.0, evidence_session_count / 10.0)

    return _upsert_failure_mode(
        user_id,
        {
            "mode_code": mapping["mode_code"],
            "mode_label": mapping["mode_label"],
            "mode_description": mapping["mode_description"],
            "primary_dimension": primary_dimension,
            "secondary_dimension": secondary_dimension,
            "confidence_score": confidence_score,
            "last_updated": datetime.utcnow(),
            "evidence_session_count": evidence_session_count,
        },
    )


def detect_failure_modes(user_id, *args, **kwargs):
    return detect_primary_failure_mode(user_id)
