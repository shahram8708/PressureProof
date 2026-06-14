from datetime import date, datetime, time, timedelta
import json
import os
import tempfile
from uuid import uuid4

from flask import Blueprint, abort, current_app, jsonify, request, send_file, url_for
from flask_login import current_user
from flask_wtf.csrf import validate_csrf
import redis
from wtforms.validators import ValidationError

from app.extensions import celery, db, limiter
from app.models import Assessment, InjectionEvent, LsrcScore, PgiRecord, SnapSpeakRecord, TrainingSession
from app.services import notification_service
from app.services import cohort_service, payment_service
from app.services import certificate_generator
from app.services.pgi_calculator import compute_pgi_projection, get_pgi_trend_data
from app.utils.decorators import login_required


api_bp = Blueprint("api", __name__, url_prefix="/api")


ALLOWED_AUDIO_MIME_TYPES = {
    "audio/webm",
    "audio/wav",
    "audio/ogg",
    "audio/mp4",
}
MAX_AUDIO_BYTES = 15 * 1024 * 1024

ALLOWED_SNAPSPEAK_MIME_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/mp4",
    "application/octet-stream",
}

ALLOWED_SESSION_CHUNK_MIME_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/mp4",
    "application/octet-stream",
}
MAX_SESSION_CHUNK_BYTES = 2 * 1024 * 1024
SESSION_CHUNK_TTL_SECONDS = 3600


DIMENSION_CONFIG = [
    ("lexical_diversity", "Lexical Diversity", "lexical_diversity"),
    ("syntactic_complexity", "Syntactic Complexity", "syntactic_complexity"),
    ("prosodic_confidence", "Prosodic Confidence", "prosodic_confidence"),
    ("disfluency_rate", "Disfluency Rate", "disfluency_rate"),
    ("sentence_completion", "Sentence Completion", "sentence_completion"),
    ("recovery_speed", "Recovery Speed", "recovery_speed_score"),
]


def _get_redis_client():
    redis_url = (
        current_app.config.get("REDIS_URL")
        or current_app.config.get("CELERY_BROKER_URL")
        or os.getenv("REDIS_URL")
        or "redis://localhost:6379/0"
    )
    return redis.Redis.from_url(redis_url, decode_responses=False)


def _get_session_for_user(session_id, user_id):
    session = TrainingSession.query.get(session_id)
    if session is None:
        return None, (jsonify({"error": "Session not found."}), 404)
    if session.user_id != user_id:
        return None, (jsonify({"error": "Access denied."}), 403)
    return session, None


def _parse_injection_event_payload(raw_payload):
    if not raw_payload:
        return None

    if isinstance(raw_payload, dict):
        payload = raw_payload
    else:
        try:
            payload = json.loads(raw_payload)
        except (TypeError, ValueError):
            return None

    if not isinstance(payload, dict):
        return None

    return payload


def _log_injection_event(session, injection_payload):
    if not injection_payload:
        return None

    injection_type = (injection_payload.get("injection_type") or session.stress_injection_type or "none").strip()
    fired_at_seconds = _safe_float(injection_payload.get("fired_at_seconds"), default=None)
    pressure_meter_value = _safe_float(injection_payload.get("pressure_meter_value"), default=None)

    if fired_at_seconds is None:
        fired_at_seconds = float(session.injection_timestamp_seconds or 0)
    fired_at_seconds = max(0.0, fired_at_seconds)

    if pressure_meter_value is not None:
        pressure_meter_value = max(0.0, min(1.0, pressure_meter_value))

    event = InjectionEvent(
        session_id=session.id,
        injection_type=injection_type,
        fired_at_seconds=fired_at_seconds,
        pressure_meter_value=pressure_meter_value,
    )
    db.session.add(event)

    session.injection_actually_fired = True
    db.session.commit()

    return event


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_week_parameter(week_value):
    year_text, week_text = week_value.split("-")
    year = int(year_text)
    week = int(week_text)
    return date.fromisocalendar(year, week, 1)


def _week_bounds(week_start_date):
    start_dt = datetime.combine(week_start_date, time.min)
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


def _query_training_sessions_for_day(user_id, day_start, day_end):
    try:
        from app.models import TrainingSession

        timestamp_column = getattr(TrainingSession, "completed_at", None) or getattr(
            TrainingSession,
            "created_at",
            None,
        )
        if timestamp_column is None:
            return 0
        return (
            TrainingSession.query.filter(
                TrainingSession.user_id == user_id,
                timestamp_column >= day_start,
                timestamp_column < day_end,
            ).count()
        )
    except Exception:
        return 0


def _query_snapspeaks_for_day(user_id, day_start, day_end):
    try:
        from app.models import SnapSpeakRecord

        timestamp_column = getattr(SnapSpeakRecord, "captured_at", None) or getattr(
            SnapSpeakRecord,
            "created_at",
            None,
        )
        if timestamp_column is None:
            return 0
        return (
            SnapSpeakRecord.query.filter(
                SnapSpeakRecord.user_id == user_id,
                timestamp_column >= day_start,
                timestamp_column < day_end,
            ).count()
        )
    except Exception:
        return 0


def _compute_readiness_score(user_id, current_pgi):
    recent_scores = (
        LsrcScore.query.filter_by(user_id=user_id)
        .order_by(LsrcScore.scored_at.desc())
        .limit(7)
        .all()
    )
    values = [
        _safe_float(score.composite_score)
        for score in recent_scores
        if _safe_float(score.composite_score) is not None
    ]
    if not values:
        return None

    mean_score = sum(values) / len(values)
    if current_pgi is not None:
        mean_score *= 1.0 - (current_pgi / 100.0)

    return max(0, min(100, int(round(mean_score))))


def _resolve_pgi_direction(user_id):
    latest_two = (
        PgiRecord.query.filter_by(user_id=user_id)
        .order_by(PgiRecord.week_start_date.desc())
        .limit(2)
        .all()
    )
    if len(latest_two) < 2:
        return "insufficient_data"

    latest = _safe_float(latest_two[0].pgi_score)
    previous = _safe_float(latest_two[1].pgi_score)
    if latest is None or previous is None:
        return "insufficient_data"
    if latest < previous:
        return "improving"
    if latest > previous:
        return "declining"
    return "stable"


def _validate_csrf_if_enabled():
    if not current_app.config.get("WTF_CSRF_ENABLED", True):
        return None

    token = request.headers.get("X-CSRFToken") or request.form.get("csrf_token")
    if not token:
        return jsonify({"error": "Missing CSRF token."}), 400

    try:
        validate_csrf(token)
    except ValidationError:
        return jsonify({"error": "Invalid CSRF token."}), 400

    return None


def _get_uploaded_file_size(file_storage):
    current_position = file_storage.stream.tell()
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(current_position)
    return size


def _save_temp_upload(file_storage, prefix):
    extension = os.path.splitext(file_storage.filename or "")[1] or ".webm"
    filename = f"{prefix}_{uuid4().hex}{extension}"
    temp_dir = os.path.join(tempfile.gettempdir(), "pressureproof_baseline")
    os.makedirs(temp_dir, exist_ok=True)
    path = os.path.join(temp_dir, filename)
    file_storage.save(path)
    return path


@api_bp.get("/health")
def health_check():
    return jsonify({"status": "ok", "service": "pressureproof"})


@api_bp.post("/assessment/baseline")
@login_required
def submit_baseline_assessment():
    csrf_error = _validate_csrf_if_enabled()
    if csrf_error is not None:
        return csrf_error

    audio_prepared = request.files.get("audio_prepared")
    audio_spontaneous = request.files.get("audio_spontaneous")

    if audio_prepared is None or audio_spontaneous is None:
        return jsonify({"error": "Both audio files are required."}), 400

    for audio_file in [audio_prepared, audio_spontaneous]:
        if audio_file.mimetype not in ALLOWED_AUDIO_MIME_TYPES:
            return jsonify({"error": f"Unsupported audio MIME type: {audio_file.mimetype}"}), 400
        if _get_uploaded_file_size(audio_file) > MAX_AUDIO_BYTES:
            return jsonify({"error": "Each audio file must be under 15MB."}), 400

    temp_prepared_path = None
    temp_spontaneous_path = None

    try:
        temp_prepared_path = _save_temp_upload(audio_prepared, "prepared")
        temp_spontaneous_path = _save_temp_upload(audio_spontaneous, "spontaneous")

        assessment = Assessment(
            user_id=current_user.id,
            assessment_type="baseline",
            status="processing",
        )
        db.session.add(assessment)
        db.session.flush()

        from app.tasks import analyze_baseline_audio

        async_task = analyze_baseline_audio.delay(
            temp_prepared_path,
            temp_spontaneous_path,
            assessment.id,
            current_user.id,
        )

        assessment.celery_task_id = async_task.id
        db.session.commit()

        return jsonify(
            {
                "status": "processing",
                "task_id": async_task.id,
                "assessment_id": assessment.id,
            }
        )
    except Exception as exc:
        db.session.rollback()
        for path in [temp_prepared_path, temp_spontaneous_path]:
            if path and os.path.exists(path):
                os.remove(path)
        return jsonify({"error": f"Unable to start baseline analysis: {exc}"}), 500


@limiter.exempt
@api_bp.get("/assessment/status/<task_id>")
@login_required
def baseline_status(task_id):
    assessment = Assessment.query.filter_by(celery_task_id=task_id).first()
    if assessment is None:
        return jsonify({"status": "not_found", "message": "Assessment not found."}), 404

    if assessment.user_id != current_user.id:
        return jsonify({"status": "forbidden", "message": "Access denied."}), 403

    if assessment.status in {"pending", "processing"}:
        async_result = celery.AsyncResult(task_id)
        progress = 10

        if async_result.state == "PROGRESS":
            progress = int((async_result.info or {}).get("progress", 10))
        elif async_result.state == "STARTED":
            progress = 25
        elif async_result.state == "SUCCESS":
            progress = 95
        elif async_result.state == "FAILURE":
            return jsonify(
                {
                    "status": "failed",
                    "message": assessment.error_message
                    or "Speech analysis failed during processing.",
                }
            )

        return jsonify({"status": "processing", "progress": progress})

    if assessment.status == "completed":
        return jsonify({"status": "completed", "redirect": "/onboarding/step-3"})

    if assessment.status == "failed":
        return jsonify(
            {
                "status": "failed",
                "message": assessment.error_message or "Speech analysis failed.",
            }
        )

    return jsonify({"status": assessment.status})


@api_bp.post("/snapspeak/submit")
@login_required
def submit_snapspeak():
    csrf_error = _validate_csrf_if_enabled()
    if csrf_error is not None:
        return csrf_error

    snapspeak_id = request.form.get("snapspeak_id", type=int)
    audio_file = request.files.get("audio")

    if snapspeak_id is None:
        return jsonify({"error": "snapspeak_id is required."}), 400
    if audio_file is None:
        return jsonify({"error": "Audio file is required."}), 400

    record = SnapSpeakRecord.query.get(snapspeak_id)
    if record is None:
        return jsonify({"error": "SnapSpeak record not found."}), 404
    if record.user_id != current_user.id:
        return jsonify({"error": "Access denied."}), 403
    if record.status != "pending":
        return jsonify({"error": "This SnapSpeak has already been submitted."}), 409

    mime_type = (audio_file.mimetype or "").split(";")[0].strip().lower()
    if mime_type not in ALLOWED_SNAPSPEAK_MIME_TYPES:
        return jsonify({"error": f"Unsupported audio MIME type: {audio_file.mimetype}"}), 400

    if _get_uploaded_file_size(audio_file) > MAX_AUDIO_BYTES:
        return jsonify({"error": "Audio file must be under 15MB."}), 413

    temp_audio_path = None
    try:
        temp_audio_path = _save_temp_upload(audio_file, "snapspeak")

        from app.tasks import analyze_snapspeak_audio

        record.status = "processing"
        task = analyze_snapspeak_audio.delay(temp_audio_path, record.id, current_user.id)
        record.celery_task_id = task.id
        db.session.commit()

        return jsonify(
            {
                "status": "processing",
                "task_id": task.id,
                "snapspeak_id": record.id,
            }
        )
    except Exception as exc:
        db.session.rollback()
        if temp_audio_path and os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)
        return jsonify({"error": f"Unable to submit SnapSpeak audio: {exc}"}), 500


@api_bp.get("/snapspeak/status/<task_id>")
@login_required
def snapspeak_status(task_id):
    record = SnapSpeakRecord.query.filter_by(celery_task_id=task_id).first()
    if record is None:
        return jsonify({"status": "not_found", "message": "SnapSpeak task not found."}), 404
    if record.user_id != current_user.id:
        return jsonify({"status": "forbidden", "message": "Access denied."}), 403

    if record.status in {"pending", "processing"}:
        progress = 10
        async_result = celery.AsyncResult(task_id)
        if async_result.state == "PROGRESS":
            progress = int((async_result.info or {}).get("progress", 10))
        elif async_result.state == "STARTED":
            progress = 30
        elif async_result.state == "SUCCESS":
            progress = 95
        elif async_result.state == "FAILURE":
            return jsonify(
                {
                    "status": "failed",
                    "message": record.error_message or "SnapSpeak analysis failed.",
                }
            )

        return jsonify({"status": "processing", "progress": max(1, min(99, progress))})

    if record.status == "completed":
        return jsonify(
            {
                "status": "completed",
                "analysis": {
                    "line_1": record.analysis_line_1,
                    "line_2": record.analysis_line_2,
                    "line_3": record.analysis_line_3,
                },
                "snapspeak_id": record.id,
            }
        )

    if record.status == "failed":
        return jsonify(
            {
                "status": "failed",
                "message": record.error_message or "SnapSpeak analysis failed.",
            }
        )

    return jsonify({"status": record.status})


@api_bp.post("/snapspeak/<int:snapspeak_id>/tag")
@login_required
def tag_snapspeak(snapspeak_id):
    csrf_error = _validate_csrf_if_enabled()
    if csrf_error is not None:
        return csrf_error

    record = SnapSpeakRecord.query.get_or_404(snapspeak_id)
    if record.user_id != current_user.id:
        return jsonify({"error": "Access denied."}), 403

    payload = request.get_json(silent=True) or {}
    tag_value = (payload.get("tag") or "").strip().lower()
    if tag_value not in {"work", "casual", "preparation"}:
        return jsonify({"error": "Invalid tag value."}), 400

    record.context_tag = tag_value
    db.session.commit()
    return jsonify({"status": "updated", "tag": tag_value})


@api_bp.post("/push/subscribe")
@login_required
def push_subscribe():
    csrf_error = _validate_csrf_if_enabled()
    if csrf_error is not None:
        return csrf_error

    payload = request.get_json(silent=True) or {}
    try:
        notification_service.register_push_subscription(current_user.id, payload)
        return jsonify({"status": "subscribed"})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        current_app.logger.exception("Push subscription registration failed")
        return jsonify({"error": f"Unable to subscribe for push notifications: {exc}"}), 500


@api_bp.post("/push/unsubscribe")
@login_required
def push_unsubscribe():
    csrf_error = _validate_csrf_if_enabled()
    if csrf_error is not None:
        return csrf_error

    payload = request.get_json(silent=True) or {}
    endpoint = payload.get("endpoint")
    notification_service.unregister_push_subscription(endpoint)
    return jsonify({"status": "unsubscribed"})


@api_bp.get("/lsrc/<week>")
@login_required
def lsrc_week_data(week):
    try:
        week_start = _parse_week_parameter(week)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid week format. Use YYYY-WW."}), 400

    week_start_dt, week_end_dt = _week_bounds(week_start)
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
    has_data = len(week_scores) > 0

    if has_data:
        prepared_data = [
            _average(prepared_scores, field_name) or 0 for _, _, field_name in DIMENSION_CONFIG
        ]
        spontaneous_data = [
            _average(spontaneous_scores, field_name) or 0 for _, _, field_name in DIMENSION_CONFIG
        ]
    else:
        prepared_data = []
        spontaneous_data = []

    return jsonify(
        {
            "labels": [display_name for _, display_name, _ in DIMENSION_CONFIG],
            "datasets": [
                {
                    "label": "Prepared English",
                    "data": prepared_data,
                    "borderColor": "#4F46E5",
                    "backgroundColor": "rgba(79,70,229,0.15)",
                },
                {
                    "label": "English Under Pressure",
                    "data": spontaneous_data,
                    "borderColor": "#F59E0B",
                    "backgroundColor": "rgba(245,158,11,0.15)",
                },
            ],
            "has_data": has_data,
            "week_start": week_start.strftime("%Y-%m-%d"),
            "week_end": (week_start + timedelta(days=6)).strftime("%Y-%m-%d"),
        }
    )


@api_bp.get("/pgi/trend")
@login_required
def pgi_trend_data():
    try:
        weeks = int(request.args.get("weeks", 12))
    except (TypeError, ValueError):
        weeks = 12
    weeks = max(1, min(52, weeks))

    trend = get_pgi_trend_data(current_user.id, weeks=weeks)
    projection = compute_pgi_projection(trend)

    latest_record = (
        PgiRecord.query.filter_by(user_id=current_user.id)
        .order_by(PgiRecord.week_start_date.desc())
        .first()
    )
    baseline_record = (
        PgiRecord.query.filter_by(user_id=current_user.id)
        .order_by(PgiRecord.week_start_date.asc())
        .first()
    )

    return jsonify(
        {
            "trend": trend,
            "projection": projection,
            "current_pgi": _safe_float(latest_record.pgi_score) if latest_record else None,
            "baseline_pgi": _safe_float(baseline_record.pgi_score) if baseline_record else None,
        }
    )


@api_bp.get("/dashboard/readiness")
@login_required
def dashboard_readiness():
    latest_record = (
        PgiRecord.query.filter_by(user_id=current_user.id)
        .order_by(PgiRecord.week_start_date.desc())
        .first()
    )
    current_pgi = _safe_float(latest_record.pgi_score) if latest_record else None
    readiness_score = _compute_readiness_score(current_user.id, current_pgi)
    pgi_direction = _resolve_pgi_direction(current_user.id)

    day_start = datetime.combine(date.today(), time.min)
    day_end = day_start + timedelta(days=1)
    sessions_today = _query_training_sessions_for_day(current_user.id, day_start, day_end)
    snapspeaks_today = _query_snapspeaks_for_day(current_user.id, day_start, day_end)

    recommended_action = "session" if sessions_today == 0 else "snapspeak"

    return jsonify(
        {
            "readiness_score": readiness_score,
            "current_pgi": current_pgi,
            "pgi_direction": pgi_direction,
            "recommended_action": recommended_action,
            "sessions_today": sessions_today,
            "snapspeaks_today": snapspeaks_today,
        }
    )


@api_bp.post("/session/<int:session_id>/audio-chunk")
@login_required
def session_audio_chunk(session_id):
    csrf_error = _validate_csrf_if_enabled()
    if csrf_error is not None:
        return csrf_error

    session, error_response = _get_session_for_user(session_id, current_user.id)
    if error_response is not None:
        return error_response

    if session.status != "recording":
        return jsonify({"error": "Session is not accepting audio chunks."}), 409

    if request.is_json:
        payload = request.get_json(silent=True) or {}
        injection_payload = _parse_injection_event_payload(payload.get("injection_event"))
        if injection_payload is None:
            return jsonify({"error": "No injection event payload provided."}), 400

        _log_injection_event(session, injection_payload)
        return jsonify({"status": "received", "chunk_index": None})

    chunk_file = request.files.get("chunk")
    chunk_index = request.form.get("chunk_index", type=int)
    injection_payload = _parse_injection_event_payload(request.form.get("injection_event"))

    if injection_payload is not None:
        _log_injection_event(session, injection_payload)

    if chunk_file is None:
        if injection_payload is not None:
            return jsonify({"status": "received", "chunk_index": None})
        return jsonify({"error": "Audio chunk is required."}), 400

    if chunk_index is None or chunk_index < 0:
        return jsonify({"error": "chunk_index must be a non-negative integer."}), 400

    mime_type = (chunk_file.mimetype or "").split(";")[0].strip().lower()
    if mime_type not in ALLOWED_SESSION_CHUNK_MIME_TYPES:
        return jsonify({"error": f"Unsupported audio MIME type: {chunk_file.mimetype}"}), 400

    chunk_size = _get_uploaded_file_size(chunk_file)
    if chunk_size > MAX_SESSION_CHUNK_BYTES:
        return jsonify({"error": "Audio chunk exceeds 2MB limit."}), 413

    chunk_bytes = chunk_file.read()
    if not chunk_bytes:
        return jsonify({"error": "Audio chunk payload is empty."}), 400

    chunk_key = f"session:{session_id}:chunk:{chunk_index:04d}"
    count_key = f"session:{session_id}:chunk_count"

    try:
        redis_client = _get_redis_client()
        redis_client.setex(chunk_key, SESSION_CHUNK_TTL_SECONDS, chunk_bytes)
        redis_client.incr(count_key)
        redis_client.expire(count_key, SESSION_CHUNK_TTL_SECONDS)
    except redis.RedisError as exc:
        return jsonify({"error": f"Unable to persist audio chunk: {exc}"}), 503

    return jsonify({"status": "received", "chunk_index": chunk_index})


@api_bp.post("/session/<int:session_id>/complete")
@login_required
def complete_session(session_id):
    csrf_error = _validate_csrf_if_enabled()
    if csrf_error is not None:
        return csrf_error

    session, error_response = _get_session_for_user(session_id, current_user.id)
    if error_response is not None:
        return error_response

    if session.status == "completed":
        return jsonify(
            {
                "status": "completed",
                "redirect": url_for("sessions.summary", session_id=session.id),
            }
        )

    payload = request.get_json(silent=True) or {}
    early_exit = bool(payload.get("early_exit", False))
    early_exit_reason = (payload.get("early_exit_reason") or "").strip() or None
    injection_fired = bool(payload.get("injection_fired", False))

    session.early_exit = early_exit
    session.early_exit_reason = early_exit_reason[:100] if early_exit_reason else None
    session.injection_actually_fired = bool(session.injection_actually_fired or injection_fired)
    session.status = "processing"
    session.completed_at = datetime.utcnow()

    try:
        from app.tasks import analyze_session_audio

        async_task = analyze_session_audio.delay(session.id)
        session.celery_task_id = async_task.id
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": f"Unable to queue session analysis: {exc}"}), 500

    return jsonify(
        {
            "status": "processing",
            "task_id": session.celery_task_id,
            "redirect_poll": url_for("api.session_status", session_id=session_id),
        }
    )


@api_bp.get("/session/<int:session_id>/status")
@login_required
def session_status(session_id):
    session, error_response = _get_session_for_user(session_id, current_user.id)
    if error_response is not None:
        return error_response

    if session.status == "processing":
        progress = 15
        if session.celery_task_id:
            async_result = celery.AsyncResult(session.celery_task_id)
            if async_result.state == "PROGRESS":
                progress = int((async_result.info or {}).get("progress", 15))
            elif async_result.state == "STARTED":
                progress = 40
            elif async_result.state == "SUCCESS":
                progress = 95
            elif async_result.state == "FAILURE":
                return jsonify(
                    {
                        "status": "failed",
                        "message": session.error_message or "Session analysis failed.",
                    }
                )

        return jsonify({"status": "processing", "progress": max(1, min(99, progress))})

    if session.status == "completed":
        return jsonify(
            {
                "status": "completed",
                "redirect": url_for("sessions.summary", session_id=session.id),
            }
        )

    if session.status == "failed":
        return jsonify(
            {
                "status": "failed",
                "message": session.error_message or "Session analysis failed.",
            }
        )

    if session.status == "recording":
        return jsonify({"status": "recording"})

    return jsonify({"status": session.status})


@api_bp.get("/cohort/percentiles")
@login_required
def cohort_percentiles():
    data = cohort_service.get_user_cohort_percentiles(current_user.id)
    return jsonify(data)


@api_bp.post("/certificate/generate")
@login_required
def api_generate_certificate():
    eligibility_data = certificate_generator.check_eligibility(current_user.id)
    if not eligibility_data.get("eligible"):
        return jsonify({"error": "Not eligible", "details": eligibility_data}), 403

    certificate = certificate_generator.generate_certificate(current_user.id)
    return jsonify(
        {
            "status": "generated",
            "certificate_id": certificate.id,
            "download_url": url_for("certificate.download"),
            "share_url": certificate.share_url,
        }
    )


@api_bp.get("/subscription/status")
@login_required
def subscription_status():
    data = payment_service.get_subscription_status(current_user.id)
    return jsonify(data)


@api_bp.get("/audio/serve/<path:filename>")
@login_required
def serve_local_audio(filename):
    safe_filename = filename.replace("\\", "/").lstrip("/")
    user_prefix = f"{current_user.id}/"
    if not safe_filename.startswith(user_prefix):
        abort(403)

    if any(segment == ".." for segment in safe_filename.split("/") if segment):
        abort(400)

    uploads_root = os.path.join(current_app.root_path, "uploads", "audio")
    local_path = os.path.join(uploads_root, safe_filename)
    if not os.path.exists(local_path):
        abort(404)

    return send_file(local_path, as_attachment=False, conditional=True)


@api_bp.get("/audio/download/<path:filename>")
@login_required
def download_local_audio(filename):
    safe_filename = filename.replace("\\", "/").lstrip("/")
    user_prefix = f"{current_user.id}/"
    if not safe_filename.startswith(user_prefix):
        abort(403)

    if any(segment == ".." for segment in safe_filename.split("/") if segment):
        abort(400)

    uploads_root = os.path.join(current_app.root_path, "uploads", "audio")
    local_path = os.path.join(uploads_root, safe_filename)
    if not os.path.exists(local_path):
        abort(404)

    download_name = os.path.basename(safe_filename)
    return send_file(local_path, as_attachment=True, download_name=download_name, conditional=False)
