import logging
import io
import json
import os
import re
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from uuid import uuid4

from app import create_app
from app.extensions import celery, db
from app.models import Assessment, NotificationLog, SnapSpeakRecord, TrainingSession, User
import redis
from pydub import AudioSegment

from app.services.calibration_engine import compute_next_session
from app.services.audio_storage import delete_audio, upload_audio
from app.services import cohort_service
from app.services.failure_mode_detector import detect_primary_failure_mode
from app.services.lsrc_engine import compute_lsrc_scores
from app.services.notification_service import send_snapspeak_push, send_weekly_report_email
from app.services.pgi_calculator import compute_weekly_pgi
from app.services.speech_analyzer import analyze_audio
from app.utils.helpers import check_snapspeak_notable, generate_snapspeak_analysis_lines


logger = logging.getLogger(__name__)
_task_app = None
celery_app = celery


def _get_task_app():
    global _task_app
    if _task_app is None:
        config_name = (
            os.getenv("FLASK_CONFIG")
            or os.getenv("FLASK_ENV")
            or "default"
        )
        _task_app = create_app(config_name)
    return _task_app


def _get_redis_client(flask_app):
    redis_url = (
        flask_app.config.get("REDIS_URL")
        or flask_app.config.get("CELERY_BROKER_URL")
        or os.getenv("REDIS_URL")
        or "redis://localhost:6379/0"
    )
    return redis.Redis.from_url(redis_url, decode_responses=False)


def _build_topic_vector(transcript):
    text = (transcript or "").strip()
    if not text:
        return None

    try:
        tokens = re.findall(r"[a-z0-9']+", text.lower())
        if not tokens:
            return None

        terms = list(tokens)
        terms.extend(f"{tokens[index]} {tokens[index + 1]}" for index in range(len(tokens) - 1))

        counts = Counter(terms)
        total = float(sum(counts.values()))
        if total == 0:
            return None

        entries = [(token, round(count / total, 6)) for token, count in counts.items()]

        entries.sort(key=lambda item: item[1], reverse=True)
        return json.dumps(dict(entries[:30]))
    except Exception:
        logger.exception("Unable to compute transcript TF-IDF topic vector")
        return None


def _is_time_within_window(current_time, start_time, end_time):
    if start_time <= end_time:
        return start_time <= current_time <= end_time
    return current_time >= start_time or current_time <= end_time


@celery.task(
    bind=True,
    name="tasks.analyze_baseline_audio",
    time_limit=300,
    soft_time_limit=240,
    queue="speech_analysis",
)
def analyze_baseline_audio(
    self,
    audio_path_prepared: str,
    audio_path_spontaneous: str,
    assessment_id: int,
    user_id: int,
):
    flask_app = _get_task_app()

    with flask_app.app_context():
        assessment = Assessment.query.get(assessment_id)

        try:
            self.update_state(state="PROGRESS", meta={"progress": 5})
            if assessment is None:
                raise ValueError(f"Assessment {assessment_id} was not found.")

            assessment.status = "processing"
            assessment.error_message = None
            db.session.commit()

            self.update_state(state="PROGRESS", meta={"progress": 15})
            prepared_analysis = analyze_audio(audio_path_prepared)

            self.update_state(state="PROGRESS", meta={"progress": 35})
            spontaneous_analysis = analyze_audio(audio_path_spontaneous)

            self.update_state(state="PROGRESS", meta={"progress": 55})
            compute_lsrc_scores(
                prepared_analysis,
                user_id=user_id,
                source_type="assessment",
                source_id=assessment_id,
                condition="prepared",
            )

            self.update_state(state="PROGRESS", meta={"progress": 65})
            compute_lsrc_scores(
                spontaneous_analysis,
                user_id=user_id,
                source_type="assessment",
                source_id=assessment_id,
                condition="spontaneous",
            )

            self.update_state(state="PROGRESS", meta={"progress": 75})
            assessment.transcript_prepared = prepared_analysis.get("transcript")
            assessment.transcript_spontaneous = spontaneous_analysis.get("transcript")
            assessment.duration_prepared = int(round(prepared_analysis.get("duration_seconds", 0.0)))
            assessment.duration_spontaneous = int(
                round(spontaneous_analysis.get("duration_seconds", 0.0))
            )

            self.update_state(state="PROGRESS", meta={"progress": 82})
            assessment.audio_path_prepared = upload_audio(
                audio_path_prepared,
                user_id=user_id,
                record_type="assessment_prepared",
            )
            assessment.audio_path_spontaneous = upload_audio(
                audio_path_spontaneous,
                user_id=user_id,
                record_type="assessment_spontaneous",
            )

            self.update_state(state="PROGRESS", meta={"progress": 90})
            detect_primary_failure_mode(user_id)

            assessment.status = "completed"
            assessment.error_message = None
            db.session.commit()

            self.update_state(state="PROGRESS", meta={"progress": 100})
            return {
                "status": "completed",
                "assessment_id": assessment_id,
                "user_id": user_id,
            }
        except Exception as exc:
            logger.exception("Baseline analysis task failed for assessment %s", assessment_id)
            if assessment is not None:
                assessment.status = "failed"
                assessment.error_message = str(exc)
                db.session.commit()
            raise
        finally:
            for temp_path in [audio_path_prepared, audio_path_spontaneous]:
                try:
                    if temp_path and os.path.exists(temp_path):
                        os.remove(temp_path)
                except OSError:
                    logger.warning("Unable to clean temp file %s", temp_path, exc_info=True)


@celery.task(
    bind=True,
    name="tasks.analyze_session_audio",
    time_limit=300,
    soft_time_limit=240,
    queue="speech_analysis",
)
def analyze_session_audio(self, session_id: int):
    flask_app = _get_task_app()

    redis_client = None
    chunk_count = 0
    temp_wav_path = None

    with flask_app.app_context():
        session = TrainingSession.query.get(session_id)

        try:
            if session is None:
                raise ValueError(f"Training session {session_id} was not found.")

            session.status = "processing"
            session.error_message = None
            db.session.commit()
            self.update_state(state="PROGRESS", meta={"progress": 5})

            redis_client = _get_redis_client(flask_app)
            count_key = f"session:{session_id}:chunk_count"
            raw_count = redis_client.get(count_key)
            chunk_count = int(raw_count or 0)

            chunk_payloads = []
            for index in range(chunk_count):
                chunk_key = f"session:{session_id}:chunk:{index:04d}"
                chunk_bytes = redis_client.get(chunk_key)
                if chunk_bytes is None:
                    logger.warning(
                        "Session %s chunk %s is missing during assembly.",
                        session_id,
                        index,
                    )
                    continue
                chunk_payloads.append(chunk_bytes)

            if not chunk_payloads:
                raise ValueError("No audio chunks were found for this session.")

            self.update_state(state="PROGRESS", meta={"progress": 15})

            combined_audio = AudioSegment.silent(duration=0)
            for chunk_bytes in chunk_payloads:
                segment = None
                for fmt in ["webm", "ogg", "mp4"]:
                    try:
                        segment = AudioSegment.from_file(io.BytesIO(chunk_bytes), format=fmt)
                        break
                    except Exception:
                        segment = None

                if segment is None:
                    logger.warning("Unable to decode one session chunk; skipping it.")
                    continue

                combined_audio += segment

            tmp_dir = "/tmp"
            os.makedirs(tmp_dir, exist_ok=True)
            temp_wav_path = os.path.join(tmp_dir, f"{uuid4().hex}.wav")
            combined_audio.export(temp_wav_path, format="wav")
            self.update_state(state="PROGRESS", meta={"progress": 30})

            analysis_result = analyze_audio(temp_wav_path)
            self.update_state(state="PROGRESS", meta={"progress": 60})

            compute_lsrc_scores(
                analysis_result,
                user_id=session.user_id,
                source_type="session",
                source_id=session_id,
                condition="prepared",
            )
            self.update_state(state="PROGRESS", meta={"progress": 75})

            session.audio_path = upload_audio(temp_wav_path, user_id=session.user_id, record_type="session")
            session.transcript = analysis_result.get("transcript")
            session.topic_vector = _build_topic_vector(session.transcript)

            compute_weekly_pgi(session.user_id)
            self.update_state(state="PROGRESS", meta={"progress": 85})

            compute_next_session(session.user_id)

            session.status = "completed"
            session.completed_at = datetime.utcnow()
            session.error_message = None
            db.session.commit()
            self.update_state(state="PROGRESS", meta={"progress": 100})

            return {
                "status": "completed",
                "session_id": session_id,
                "user_id": session.user_id,
            }
        except Exception as exc:
            logger.exception("Session analysis task failed for session %s", session_id)
            db.session.rollback()

            failed_session = TrainingSession.query.get(session_id)
            if failed_session is not None:
                failed_session.status = "failed"
                failed_session.error_message = str(exc)
                db.session.commit()
            raise
        finally:
            if redis_client is not None:
                try:
                    chunk_pattern = f"session:{session_id}:chunk:*"
                    chunk_keys = list(redis_client.scan_iter(match=chunk_pattern))
                    if chunk_keys:
                        redis_client.delete(*chunk_keys)
                    redis_client.delete(f"session:{session_id}:chunk_count")
                except Exception:
                    logger.warning(
                        "Unable to cleanup Redis chunks for session %s", session_id, exc_info=True
                    )

            if temp_wav_path and os.path.exists(temp_wav_path):
                try:
                    os.remove(temp_wav_path)
                except OSError:
                    logger.warning(
                        "Unable to clean temporary session audio %s", temp_wav_path, exc_info=True
                    )


@celery.task(
    bind=True,
    name="tasks.analyze_snapspeak_audio",
    time_limit=180,
    soft_time_limit=150,
    queue="speech_analysis",
)
def analyze_snapspeak_audio(self, temp_audio_path: str, snapspeak_id: int, user_id: int):
    flask_app = _get_task_app()

    with flask_app.app_context():
        try:
            snapspeak_record = SnapSpeakRecord.query.get(snapspeak_id)
            if snapspeak_record is None:
                raise ValueError(f"SnapSpeak record {snapspeak_id} was not found.")
            if snapspeak_record.user_id != user_id:
                raise ValueError("SnapSpeak record does not belong to provided user.")

            snapspeak_record.status = "processing"
            snapspeak_record.error_message = None
            db.session.commit()
            self.update_state(state="PROGRESS", meta={"progress": 5})

            analysis_result = analyze_audio(temp_audio_path)
            self.update_state(state="PROGRESS", meta={"progress": 40})

            lsrc_score = compute_lsrc_scores(
                analysis_result,
                user_id=user_id,
                source_type="snapspeak",
                source_id=snapspeak_id,
                condition="spontaneous",
            )
            self.update_state(state="PROGRESS", meta={"progress": 60})

            line_1, line_2, line_3 = generate_snapspeak_analysis_lines(lsrc_score, user_id)
            snapspeak_record.analysis_line_1 = line_1
            snapspeak_record.analysis_line_2 = line_2
            snapspeak_record.analysis_line_3 = line_3

            is_notable, annotation = check_snapspeak_notable(lsrc_score, user_id)
            snapspeak_record.is_notable = bool(is_notable)
            snapspeak_record.notable_annotation = annotation or None

            snapspeak_record.audio_path = upload_audio(
                temp_audio_path,
                user_id=user_id,
                record_type="snapspeak",
            )

            snapspeak_record.transcript = analysis_result.get("transcript")
            snapspeak_record.topic_vector = _build_topic_vector(snapspeak_record.transcript)

            compute_weekly_pgi(user_id)
            self.update_state(state="PROGRESS", meta={"progress": 85})

            detect_primary_failure_mode(user_id)

            duration_seconds = analysis_result.get("duration_seconds")
            snapspeak_record.duration_seconds = int(round(float(duration_seconds or 0.0)))
            snapspeak_record.status = "completed"
            snapspeak_record.error_message = None
            db.session.commit()
            self.update_state(state="PROGRESS", meta={"progress": 100})

            return {
                "status": "completed",
                "snapspeak_id": snapspeak_id,
                "user_id": user_id,
            }
        except Exception as exc:
            logger.exception("SnapSpeak analysis task failed for record %s", snapspeak_id)
            db.session.rollback()

            failed_record = SnapSpeakRecord.query.get(snapspeak_id)
            if failed_record is not None:
                failed_record.status = "failed"
                failed_record.error_message = str(exc)
                db.session.commit()
            raise
        finally:
            try:
                if temp_audio_path and os.path.exists(temp_audio_path):
                    os.remove(temp_audio_path)
            except OSError:
                logger.warning("Unable to clean temp file %s", temp_audio_path, exc_info=True)


@celery.task(name="tasks.send_snapspeak_notifications", queue="lsrc_update")
def send_snapspeak_notifications():
    flask_app = _get_task_app()

    with flask_app.app_context():
        now_aware = datetime.now(timezone.utc)
        now_naive = now_aware.replace(tzinfo=None)
        current_time = now_aware.time().replace(tzinfo=None)

        eligible_users = User.query.filter_by(
            email_verified=True,
            onboarding_complete=True,
            snapspeak_opted_in=True,
        ).all()

        sent_count = 0
        six_hours_ago = now_naive - timedelta(hours=6)

        for user in eligible_users:
            start_time = user.preferred_snapspeak_start or time(9, 0)
            end_time = user.preferred_snapspeak_end or time(18, 0)

            if not _is_time_within_window(current_time, start_time, end_time):
                continue

            recent_notification = (
                NotificationLog.query.filter(
                    NotificationLog.user_id == user.id,
                    NotificationLog.notification_type == "snapspeak",
                    NotificationLog.sent_at.isnot(None),
                    NotificationLog.sent_at >= six_hours_ago,
                )
                .order_by(NotificationLog.sent_at.desc())
                .first()
            )
            if recent_notification is not None:
                continue

            sent = send_snapspeak_push(user)
            if not sent:
                continue

            endpoint = None
            active_subscription = user.push_subscriptions.filter_by(is_active=True).first()
            if active_subscription is not None:
                endpoint = active_subscription.endpoint

            db.session.add(
                NotificationLog(
                    user_id=user.id,
                    notification_type="snapspeak",
                    scheduled_at=now_naive,
                    sent_at=now_naive,
                    push_subscription_endpoint=endpoint,
                )
            )
            sent_count += 1

        db.session.commit()
        logger.info(
            "Sent SnapSpeak notifications to %s of %s eligible users.",
            sent_count,
            len(eligible_users),
        )
        return {
            "sent_count": sent_count,
            "eligible_users": len(eligible_users),
        }


@celery.task(name="tasks.weekly_pgi_recalculation", queue="lsrc_update")
def weekly_pgi_recalculation():
    flask_app = _get_task_app()

    with flask_app.app_context():
        users = User.query.filter_by(email_verified=True, onboarding_complete=True).all()
        updated_count = 0

        for user in users:
            try:
                compute_weekly_pgi(user.id)
                updated_count += 1
            except Exception:
                db.session.rollback()
                logger.exception("Weekly PGI recalculation failed for user %s", user.id)

        try:
            redis_client = _get_redis_client(flask_app)
            redis_client.set("last_weekly_pgi_recalculation", datetime.utcnow().isoformat())
        except Exception:
            logger.warning("Unable to write last_weekly_pgi_recalculation timestamp", exc_info=True)

        logger.info("Weekly PGI recalculation completed. Updated users: %s", updated_count)
        return {"updated_users": updated_count}


def _estimate_local_file_size_bytes(flask_app, storage_path):
    if not storage_path:
        return 0
    normalized = storage_path.replace("\\", "/")
    if normalized.startswith("audio/") or normalized.startswith("certificates/"):
        return 0
    full_path = os.path.join(flask_app.root_path, normalized)
    if not os.path.exists(full_path):
        return 0
    try:
        return os.path.getsize(full_path)
    except OSError:
        return 0


@celery.task(name="tasks.daily_audio_cleanup", queue="lsrc_update")
def daily_audio_cleanup():
    flask_app = _get_task_app()

    with flask_app.app_context():
        cutoff = datetime.utcnow() - timedelta(hours=72)
        cleaned_count = 0
        freed_bytes = 0

        old_assessments = Assessment.query.filter(Assessment.created_at < cutoff).all()
        for assessment in old_assessments:
            for field_name in ["audio_path_prepared", "audio_path_spontaneous"]:
                path = getattr(assessment, field_name, None)
                if path:
                    freed_bytes += _estimate_local_file_size_bytes(flask_app, path)
                    try:
                        delete_audio(path)
                    except Exception:
                        logger.warning("Unable to delete assessment audio %s", path, exc_info=True)
                    setattr(assessment, field_name, None)
                    cleaned_count += 1

        old_sessions = TrainingSession.query.filter(
            TrainingSession.completed_at.isnot(None),
            TrainingSession.completed_at < cutoff,
            TrainingSession.audio_path.isnot(None),
        ).all()
        for training_session in old_sessions:
            path = training_session.audio_path
            freed_bytes += _estimate_local_file_size_bytes(flask_app, path)
            try:
                delete_audio(path)
            except Exception:
                logger.warning("Unable to delete session audio %s", path, exc_info=True)
            training_session.audio_path = None
            cleaned_count += 1

        old_snapspeaks = SnapSpeakRecord.query.filter(
            SnapSpeakRecord.captured_at < cutoff,
            SnapSpeakRecord.audio_path.isnot(None),
        ).all()
        for record in old_snapspeaks:
            path = record.audio_path
            freed_bytes += _estimate_local_file_size_bytes(flask_app, path)
            try:
                delete_audio(path)
            except Exception:
                logger.warning("Unable to delete snapspeak audio %s", path, exc_info=True)
            record.audio_path = None
            cleaned_count += 1

        db.session.commit()

        try:
            redis_client = _get_redis_client(flask_app)
            redis_client.set("last_audio_cleanup", datetime.utcnow().isoformat())
        except Exception:
            logger.warning("Unable to write last_audio_cleanup timestamp", exc_info=True)

        freed_mb = round(freed_bytes / (1024 * 1024), 2)
        logger.info("Cleaned up %s audio files. Freed approximately %s MB of storage.", cleaned_count, freed_mb)
        return {"cleaned_files": cleaned_count, "freed_mb": freed_mb}


@celery.task(name="tasks.nightly_cohort_rebuild", queue="lsrc_update")
def nightly_cohort_rebuild():
    flask_app = _get_task_app()

    with flask_app.app_context():
        result = cohort_service.rebuild_cohort_aggregates()
        try:
            redis_client = _get_redis_client(flask_app)
            redis_client.set("last_cohort_rebuild", datetime.utcnow().isoformat())
        except Exception:
            logger.warning("Unable to write last_cohort_rebuild timestamp", exc_info=True)

        logger.info("Nightly cohort rebuild completed. %s", result)
        return result


@celery.task(name="tasks.weekly_report_email", queue="lsrc_update")
def weekly_report_email():
    flask_app = _get_task_app()

    with flask_app.app_context():
        paid_users = User.query.filter(User.subscription_tier.in_(["professional", "pro_annual"])).all()
        sent_count = 0
        for user in paid_users:
            if send_weekly_report_email(user):
                sent_count += 1

        try:
            redis_client = _get_redis_client(flask_app)
            redis_client.set("last_weekly_report_email", datetime.utcnow().isoformat())
        except Exception:
            logger.warning("Unable to write last_weekly_report_email timestamp", exc_info=True)

        logger.info("Weekly report emails sent to %s of %s paid users.", sent_count, len(paid_users))
        return {"sent_count": sent_count, "paid_users": len(paid_users)}
