from collections import defaultdict
from datetime import datetime, timedelta
import json
import os
import random
import tempfile

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from flask_wtf.csrf import validate_csrf
from wtforms.validators import ValidationError

from app.extensions import db
from app.models import (
    Assessment,
    DrillCompletion,
    Drill,
    FailureMode,
    InjectionEvent,
    LsrcScore,
    SessionCalibration,
    TrainingSession,
)
from app.services import calibration_engine
from app.services.audio_storage import get_audio_download_url, get_audio_url, upload_audio
from app.services.speech_analyzer import analyze_audio
from app.utils.decorators import login_required
from app.utils.helpers import (
    generate_session_insight,
    get_injection_type_display_name,
    get_session_type_display_name,
    get_sidebar_context,
)


sessions_bp = Blueprint("sessions", __name__, url_prefix="/")


DIMENSIONS = [
    {
        "key": "lexical_diversity",
        "label": "Lexical Diversity",
        "field": "lexical_diversity",
        "higher_is_better": True,
        "display": "score",
    },
    {
        "key": "syntactic_complexity",
        "label": "Syntactic Complexity",
        "field": "syntactic_complexity",
        "higher_is_better": True,
        "display": "score",
    },
    {
        "key": "prosodic_confidence",
        "label": "Prosodic Confidence",
        "field": "prosodic_confidence",
        "higher_is_better": True,
        "display": "score",
    },
    {
        "key": "disfluency_rate",
        "label": "Disfluency Rate",
        "field": "disfluency_rate",
        "higher_is_better": True,
        "display": "score",
    },
    {
        "key": "sentence_completion",
        "label": "Sentence Completion",
        "field": "sentence_completion",
        "higher_is_better": True,
        "display": "score",
    },
    {
        "key": "recovery_speed",
        "label": "Recovery Speed",
        "field": "recovery_speed_seconds",
        "higher_is_better": False,
        "display": "seconds",
    },
]


PIVOT_QUESTION_BANK = {
    "vocabulary_pressure": [
        "Now describe this situation from your manager's perspective.",
        "What would you tell a new colleague about this challenge?",
        "How would you explain this to someone with no technical background?",
        "What is the single most important thing you left out of what you just said?",
        "Describe the same situation but focus on what went wrong rather than what went right.",
        "Summarize your explanation in exactly three short points.",
        "If this happened again tomorrow, what would you do differently first?",
        "Explain the same story as if you were writing a client update email.",
        "What question would a skeptical stakeholder ask you right now?",
        "Restate your last point using simpler and clearer language.",
    ],
    "distractor_challenge": [
        "Switch now and explain this through a customer impact lens.",
        "Describe the risk if your first plan fails unexpectedly.",
        "What timeline would you commit to if you had half your current resources?",
        "Now focus only on communication mistakes made during the scenario.",
        "Explain how you would brief leadership in under one minute.",
        "Describe this event as if you were coaching a junior teammate.",
        "What assumptions in your approach might be wrong?",
        "Explain the same scenario but prioritize cost over speed.",
        "What would your toughest client likely challenge in your answer?",
        "Shift to prevention. How would you stop this from repeating?",
    ],
    "prosodic_drill": [
        "Now deliver the next part as if the listener is deeply concerned.",
        "Speak the same idea with calm authority and shorter sentences.",
        "Add a concise opening and closing statement to your explanation.",
        "Shift to a coaching tone and explain this to a new team member.",
        "How would you communicate this if the room was highly tense?",
        "Restate the last point with emphasis on confidence and clarity.",
        "Now answer as if this is a live media interview.",
        "Explain the key message in two confident sentences.",
        "What is your strongest recommendation and why should we trust it?",
        "Deliver one final summary with deliberate pace and calm tone.",
    ],
    "recovery_focus": [
        "Pause for a second, then restart with a cleaner first sentence.",
        "Reframe your response using one bridge phrase before continuing.",
        "Now continue and avoid repeating any phrase you used earlier.",
        "Restart from your most important point and keep it concise.",
        "Take a breath and summarize your answer in plain language.",
        "Continue but avoid filler words for the next twenty seconds.",
        "Switch perspective and answer as if you are mentoring someone.",
        "Recover from your previous point by giving one practical example.",
        "Now continue with slower pacing and complete every sentence fully.",
        "Close with a confident next action statement.",
    ],
    "baseline_measurement": [
        "Describe your current role and what communication pressure looks like for you.",
        "Share one recent conversation where stress affected your speech.",
        "Explain what you want to improve first in spoken English.",
        "Describe how you currently prepare for high stakes conversations.",
        "What kind of interruptions are hardest for you to manage?",
        "How do you recover when you lose a word during a meeting?",
        "Describe a typical work conversation where confidence drops.",
        "What outcome would make this training feel successful for you?",
        "How do you want colleagues to describe your communication style six months from now?",
        "What topic makes you feel most pressure when speaking in English?",
    ],
}


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def _validate_form_csrf():
    if not current_app.config.get("WTF_CSRF_ENABLED", True):
        return True

    token = request.form.get("csrf_token")
    if not token:
        return False

    try:
        validate_csrf(token)
    except ValidationError:
        return False

    return True


def _get_or_refresh_calibration(user_id):
    calibration = SessionCalibration.query.filter_by(user_id=user_id).first()
    stale_cutoff = datetime.utcnow() - timedelta(hours=48)
    if calibration is None or (calibration.computed_at and calibration.computed_at < stale_cutoff):
        calibration = calibration_engine.compute_next_session(user_id)
    return calibration


def _get_baseline_scores(user_id):
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
        return []

    return (
        LsrcScore.query.filter_by(
            user_id=user_id,
            source_type="assessment",
            source_id=baseline_assessment.id,
        )
        .order_by(LsrcScore.scored_at.asc())
        .all()
    )


def _build_dimension_rows(session_score, baseline_score):
    rows = []

    for dimension in DIMENSIONS:
        session_value = _safe_float(getattr(session_score, dimension["field"], None))
        baseline_value = _safe_float(getattr(baseline_score, dimension["field"], None))

        if session_value is None or baseline_value is None:
            change_value = None
            trend = "same"
        else:
            change_value = round(session_value - baseline_value, 2)
            if abs(change_value) < 0.01:
                trend = "same"
            elif dimension["higher_is_better"]:
                trend = "improved" if change_value > 0 else "declined"
            else:
                trend = "improved" if change_value < 0 else "declined"

        rows.append(
            {
                "key": dimension["key"],
                "label": dimension["label"],
                "display": dimension["display"],
                "session_value": session_value,
                "baseline_value": baseline_value,
                "change": change_value,
                "trend": trend,
            }
        )

    return rows


def _group_drills_by_category(drills):
    grouped = defaultdict(list)
    for drill in drills:
        grouped[drill.category].append(drill)
    return dict(sorted(grouped.items(), key=lambda item: item[0]))


def _normalize_category_name(value):
    return (value or "").strip().lower().replace(" ", "_")


def _recommended_drill_category(user_id):
    failure_mode = FailureMode.query.filter_by(user_id=user_id).first()
    if failure_mode is None:
        return None, None

    mapping = {
        "lexical_diversity": "semantic_substitution",
        "recovery_speed": "semantic_substitution",
        "prosodic_confidence": "filler_bridging",
        "disfluency_rate": "filler_bridging",
        "sentence_completion": "reformulation",
        "syntactic_complexity": "reformulation",
    }
    return mapping.get(failure_mode.primary_dimension), failure_mode


def _drill_completion_stats(user_id):
    return DrillCompletion.get_user_stats(user_id)


def _drill_personal_bests(user_id):
    completions = (
        DrillCompletion.query.filter_by(user_id=user_id)
        .order_by(DrillCompletion.completed_at.desc())
        .all()
    )
    bests = {}
    for completion in completions:
        value = _safe_float(completion.recovery_time_seconds)
        if value is None:
            continue
        previous = bests.get(completion.drill_id)
        if previous is None or value < previous:
            bests[completion.drill_id] = round(value, 2)
    return bests


@sessions_bp.get("/session/new")
@login_required
def new_session():
    calibration = _get_or_refresh_calibration(current_user.id)
    prompt_text = calibration_engine.get_session_prompt(
        calibration.next_session_type,
        current_user.professional_context or "Other",
    )

    completed_count = TrainingSession.get_user_session_count(current_user.id)
    session_number = completed_count + 1

    return render_template(
        "sessions/new.html",
        title="New Session - PressureProof",
        calibration=calibration,
        prompt_text=prompt_text,
        session_number=session_number,
        session_type_display_name=get_session_type_display_name(
            calibration.next_session_type
        ),
        microphone_test_endpoint=url_for("api.dashboard_readiness"),
        **_sidebar_payload(current_user.id),
    )


@sessions_bp.post("/session/new")
@login_required
def create_session():
    if not _validate_form_csrf():
        flash("Session could not be created because your security token expired.", "error")
        return redirect(url_for("sessions.new_session"))

    calibration = _get_or_refresh_calibration(current_user.id)
    completed_count = TrainingSession.get_user_session_count(current_user.id)

    session_type = request.form.get("session_type") or calibration.next_session_type
    prompt_text = request.form.get("prompt_text") or calibration_engine.get_session_prompt(
        calibration.next_session_type,
        current_user.professional_context or "Other",
    )

    session = TrainingSession(
        user_id=current_user.id,
        session_type=session_type,
        prompt_text=prompt_text,
        stress_injection_type=calibration.next_injection_type,
        stress_injection_intensity=calibration.next_injection_intensity,
        injection_timestamp_seconds=calibration.next_injection_timing_seconds,
        injection_actually_fired=False,
        early_exit=False,
        session_number=completed_count + 1,
        status="recording",
    )

    db.session.add(session)
    db.session.commit()

    return redirect(url_for("sessions.active_session", session_id=session.id))


@sessions_bp.get("/session/<int:session_id>")
@login_required
def active_session(session_id):
    session = TrainingSession.query.get_or_404(session_id)
    if session.user_id != current_user.id:
        abort(403)

    if session.status == "completed":
        return redirect(url_for("sessions.summary", session_id=session.id))

    if session.status == "failed":
        flash(
            session.error_message or "The previous session processing failed. Please start again.",
            "error",
        )
        return redirect(url_for("sessions.new_session"))

    calibration_payload = {
        "injection_type": session.stress_injection_type,
        "intensity": float(session.stress_injection_intensity),
        "timing_seconds": session.injection_timestamp_seconds,
        "session_id": session.id,
    }

    segment_duration = 180
    transition_duration = 10

    return render_template(
        "sessions/active.html",
        title="Active Session - PressureProof",
        session=session,
        session_type_display_name=get_session_type_display_name(session.session_type),
        calibration_payload=calibration_payload,
        segment_duration=segment_duration,
        transition_duration=transition_duration,
        chunk_upload_url=url_for("api.session_audio_chunk", session_id=session.id),
        session_complete_url=url_for("api.complete_session", session_id=session.id),
        pivot_questions=PIVOT_QUESTION_BANK.get(
            session.session_type,
            PIVOT_QUESTION_BANK["baseline_measurement"],
        ),
        hide_header=True,
        hide_footer=True,
        hide_sidebar=True,
        no_sidebar=True,
    )


@sessions_bp.get("/session/<int:session_id>/summary")
@login_required
def summary(session_id):
    session = TrainingSession.query.get_or_404(session_id)
    if session.user_id != current_user.id:
        abort(403)

    if session.status != "completed":
        return render_template(
            "sessions/summary.html",
            title="Session Summary - PressureProof",
            session=session,
            is_processing=True,
            status_poll_url=url_for("api.session_status", session_id=session.id),
            **_sidebar_payload(current_user.id),
        )

    session_lsrc_scores = (
        LsrcScore.query.filter_by(
            user_id=current_user.id,
            source_type="session",
            source_id=session.id,
        )
        .order_by(LsrcScore.scored_at.desc())
        .all()
    )
    session_score = None
    for candidate in session_lsrc_scores:
        if candidate.condition == "prepared":
            session_score = candidate
            break
    if session_score is None and session_lsrc_scores:
        session_score = session_lsrc_scores[0]

    baseline_scores = _get_baseline_scores(current_user.id)
    baseline_score = None
    for score in reversed(baseline_scores):
        if score.condition == "prepared":
            baseline_score = score
            break
    if baseline_score is None and baseline_scores:
        baseline_score = baseline_scores[-1]

    dimension_rows = []
    if session_score is not None and baseline_score is not None:
        dimension_rows = _build_dimension_rows(session_score, baseline_score)

    injection_events = (
        InjectionEvent.query.filter_by(session_id=session.id)
        .order_by(InjectionEvent.created_at.asc())
        .all()
    )

    insight_payload = generate_session_insight(
        session=session,
        lsrc_scores=session_lsrc_scores,
        baseline_scores=baseline_scores,
        injection_events=injection_events,
    )

    calibration = _get_or_refresh_calibration(current_user.id)

    audio_url = get_audio_url(session.audio_path) if session.audio_path else None
    audio_download_url = get_audio_download_url(session.audio_path) if session.audio_path else None
    total_duration_seconds = 370
    if session.completed_at and session.created_at:
        computed_duration = int((session.completed_at - session.created_at).total_seconds())
        if computed_duration > 0:
            total_duration_seconds = computed_duration

    injection_marker_left = 0
    if total_duration_seconds > 0:
        injection_marker_left = round(
            min(100, max(0, (session.injection_timestamp_seconds / total_duration_seconds) * 100)),
            2,
        )

    return render_template(
        "sessions/summary.html",
        title="Session Summary - PressureProof",
        session=session,
        is_processing=False,
        session_score=session_score,
        baseline_score=baseline_score,
        dimension_rows=dimension_rows,
        session_composite=_safe_float(getattr(session_score, "composite_score", None)),
        baseline_composite=_safe_float(getattr(baseline_score, "composite_score", None)),
        injection_events=injection_events,
        injection_type_display=get_injection_type_display_name(session.stress_injection_type),
        injection_analysis_text=insight_payload.get("injection_analysis"),
        key_insight=insight_payload.get("key_insight"),
        next_session_display=get_session_type_display_name(calibration.next_session_type),
        audio_url=audio_url,
        audio_download_url=audio_download_url,
        total_duration_seconds=total_duration_seconds,
        injection_marker_left=injection_marker_left,
        **_sidebar_payload(current_user.id),
    )


@sessions_bp.get("/drills")
@login_required
def drills_library():
    drills = (
        Drill.query.order_by(Drill.category.asc(), Drill.difficulty_level.asc(), Drill.title.asc()).all()
    )
    grouped_drills = _group_drills_by_category(drills)
    recommended_category_key, failure_mode = _recommended_drill_category(current_user.id)

    recommended_drills = []
    if recommended_category_key:
        recommended_drills = [
            drill for drill in drills if _normalize_category_name(drill.category) == recommended_category_key
        ][:2]

    drill_stats = _drill_completion_stats(current_user.id)
    personal_bests = _drill_personal_bests(current_user.id)

    return render_template(
        "drills/library.html",
        title="Recovery Drill Library - PressureProof",
        drills_by_category=grouped_drills,
        recommended_category_key=recommended_category_key,
        recommended_drills=recommended_drills,
        failure_mode=failure_mode,
        drill_stats=drill_stats,
        personal_bests=personal_bests,
        **_sidebar_payload(current_user.id),
    )


@sessions_bp.get("/drills/<int:drill_id>")
@login_required
def drills_active(drill_id):
    drill = Drill.query.get_or_404(drill_id)

    try:
        filler_phrases = json.loads(drill.filler_phrases or "[]")
        if not isinstance(filler_phrases, list):
            filler_phrases = []
    except (TypeError, ValueError):
        filler_phrases = []

    completed_count = TrainingSession.get_user_session_count(current_user.id)
    drill_session = TrainingSession(
        user_id=current_user.id,
        session_type="recovery_focus",
        prompt_text=f"Drill: {drill.title}. {drill.description}",
        stress_injection_type="none",
        stress_injection_intensity=0.0,
        injection_timestamp_seconds=0,
        injection_actually_fired=False,
        early_exit=False,
        session_number=completed_count + 1,
        status="recording",
    )
    db.session.add(drill_session)
    db.session.commit()

    freeze_cue_timing = random.randint(18, 45)

    return render_template(
        "drills/active.html",
        title=f"{drill.title} - Recovery Drill - PressureProof",
        drill=drill,
        filler_phrases=filler_phrases,
        freeze_cue_timing=freeze_cue_timing,
        drill_session=drill_session,
        hide_sidebar=True,
        no_sidebar=True,
        **_sidebar_payload(current_user.id),
    )


@sessions_bp.post("/drills/<int:drill_id>/complete")
@login_required
def complete_drill(drill_id):
    if not _validate_form_csrf():
        return jsonify({"success": False, "error": "Security token expired."}), 400

    drill = Drill.query.get_or_404(drill_id)

    freeze_cue_timestamp_seconds = _safe_float(
        request.form.get("freeze_cue_timestamp_seconds"),
        default=0.0,
    )
    recovery_time_seconds = _safe_float(request.form.get("recovery_time_seconds"), default=None)
    pathway_used = (request.form.get("pathway_used") or "reformulation").strip()
    transcript_excerpt = (request.form.get("transcript_excerpt") or "").strip()
    drill_session_id = request.form.get("session_id", type=int)
    audio_file = request.files.get("audio")

    if pathway_used not in {"filler_bridging", "reformulation", "semantic_substitution"}:
        pathway_used = "reformulation"

    training_session = None
    if drill_session_id:
        candidate = TrainingSession.query.get(drill_session_id)
        if (
            candidate is not None
            and candidate.user_id == current_user.id
            and candidate.session_type == "recovery_focus"
        ):
            training_session = candidate

    if training_session is None:
        completed_count = TrainingSession.get_user_session_count(current_user.id)
        training_session = TrainingSession(
            user_id=current_user.id,
            session_type="recovery_focus",
            prompt_text=f"Drill: {drill.title}",
            stress_injection_type="none",
            stress_injection_intensity=0.0,
            injection_timestamp_seconds=0,
            injection_actually_fired=False,
            early_exit=False,
            session_number=completed_count + 1,
            status="recording",
        )
        db.session.add(training_session)
        db.session.flush()

    temp_path = None
    uploaded_audio_path = None

    try:
        estimated_recovery_time = recovery_time_seconds
        analyzed_transcript = None

        if audio_file is not None and audio_file.filename:
            extension = os.path.splitext(audio_file.filename)[1] or ".webm"
            temp_filename = f"drill_{training_session.id}_{random.randint(1000, 9999)}{extension}"
            temp_path = os.path.join(tempfile.gettempdir(), temp_filename)
            audio_file.save(temp_path)

            analysis_result = analyze_audio(temp_path)
            analyzed_transcript = (analysis_result.get("transcript") or "").strip()
            word_timestamps = analysis_result.get("word_timestamps") or []

            if estimated_recovery_time is None:
                post_freeze_words = [
                    word for word in word_timestamps if _safe_float(word.get("start"), default=-1) >= freeze_cue_timestamp_seconds
                ]
                if post_freeze_words:
                    first_resumption = _safe_float(post_freeze_words[0].get("start"), default=freeze_cue_timestamp_seconds)
                    estimated_recovery_time = max(0.2, first_resumption - freeze_cue_timestamp_seconds)
                else:
                    estimated_recovery_time = 4.5

            uploaded_audio_path = upload_audio(
                temp_path,
                user_id=current_user.id,
                record_type="drill",
            )

        if estimated_recovery_time is None:
            estimated_recovery_time = 4.5

        normalized_recovery = round(max(0.1, float(estimated_recovery_time)), 2)

        transcript_value = transcript_excerpt or analyzed_transcript or ""
        transcript_value = transcript_value[:300] if transcript_value else None

        training_session.prompt_text = f"Drill: {drill.title}. Pathway used: {pathway_used}."
        training_session.transcript = transcript_value
        training_session.audio_path = uploaded_audio_path or training_session.audio_path
        training_session.injection_actually_fired = True
        training_session.injection_timestamp_seconds = int(round(max(0.0, freeze_cue_timestamp_seconds)))
        training_session.stress_injection_type = "drill_freeze_cue"
        training_session.stress_injection_intensity = 0.3
        training_session.status = "completed"
        training_session.completed_at = datetime.utcnow()

        db.session.add(
            InjectionEvent(
                session_id=training_session.id,
                injection_type="drill_freeze_cue",
                fired_at_seconds=max(0.0, freeze_cue_timestamp_seconds),
                pressure_meter_value=0.30,
            )
        )

        db.session.add(
            DrillCompletion(
                user_id=current_user.id,
                drill_id=drill.id,
                recovery_time_seconds=normalized_recovery,
                pathway_used=pathway_used,
                transcript_excerpt=transcript_value,
                audio_path=uploaded_audio_path,
                session_id=training_session.id,
            )
        )

        db.session.commit()

        if normalized_recovery <= 3.0:
            feedback = "Excellent control. Your recovery speed is in the target zone."
        elif normalized_recovery <= 5.0:
            feedback = "Good recovery. Keep tightening your bridge phrase and continue immediately."
        else:
            feedback = "Recovery completed, but slower than target. Repeat this drill to shorten the pause gap."

        return jsonify(
            {
                "success": True,
                "recovery_time": normalized_recovery,
                "freeze_cue_timestamp_seconds": round(max(0.0, freeze_cue_timestamp_seconds), 2),
                "message": feedback,
            }
        )
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Unable to complete drill: {exc}"}), 500
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                current_app.logger.warning("Unable to clean temporary drill audio %s", temp_path)
