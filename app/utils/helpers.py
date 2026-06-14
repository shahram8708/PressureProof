from datetime import datetime
import random
from typing import TYPE_CHECKING

from app.models import PgiRecord, User

if TYPE_CHECKING:
    from app.models.lsrc_score import LsrcScore


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_utc_iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    raise TypeError("to_utc_iso expects a datetime or None.")


def compute_pgi_estimate(prepared_score: "LsrcScore", spontaneous_score: "LsrcScore") -> float:
    dimensions = [
        "lexical_diversity",
        "syntactic_complexity",
        "prosodic_confidence",
        "disfluency_rate",
        "sentence_completion",
        "recovery_speed_score",
    ]

    prepared_values = []
    spontaneous_values = []

    for dimension in dimensions:
        prepared_value = _safe_float(getattr(prepared_score, dimension, None))
        spontaneous_value = _safe_float(getattr(spontaneous_score, dimension, None))
        if prepared_value is not None:
            prepared_values.append(prepared_value)
        if spontaneous_value is not None:
            spontaneous_values.append(spontaneous_value)

    if prepared_values and spontaneous_values:
        prepared_composite = sum(prepared_values) / len(prepared_values)
        spontaneous_composite = sum(spontaneous_values) / len(spontaneous_values)
    else:
        prepared_composite = _safe_float(getattr(prepared_score, "composite_score", None))
        spontaneous_composite = _safe_float(getattr(spontaneous_score, "composite_score", None))

    if prepared_composite is None or spontaneous_composite is None:
        return None

    if prepared_composite <= 0:
        return None

    pgi_value = ((prepared_composite - spontaneous_composite) / prepared_composite) * 100.0
    return max(0.0, min(100.0, round(pgi_value, 2)))


def generate_profile_narrative(
    prepared_scores: "LsrcScore", spontaneous_scores: "LsrcScore"
) -> str:
    if prepared_scores is None or spontaneous_scores is None:
        return (
            "Your baseline profile is still being assembled. As more speech samples arrive, "
            "we will map exactly how pressure changes your English and where to train first."
        )

    dimension_labels = {
        "lexical_diversity": "vocabulary range",
        "syntactic_complexity": "sentence complexity",
        "prosodic_confidence": "vocal confidence",
        "disfluency_rate": "fluency control",
        "sentence_completion": "sentence completion",
        "recovery_speed_score": "recovery stability",
    }

    drops = []
    for dimension, label in dimension_labels.items():
        prepared_value = _safe_float(getattr(prepared_scores, dimension, None))
        spontaneous_value = _safe_float(getattr(spontaneous_scores, dimension, None))
        if prepared_value is None or spontaneous_value is None or prepared_value <= 0:
            continue
        drop_pct = ((prepared_value - spontaneous_value) / prepared_value) * 100.0
        drops.append((dimension, label, drop_pct))

    largest_drop_text = ""
    if drops:
        largest = max(drops, key=lambda item: item[2])
        largest_drop_text = (
            f"your {largest[1]} is the first thing to narrow, with an estimated "
            f"{max(0.0, largest[2]):.1f}% drop between prepared and spontaneous speech"
        )

    sentence_completion = _safe_float(getattr(spontaneous_scores, "sentence_completion", None))
    recovery_seconds = _safe_float(getattr(spontaneous_scores, "recovery_speed_seconds", None))

    completion_text = ""
    if sentence_completion is not None:
        completion_text = f"Your sentence completion stays around {sentence_completion:.1f}%"

    recovery_text = ""
    if recovery_seconds is not None:
        recovery_text = (
            f"when a breakdown starts, recovery takes about {recovery_seconds:.1f} seconds on average"
        )

    core_parts = [
        "Your English under pressure shows a clear pattern",
        largest_drop_text,
        completion_text,
        recovery_text,
    ]
    core_parts = [part for part in core_parts if part]

    if not core_parts:
        return (
            "Your English under pressure profile is now active. This is your starting point, "
            "not a judgment, and every metric can improve with consistent training."
        )

    return (
        ". ".join(core_parts)
        + ". This is your starting point, not a judgment, and every one of these numbers is trainable."
    )


def get_prompt_for_context(professional_context: str, prompt_type: str) -> str:
    prompt_bank = {
        "IT Services": {
            "prepared": [
                "Describe a recent technical challenge you solved at work and walk through your approach.",
                "Explain to a non-technical client why a software deployment needs to be delayed.",
                "Walk me through what your typical workday looks like.",
                "Describe the most complex project you have worked on and your role in it.",
                "Explain what your team does to a new colleague who has just joined the company.",
                "Describe a production incident you handled and the communication decisions you made.",
                "Explain how you prioritize tasks when multiple teams need support at the same time.",
                "Describe how you would present project risk to a client who expects unrealistic timelines.",
            ],
            "spontaneous": [
                "Describe a moment when you had to explain something technical to someone impatient or unhappy.",
                "Tell me about a time when your English let you down in a professional situation.",
                "Describe what happened in the most stressful meeting or call you have had in the past 6 months.",
                "Talk about a moment when you forgot a key word in an important technical discussion.",
                "Describe a call where you felt your confidence drop and what happened next.",
            ],
        },
        "BPO or Call Centre": {
            "prepared": [
                "Describe your process for handling an upset customer from greeting to resolution.",
                "Explain how you balance call quality and handle time in a busy shift.",
                "Walk me through how you escalate a case when first-line troubleshooting fails.",
                "Describe the product or service you support as if you are training a new agent.",
                "Explain how you keep your tone professional during difficult calls.",
                "Describe your best call and why it went well.",
                "Explain the key metrics your team is measured on and how you improve them.",
                "Describe a time when active listening helped you solve a customer issue quickly.",
            ],
            "spontaneous": [
                "Describe a call where the customer interrupted you repeatedly and how you responded.",
                "Tell me about a time you lost your flow while speaking and had to recover quickly.",
                "Describe your most stressful escalation and what made it hard.",
                "Talk about a moment when you misunderstood a customer because of accent or speed.",
                "Describe a shift where fatigue affected your speaking confidence.",
            ],
        },
        "Healthcare": {
            "prepared": [
                "Describe a typical interaction with a patient and how you build trust quickly.",
                "Explain a treatment or procedure in simple language for a worried family member.",
                "Walk me through how you hand over a patient case to another healthcare professional.",
                "Describe a time when clear communication prevented a clinical error.",
                "Explain your role in your healthcare team and what decisions you make daily.",
                "Describe how you communicate with patients from different language backgrounds.",
                "Explain how you prioritize tasks during a high workload shift.",
                "Describe how you discuss follow-up instructions so patients can remember them clearly.",
            ],
            "spontaneous": [
                "Describe a high-pressure clinical moment when you had to speak clearly despite stress.",
                "Tell me about a time when you struggled to find the right English words with a patient.",
                "Describe a handover where you felt rushed and worried about clarity.",
                "Talk about a difficult conversation with a patient's family and what happened.",
                "Describe a situation where emotional pressure affected your speaking pace or confidence.",
            ],
        },
        "Immigration Applicant": {
            "prepared": [
                "Describe why you chose your destination country and what opportunities you are seeking.",
                "Explain your education and work history in a clear timeline.",
                "Walk me through your preparation plan for language and settlement.",
                "Describe your current profession and how your skills will transfer abroad.",
                "Explain your long-term goals after immigration in practical terms.",
                "Describe a challenge you faced in your application process and how you solved it.",
                "Explain your financial and professional readiness for relocation.",
                "Describe how you plan to adapt to a new workplace culture in English.",
            ],
            "spontaneous": [
                "Describe the most stressful part of your immigration journey so far.",
                "Tell me about a time you felt judged for your English and how it affected you.",
                "Describe a visa or interview moment where you felt pressure while speaking.",
                "Talk about a recent conversation where anxiety made your English less fluent.",
                "Describe your biggest fear about using English in your new country.",
            ],
        },
        "Other": {
            "prepared": [
                "Describe your current role and the kind of conversations you handle most often.",
                "Explain a recent work challenge and how you communicated through it.",
                "Walk me through a normal day in your professional life.",
                "Describe a project or task you are proud of and why it mattered.",
                "Explain your work to someone outside your field in simple language.",
                "Describe how you prepare before an important meeting or conversation.",
                "Explain a decision you made at work and how you communicated it to others.",
                "Describe how English impacts your confidence in professional settings.",
            ],
            "spontaneous": [
                "Describe a recent moment when speaking English felt stressful.",
                "Tell me about a conversation where you felt pressure and lost your flow.",
                "Describe a time when you paused too much because you were searching for words.",
                "Talk about a situation where you wanted to sound confident but felt tense.",
                "Describe a difficult interaction where you wished your English came out more clearly.",
            ],
        },
    }

    context_key = professional_context if professional_context in prompt_bank else "Other"
    type_key = prompt_type if prompt_type in ("prepared", "spontaneous") else "prepared"

    prompts = prompt_bank[context_key][type_key]
    return random.choice(prompts)


DIMENSION_LABELS = {
    "lexical_diversity": "vocabulary range",
    "syntactic_complexity": "sentence structure",
    "prosodic_confidence": "vocal confidence",
    "disfluency_rate": "fluency control",
    "sentence_completion": "sentence completion",
    "recovery_speed": "recovery speed",
}


def get_sidebar_context(user_id: int) -> dict:
    user = User.query.get(user_id)
    latest_two_records = (
        PgiRecord.query.filter_by(user_id=user_id)
        .order_by(PgiRecord.week_start_date.desc())
        .limit(2)
        .all()
    )

    current_pgi = None
    pgi_direction = "insufficient_data"
    if latest_two_records:
        current_pgi = _safe_float(latest_two_records[0].pgi_score)

    if len(latest_two_records) >= 2:
        latest = _safe_float(latest_two_records[0].pgi_score)
        previous = _safe_float(latest_two_records[1].pgi_score)
        if latest is not None and previous is not None:
            if latest < previous:
                pgi_direction = "improving"
            elif latest > previous:
                pgi_direction = "declining"
            else:
                pgi_direction = "stable"

    trial_days_remaining = None
    if user and user.trial_ends_at and user.trial_ends_at > datetime.utcnow():
        trial_days_remaining = max(0, (user.trial_ends_at - datetime.utcnow()).days)

    return {
        "current_pgi": current_pgi,
        "pgi_direction": pgi_direction,
        "subscription_tier": user.subscription_tier if user else "free",
        "trial_days_remaining": trial_days_remaining,
    }


def generate_dimension_narrative(
    dimension: str,
    prepared_score: float,
    spontaneous_score: float,
    prior_prepared: float = None,
    prior_spontaneous: float = None,
) -> str:
    prepared_value = _safe_float(prepared_score)
    spontaneous_value = _safe_float(spontaneous_score)
    prior_prepared_value = _safe_float(prior_prepared)
    prior_spontaneous_value = _safe_float(prior_spontaneous)

    if prepared_value is None and spontaneous_value is None:
        return "No measurable data for this dimension this week yet."

    if dimension == "recovery_speed":
        if prepared_value is None or spontaneous_value is None:
            return "Recovery timing data is still incomplete for this week."

        delay = spontaneous_value - prepared_value
        if delay >= 0:
            sentence_one = (
                f"You recover in {prepared_value:.1f}s in prepared conditions and {spontaneous_value:.1f}s under pressure, adding {delay:.1f}s under load."
            )
        else:
            sentence_one = (
                f"You recover in {prepared_value:.1f}s in prepared conditions and {spontaneous_value:.1f}s under pressure, showing faster recovery in spontaneous speaking this week."
            )

        if prior_prepared_value is None or prior_spontaneous_value is None:
            return sentence_one

        prior_delay = prior_spontaneous_value - prior_prepared_value
        if delay < prior_delay - 0.3:
            trend_sentence = "The recovery gap is narrowing compared with last week."
        elif delay > prior_delay + 0.3:
            trend_sentence = "The recovery gap widened versus last week, so a recovery focused drill is timely."
        else:
            trend_sentence = "The recovery gap is steady compared with last week."
        return f"{sentence_one} {trend_sentence}"

    label = DIMENSION_LABELS.get(dimension, dimension.replace("_", " "))
    if prepared_value is None or spontaneous_value is None:
        if prepared_value is not None:
            return (
                f"Your {label} score is {prepared_value:.0f} in prepared speaking, but there is not enough spontaneous data to measure a weekly gap."
            )
        return (
            f"Your spontaneous {label} score is {spontaneous_value:.0f}, but we still need prepared data to compute the weekly gap."
        )

    gap = prepared_value - spontaneous_value
    sentence_one = (
        f"Your {label} score is {prepared_value:.0f} in prepared conditions and {spontaneous_value:.0f} under pressure, a {abs(gap):.0f} point gap."
    )

    if prior_prepared_value is None or prior_spontaneous_value is None:
        return sentence_one

    prior_gap = prior_prepared_value - prior_spontaneous_value
    if gap < prior_gap - 1.0:
        trend_sentence = "This gap is shrinking versus last week."
    elif gap > prior_gap + 1.0:
        trend_sentence = "This gap is wider than last week and needs targeted practice."
    else:
        trend_sentence = "This gap is stable relative to last week."

    return f"{sentence_one} {trend_sentence}"


def generate_focus_recommendation(dimension: str, gap: float) -> str:
    gap_value = _safe_float(gap) or 0.0
    recommendation_map = {
        "lexical_diversity": "Vocabulary Pressure",
        "syntactic_complexity": "Distractor Challenge",
        "prosodic_confidence": "Prosodic Drill",
        "disfluency_rate": "Prosodic Drill",
        "sentence_completion": "Distractor Challenge",
        "recovery_speed": "Recovery Focus",
    }
    label_map = {
        "lexical_diversity": "lexical diversity",
        "syntactic_complexity": "syntactic complexity",
        "prosodic_confidence": "prosodic confidence",
        "disfluency_rate": "disfluency control",
        "sentence_completion": "sentence completion",
        "recovery_speed": "recovery speed",
    }

    session_label = recommendation_map.get(dimension, "Vocabulary Pressure")
    dimension_label = label_map.get(dimension, dimension.replace("_", " "))
    return (
        f"Your {dimension_label} gap is {gap_value:.1f} points, so target this with a {session_label} session today."
    )


def get_week_label(week_start_date) -> str:
    if week_start_date is None:
        return ""

    short_label = f"{week_start_date.strftime('%b')} W{((week_start_date.day - 1) // 7) + 1}"
    full_label = f"{week_start_date.day} {week_start_date.strftime('%b')}"
    return short_label if len(short_label) <= len(full_label) else full_label


def get_session_type_display_name(session_type: str) -> str:
    mapping = {
        "vocabulary_pressure": "Vocabulary Pressure Session",
        "distractor_challenge": "Distractor Challenge Session",
        "prosodic_drill": "Prosodic Drill Session",
        "recovery_focus": "Recovery Focus Session",
        "baseline_measurement": "Baseline Measurement Session",
    }
    return mapping.get(session_type, "Training Session")


def get_injection_type_display_name(injection_type: str) -> str:
    mapping = {
        "temporal": "countdown timer",
        "distractor": "dot-counting distractor",
        "interlocutor": "listener impatience cue",
        "topic_pivot": "topic pivot",
        "none": "no injection",
    }
    return mapping.get(injection_type, "no injection")


def _pick_primary_score(scores):
    if not scores:
        return None

    for score in scores:
        if getattr(score, "condition", None) == "prepared":
            return score

    return scores[0]


def _format_score(value, display_type="score"):
    numeric_value = _safe_float(value)
    if numeric_value is None:
        return "n/a"
    if display_type == "seconds":
        return f"{numeric_value:.1f}s"
    return f"{numeric_value:.0f}"


def generate_session_insight(session, lsrc_scores: list, baseline_scores: list, injection_events: list) -> dict:
    session_score = _pick_primary_score(lsrc_scores or [])
    baseline_score = _pick_primary_score(baseline_scores or [])

    if session_score is None or baseline_score is None:
        return {
            "injection_analysis": (
                "This session has not generated enough comparable LSRC data yet for an injection-moment analysis."
            ),
            "key_insight": (
                "Your session has been recorded successfully. As more comparable baseline data is available, the summary will include a sharper numerical insight on how pressure changed your delivery."
            ),
        }

    dimensions = [
        {
            "key": "lexical_diversity",
            "label": "lexical diversity",
            "field": "lexical_diversity",
            "display": "score",
            "higher_is_better": True,
        },
        {
            "key": "syntactic_complexity",
            "label": "syntactic complexity",
            "field": "syntactic_complexity",
            "display": "score",
            "higher_is_better": True,
        },
        {
            "key": "prosodic_confidence",
            "label": "prosodic confidence",
            "field": "prosodic_confidence",
            "display": "score",
            "higher_is_better": True,
        },
        {
            "key": "disfluency_rate",
            "label": "disfluency control",
            "field": "disfluency_rate",
            "display": "score",
            "higher_is_better": True,
        },
        {
            "key": "sentence_completion",
            "label": "sentence completion",
            "field": "sentence_completion",
            "display": "score",
            "higher_is_better": True,
        },
        {
            "key": "recovery_speed",
            "label": "recovery speed",
            "field": "recovery_speed_seconds",
            "display": "seconds",
            "higher_is_better": False,
        },
    ]

    injection_second = _safe_float(getattr(session, "injection_timestamp_seconds", None), default=0.0)
    injection_type = get_injection_type_display_name(getattr(session, "stress_injection_type", "none"))
    if injection_events:
        first_event = injection_events[0]
        injection_second = _safe_float(getattr(first_event, "fired_at_seconds", None), default=injection_second)
        injection_type = get_injection_type_display_name(
            getattr(first_event, "injection_type", getattr(session, "stress_injection_type", "none"))
        )

    comparison_rows = []
    for dimension in dimensions:
        session_value = _safe_float(getattr(session_score, dimension["field"], None))
        baseline_value = _safe_float(getattr(baseline_score, dimension["field"], None))
        if session_value is None or baseline_value is None:
            continue

        if dimension["higher_is_better"]:
            signed_change = session_value - baseline_value
            deterioration = baseline_value - session_value
        else:
            signed_change = baseline_value - session_value
            deterioration = session_value - baseline_value

        comparison_rows.append(
            {
                "dimension": dimension,
                "session_value": session_value,
                "baseline_value": baseline_value,
                "signed_change": signed_change,
                "deterioration": deterioration,
            }
        )

    if not comparison_rows:
        return {
            "injection_analysis": (
                f"The {injection_type} was scheduled at second {int(round(injection_second))}. Comparable baseline values were unavailable for a numeric post-injection interpretation."
            ),
            "key_insight": (
                "This session still contributes to your progress profile. Complete one more calibrated session to unlock clearer baseline to session trend interpretation."
            ),
        }

    largest_deterioration = max(comparison_rows, key=lambda row: row["deterioration"])
    dominant_dimension = largest_deterioration["dimension"]

    if largest_deterioration["deterioration"] > 0.0:
        if dominant_dimension["display"] == "seconds":
            injection_analysis = (
                f"The {injection_type} injection fired at second {int(round(injection_second))}. "
                f"Your {dominant_dimension['label']} was {largest_deterioration['session_value']:.1f}s compared with your baseline {largest_deterioration['baseline_value']:.1f}s, "
                f"a {largest_deterioration['deterioration']:.1f}s slowdown, which is consistent with delayed recovery in the 15 seconds after injection pressure."
            )
        else:
            injection_analysis = (
                f"The {injection_type} injection fired at second {int(round(injection_second))}. "
                f"In this session, your {dominant_dimension['label']} score was {largest_deterioration['session_value']:.0f} compared with your baseline {largest_deterioration['baseline_value']:.0f}, "
                f"a {largest_deterioration['deterioration']:.0f}-point gap that aligns with pressure disruption in the 15 seconds after the injection moment."
            )
    else:
        injection_analysis = (
            f"The {injection_type} injection fired at second {int(round(injection_second))}. "
            f"Your session stayed broadly stable against baseline across measured dimensions through the 15-second post-injection window, suggesting stronger control under this stress pattern."
        )

    most_notable_change = max(comparison_rows, key=lambda row: abs(row["signed_change"]))
    notable_dimension = most_notable_change["dimension"]
    direction_word = "improved" if most_notable_change["signed_change"] > 0 else "declined"

    if notable_dimension["display"] == "seconds":
        key_insight = (
            f"Your most notable shift was in {notable_dimension['label']}: {most_notable_change['baseline_value']:.1f}s at baseline versus {most_notable_change['session_value']:.1f}s in this session. "
            f"That means your recovery profile {direction_word} by {abs(most_notable_change['signed_change']):.1f}s. "
            f"Keep practicing this intensity to turn that change into a stable trend."
        )
    else:
        key_insight = (
            f"Your most notable shift was in {notable_dimension['label']}: baseline {most_notable_change['baseline_value']:.0f} versus session {most_notable_change['session_value']:.0f}. "
            f"This {direction_word} by {abs(most_notable_change['signed_change']):.0f} points. "
            f"The next session should target this dimension while preserving your strongest stable metrics."
        )

    return {
        "injection_analysis": injection_analysis,
        "key_insight": key_insight,
    }


SNAPSPEAK_PROMPT_BANK = {
    "IT Services": [
        "What are you working on right now? Describe it in one minute.",
        "Describe the last bug you fixed and why it was tricky.",
        "What is the most annoying part of your current project?",
        "Explain what your team shipped last week.",
        "Describe a technical decision you made recently and why.",
        "What is blocking you right now at work?",
        "Describe a meeting you had today or yesterday.",
        "What does your afternoon look like?",
        "Explain one thing you wish your manager understood better.",
        "Describe the last time you had to explain something technical under time pressure.",
        "Describe your current sprint goal in plain language.",
        "What small improvement would make your team faster this week?",
        "Talk about one production risk you are watching closely.",
        "Describe a code review comment that changed your thinking.",
        "What is one technical task you are postponing and why?",
    ],
    "BPO or Call Centre": [
        "Describe a customer call from the last two days that stayed in your mind.",
        "What type of customer issue appears most often in your shift?",
        "Describe how you handle a caller who keeps interrupting.",
        "Tell me about a time you calmed an angry customer quickly.",
        "What is the hardest part of maintaining tone on long shifts?",
        "Describe your opening line on calls and why it works.",
        "What quality metric are you improving this week?",
        "Describe a call that escalated and how you managed it.",
        "What do you do when you need a few seconds to think during a call?",
        "Describe a small speaking habit that improved your call outcomes.",
        "Talk about a recent misunderstanding with a customer and how you recovered.",
        "Describe how your team supports each other during peak call volume.",
        "What kind of request usually makes you feel rushed?",
        "Describe a supervisor feedback point you are applying right now.",
        "What part of your shift requires the highest focus today?",
    ],
    "Healthcare": [
        "Describe your shift so far in under one minute.",
        "Describe a patient interaction that required extra clarity today.",
        "What communication challenge did your team face this week?",
        "Explain how you give handover updates under time pressure.",
        "Describe a moment when empathy mattered more than speed.",
        "What part of your role needs the clearest spoken English?",
        "Describe a common question from patients and how you answer it.",
        "What do you do when you need to clarify an instruction quickly?",
        "Describe one stressful moment from a recent shift and how you handled it.",
        "Explain one thing you always include in a patient update.",
        "Describe a team communication habit that prevents mistakes.",
        "What kind of conversation makes you slow down and choose words carefully?",
        "Describe how you reassure a worried family member.",
        "What communication task is most challenging near end of shift?",
        "Describe a recent situation where concise speaking helped care quality.",
    ],
    "Immigration Applicant": [
        "Describe one part of your immigration preparation you worked on this week.",
        "What is one daily routine helping your English confidence right now?",
        "Describe a conversation where you explained your future plans clearly.",
        "What worries you most about speaking in your destination country?",
        "Describe one professional skill you want to use after moving.",
        "How are you preparing for interviews or official speaking situations?",
        "Describe your typical weekday in under one minute.",
        "What support system is helping you stay consistent with preparation?",
        "Describe one challenge in your process and how you responded.",
        "What does success in the next six months look like for you?",
        "Describe how your current work experience will help abroad.",
        "What kind of English conversation do you want to feel calm in soon?",
        "Describe one document or process step that felt difficult recently.",
        "What part of relocation planning is on your mind today?",
        "Describe how you explain your goals to family or friends.",
    ],
    "Other": [
        "Describe what you are focusing on at work today.",
        "Talk about one challenge you handled this week.",
        "What conversation are you preparing for in the next few days?",
        "Describe a recent situation where you needed to speak quickly.",
        "What part of your role requires the most confidence in speaking?",
        "Describe one task you completed recently and why it mattered.",
        "What kind of meeting is hardest for you and why?",
        "Describe a moment this week when you had to think while speaking.",
        "What is one professional habit you are trying to improve now?",
        "Describe your current priorities in one minute.",
        "Talk about a recent misunderstanding and how you clarified it.",
        "Describe what your next workday will likely look like.",
        "What kind of feedback about communication helped you recently?",
        "Describe one thing that currently causes speaking pressure for you.",
        "Talk about a task you need to explain clearly to someone else soon.",
    ],
}


def _is_within_time_window(current_time, start_time, end_time):
    if start_time is None or end_time is None:
        return False
    if start_time <= end_time:
        return start_time <= current_time <= end_time
    return current_time >= start_time or current_time <= end_time


def select_snapspeak_prompt(user) -> tuple[str, str]:
    context_key = user.professional_context if user.professional_context in SNAPSPEAK_PROMPT_BANK else "Other"
    now_time = datetime.utcnow().time()

    in_preferred_window = _is_within_time_window(
        now_time,
        user.preferred_snapspeak_start,
        user.preferred_snapspeak_end,
    )

    if in_preferred_window:
        contextual_prompts = SNAPSPEAK_PROMPT_BANK.get(context_key, SNAPSPEAK_PROMPT_BANK["Other"])
        return random.choice(contextual_prompts), "contextual"

    random_pool = []
    for prompt_list in SNAPSPEAK_PROMPT_BANK.values():
        random_pool.extend(prompt_list)
    return random.choice(random_pool), "random"


def _recent_snapspeak_dimension_averages(user_id: int, current_source_id: int):
    from app.models import LsrcScore, SnapSpeakRecord

    baseline_records = SnapSpeakRecord.get_user_baseline_snapspeaks(user_id, limit=10)
    source_ids = [record.id for record in baseline_records if record.id != current_source_id]
    if not source_ids:
        return {
            "lexical_diversity": None,
            "disfluency_rate": None,
            "recovery_speed_seconds": None,
        }

    history_scores = (
        LsrcScore.query.filter(
            LsrcScore.user_id == user_id,
            LsrcScore.source_type == "snapspeak",
            LsrcScore.source_id.in_(source_ids),
            LsrcScore.condition == "spontaneous",
        )
        .order_by(LsrcScore.scored_at.desc())
        .all()
    )

    def avg(field_name):
        values = [
            _safe_float(getattr(item, field_name, None))
            for item in history_scores
            if _safe_float(getattr(item, field_name, None)) is not None
        ]
        if not values:
            return None
        return sum(values) / len(values)

    return {
        "lexical_diversity": avg("lexical_diversity"),
        "disfluency_rate": avg("disfluency_rate"),
        "recovery_speed_seconds": avg("recovery_speed_seconds"),
    }


def generate_snapspeak_analysis_lines(lsrc_score, user_id: int) -> tuple[str, str, str]:
    lexical_diversity = _safe_float(getattr(lsrc_score, "lexical_diversity", None))
    disfluency_rate = _safe_float(getattr(lsrc_score, "disfluency_rate", None))
    recovery_speed_seconds = _safe_float(getattr(lsrc_score, "recovery_speed_seconds", None))
    syntactic_complexity = _safe_float(getattr(lsrc_score, "syntactic_complexity", None))
    prosodic_confidence = _safe_float(getattr(lsrc_score, "prosodic_confidence", None))

    current_source_id = getattr(lsrc_score, "source_id", None)
    averages = _recent_snapspeak_dimension_averages(user_id, current_source_id)

    lexical_avg = _safe_float(averages.get("lexical_diversity"))
    disfluency_avg = _safe_float(averages.get("disfluency_rate"))
    recovery_avg = _safe_float(averages.get("recovery_speed_seconds"))

    if lexical_diversity is not None:
        lexical_value = round(lexical_diversity)
        if lexical_avg is not None:
            diff = lexical_diversity - lexical_avg
            direction = "above" if diff >= 0 else "below"
            line_1 = (
                f"Vocabulary range: {lexical_value} - {abs(diff):.1f} {direction} your recent average."
            )
        else:
            line_1 = f"Vocabulary range: {lexical_value} out of 100."
    elif syntactic_complexity is not None:
        line_1 = (
            f"Vocabulary range was not measurable in this capture. Sentence structure score: {round(syntactic_complexity)}."
        )
    elif prosodic_confidence is not None:
        line_1 = (
            f"Vocabulary range was not measurable in this capture. Vocal confidence score: {round(prosodic_confidence)}."
        )
    else:
        line_1 = "Vocabulary range could not be measured clearly from this recording."

    if disfluency_rate is not None:
        if disfluency_rate >= 70:
            pause_text = "pause frequency is low - good fluency under pressure"
        elif disfluency_rate >= 50:
            pause_text = "some hesitation present - within normal range"
        else:
            pause_text = "elevated pause frequency - stress signature detected"

        line_2 = f"Pause frequency: {pause_text}."
        if disfluency_avg is not None:
            pause_diff = disfluency_rate - disfluency_avg
            pause_direction = "above" if pause_diff >= 0 else "below"
            line_2 = (
                f"{line_2[:-1]} This is {abs(pause_diff):.1f} points {pause_direction} your recent average."
            )
    elif prosodic_confidence is not None:
        line_2 = (
            f"Pause frequency was not measurable in this capture. Vocal confidence score: {round(prosodic_confidence)}."
        )
    else:
        line_2 = "Pause frequency could not be measured reliably in this sample."

    from app.models import LsrcScore

    previous_recovery_values = [
        _safe_float(score.recovery_speed_seconds)
        for score in LsrcScore.query.filter(
            LsrcScore.user_id == user_id,
            LsrcScore.condition == "spontaneous",
            LsrcScore.source_id != current_source_id,
        )
        .order_by(LsrcScore.scored_at.desc())
        .limit(40)
        .all()
        if _safe_float(score.recovery_speed_seconds) is not None
    ]
    best_recovery = min(previous_recovery_values) if previous_recovery_values else None

    if recovery_speed_seconds is not None:
        if best_recovery is None:
            line_3 = (
                f"Recovery speed: {recovery_speed_seconds:.1f}s - this is your first measured recovery baseline."
            )
        elif recovery_speed_seconds < (best_recovery - 0.05):
            line_3 = f"Recovery speed: {recovery_speed_seconds:.1f}s - your personal best."
        elif recovery_speed_seconds <= (best_recovery + 0.5):
            line_3 = (
                f"Recovery speed: {recovery_speed_seconds:.1f}s - close to your best of {best_recovery:.1f}s."
            )
        elif recovery_avg is not None:
            recovery_diff = recovery_speed_seconds - recovery_avg
            direction = "slower" if recovery_diff > 0 else "faster"
            line_3 = (
                f"Recovery speed: {recovery_speed_seconds:.1f}s average - baseline comparison: {abs(recovery_diff):.1f}s {direction}."
            )
        else:
            line_3 = f"Recovery speed: {recovery_speed_seconds:.1f}s average - keep building consistency."
    elif lexical_diversity is not None and lexical_avg is not None:
        lexical_delta = lexical_diversity - lexical_avg
        direction = "above" if lexical_delta >= 0 else "below"
        line_3 = (
            f"Notable shift: vocabulary landed {abs(lexical_delta):.1f} points {direction} your recent baseline."
        )
    else:
        line_3 = "Notable observation: keep collecting SnapSpeaks to sharpen baseline comparisons."

    return line_1, line_2, line_3


def check_snapspeak_notable(lsrc_score, user_id: int) -> tuple[bool, str]:
    from app.models import LsrcScore

    prior_scores = (
        LsrcScore.query.filter(
            LsrcScore.user_id == user_id,
            LsrcScore.condition == "spontaneous",
            LsrcScore.id != lsrc_score.id,
        )
        .order_by(LsrcScore.scored_at.desc())
        .all()
    )

    if not prior_scores:
        return False, ""

    dimensions = [
        ("lexical_diversity", "Best lexical diversity in a SnapSpeak to date"),
        ("syntactic_complexity", "Best syntactic complexity in a SnapSpeak to date"),
        ("prosodic_confidence", "Best vocal confidence in a SnapSpeak to date"),
        ("disfluency_rate", "Personal best: lowest disfluency score"),
        ("sentence_completion", "Best sentence completion in a SnapSpeak to date"),
        ("recovery_speed_score", "Best recovery speed score in a SnapSpeak to date"),
    ]

    for field_name, annotation in dimensions:
        current_value = _safe_float(getattr(lsrc_score, field_name, None))
        if current_value is None:
            continue

        prior_values = [
            _safe_float(getattr(score, field_name, None))
            for score in prior_scores
            if _safe_float(getattr(score, field_name, None)) is not None
        ]
        if not prior_values:
            continue

        if current_value > (max(prior_values) + 5.0):
            if field_name == "recovery_speed_score":
                recovery_seconds = _safe_float(getattr(lsrc_score, "recovery_speed_seconds", None))
                if recovery_seconds is not None:
                    return True, f"Best recovery speed to date: {recovery_seconds:.1f}s"
            return True, annotation

    current_recovery_seconds = _safe_float(getattr(lsrc_score, "recovery_speed_seconds", None))
    if current_recovery_seconds is not None:
        prior_recovery_values = [
            _safe_float(getattr(score, "recovery_speed_seconds", None))
            for score in prior_scores
            if _safe_float(getattr(score, "recovery_speed_seconds", None)) is not None
        ]
        if prior_recovery_values and current_recovery_seconds < (min(prior_recovery_values) - 0.5):
            return True, f"Best recovery speed to date: {current_recovery_seconds:.1f}s"

    return False, ""
