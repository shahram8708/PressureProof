import logging
import os
import shutil
from datetime import datetime, timedelta
from uuid import uuid4

import boto3
from flask import current_app, url_for

from app.models import Assessment


logger = logging.getLogger(__name__)


def _storage_backend() -> str:
    backend = str(current_app.config.get("STORAGE_BACKEND", "local")).strip().lower()
    if backend not in {"local", "s3"}:
        logger.warning("Invalid STORAGE_BACKEND=%s, falling back to local", backend)
        return "local"
    return backend


def _use_s3_for_new_uploads() -> bool:
    return _storage_backend() == "s3"


def _normalize_storage_path(storage_path: str) -> str:
    return (storage_path or "").replace("\\", "/").lstrip("/")


def _is_local_storage_path(storage_path: str) -> bool:
    normalized = _normalize_storage_path(storage_path)
    return normalized.startswith("uploads/")


def _validate_relative_path(path: str):
    segments = [segment for segment in path.split("/") if segment]
    if any(segment == ".." for segment in segments):
        raise ValueError("Path traversal is not allowed")


def _get_s3_settings(require_config: bool = True) -> dict:
    settings = {
        "access_key_id": current_app.config.get("AWS_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID"),
        "secret_access_key": current_app.config.get("AWS_SECRET_ACCESS_KEY")
        or os.getenv("AWS_SECRET_ACCESS_KEY"),
        "region": current_app.config.get("AWS_REGION")
        or current_app.config.get("AWS_DEFAULT_REGION")
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION"),
        "bucket_name": current_app.config.get("S3_BUCKET_NAME") or os.getenv("S3_BUCKET_NAME"),
    }

    if require_config:
        missing = []
        if not settings["access_key_id"]:
            missing.append("AWS_ACCESS_KEY_ID")
        if not settings["secret_access_key"]:
            missing.append("AWS_SECRET_ACCESS_KEY")
        if not settings["region"]:
            missing.append("AWS_REGION/AWS_DEFAULT_REGION")
        if not settings["bucket_name"]:
            missing.append("S3_BUCKET_NAME")

        if missing:
            raise RuntimeError(
                "S3 storage backend is enabled but missing configuration: " + ", ".join(missing)
            )

    return settings


def _get_s3_client(require_config: bool = True):
    settings = _get_s3_settings(require_config=require_config)

    if not require_config and not all(
        [
            settings["access_key_id"],
            settings["secret_access_key"],
            settings["region"],
            settings["bucket_name"],
        ]
    ):
        return None

    return boto3.client(
        "s3",
        aws_access_key_id=settings["access_key_id"],
        aws_secret_access_key=settings["secret_access_key"],
        region_name=settings["region"],
    )


def _s3_bucket_name(require_config: bool = True):
    settings = _get_s3_settings(require_config=require_config)
    if not require_config and not settings["bucket_name"]:
        return None
    return settings["bucket_name"]


def _uploads_audio_root():
    return os.path.join(current_app.root_path, "uploads", "audio")


def upload_audio(file_path: str, user_id: int, record_type: str) -> str:
    if _use_s3_for_new_uploads():
        s3_key = f"audio/{user_id}/{record_type}/{uuid4().hex}_{os.path.basename(file_path)}"
        client = _get_s3_client(require_config=True)
        client.upload_file(
            file_path,
            _s3_bucket_name(require_config=True),
            s3_key,
            ExtraArgs={"ServerSideEncryption": "AES256"},
        )
        logger.info("Stored audio using S3 key=%s", s3_key)
        return s3_key

    local_dir = os.path.join(_uploads_audio_root(), str(user_id), record_type)
    os.makedirs(local_dir, exist_ok=True)

    filename = f"{uuid4().hex}_{os.path.basename(file_path)}"
    destination = os.path.join(local_dir, filename)
    shutil.copy2(file_path, destination)

    relative_path = os.path.join("uploads", "audio", str(user_id), record_type, filename).replace(
        "\\", "/"
    )
    logger.info("Stored audio using local filesystem path=%s", relative_path)
    return relative_path


def get_audio_url(storage_path: str, expiry_seconds: int = 900):
    normalized = _normalize_storage_path(storage_path)
    if not normalized:
        return None

    if not _is_local_storage_path(normalized):
        client = _get_s3_client(require_config=False)
        bucket_name = _s3_bucket_name(require_config=False)
        if client is None or not bucket_name:
            logger.warning("Unable to generate S3 URL because S3 configuration is missing")
            return None

        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": normalized},
            ExpiresIn=int(expiry_seconds),
        )

    local_prefix = "uploads/audio/"
    filename = normalized
    if filename.startswith(local_prefix):
        filename = filename[len(local_prefix) :]
    else:
        logger.warning("Local audio path does not match expected prefix: %s", normalized)
        return None

    return url_for("api.serve_local_audio", filename=filename, _external=True)


def get_audio_download_url(storage_path: str, expiry_seconds: int = 900):
    normalized = _normalize_storage_path(storage_path)
    if not normalized:
        return None

    if not _is_local_storage_path(normalized):
        client = _get_s3_client(require_config=False)
        bucket_name = _s3_bucket_name(require_config=False)
        if client is None or not bucket_name:
            logger.warning("Unable to generate S3 download URL because S3 configuration is missing")
            return None

        filename = os.path.basename(normalized) or "audio"
        return client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket_name,
                "Key": normalized,
                "ResponseContentDisposition": f'attachment; filename="{filename}"',
            },
            ExpiresIn=int(expiry_seconds),
        )

    local_prefix = "uploads/audio/"
    filename = normalized
    if filename.startswith(local_prefix):
        filename = filename[len(local_prefix) :]
    else:
        logger.warning("Local audio path does not match expected prefix: %s", normalized)
        return None

    return url_for("api.download_local_audio", filename=filename, _external=True)


def delete_audio(storage_path: str):
    normalized = _normalize_storage_path(storage_path)
    if not normalized:
        return

    if not _is_local_storage_path(normalized):
        client = _get_s3_client(require_config=False)
        bucket_name = _s3_bucket_name(require_config=False)
        if client is None or not bucket_name:
            logger.warning("Skipping S3 delete for key=%s because S3 is not configured", normalized)
            return

        client.delete_object(Bucket=bucket_name, Key=normalized)
        logger.info("Deleted S3 audio key=%s", normalized)
        return

    try:
        _validate_relative_path(normalized)
    except ValueError:
        logger.warning("Skipping invalid local storage path=%s", normalized)
        return

    full_path = os.path.join(current_app.root_path, normalized)
    if os.path.exists(full_path):
        os.remove(full_path)
        logger.info("Deleted local audio file=%s", full_path)


def cleanup_old_audio(max_age_hours: int = 72):
    cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
    deleted_count = 0

    old_assessments = Assessment.query.filter(Assessment.created_at < cutoff).all()
    for assessment in old_assessments:
        for path in [assessment.audio_path_prepared, assessment.audio_path_spontaneous]:
            if path:
                delete_audio(path)
                deleted_count += 1

    snapspeak_model = None
    try:
        from app.models import SnapSpeakRecord

        snapspeak_model = SnapSpeakRecord
    except Exception:
        try:
            from app.models import SnapSpeakCapture

            snapspeak_model = SnapSpeakCapture
        except Exception:
            snapspeak_model = None

    timestamp_column = None
    if snapspeak_model is not None:
        timestamp_column = getattr(snapspeak_model, "captured_at", None) or getattr(
            snapspeak_model,
            "created_at",
            None,
        )

    if snapspeak_model is not None and timestamp_column is not None:
        old_snap_records = snapspeak_model.query.filter(timestamp_column < cutoff).all()
        for record in old_snap_records:
            for field_name in ["audio_path", "audio_file_path", "audio_storage_path"]:
                if hasattr(record, field_name):
                    path = getattr(record, field_name)
                    if path:
                        delete_audio(path)
                        deleted_count += 1

    logger.info("Audio cleanup finished. Deleted %s files", deleted_count)
    return deleted_count


def store_audio_file(file_stream, object_key):
    if not file_stream:
        raise ValueError("file_stream is required")
    if not object_key:
        raise ValueError("object_key is required")

    normalized_key = _normalize_storage_path(object_key)
    if not normalized_key:
        raise ValueError("object_key is invalid")

    _validate_relative_path(normalized_key)

    if _use_s3_for_new_uploads():
        stream_obj = getattr(file_stream, "stream", file_stream)
        try:
            stream_obj.seek(0)
        except Exception:
            pass
        client = _get_s3_client(require_config=True)
        client.upload_fileobj(
            stream_obj,
            _s3_bucket_name(require_config=True),
            normalized_key,
            ExtraArgs={"ServerSideEncryption": "AES256"},
        )
        logger.info("Stored file stream using S3 key=%s", normalized_key)
        return normalized_key

    destination = os.path.join(current_app.root_path, "uploads", normalized_key)
    os.makedirs(os.path.dirname(destination), exist_ok=True)

    if hasattr(file_stream, "save"):
        file_stream.save(destination)
    else:
        stream_obj = getattr(file_stream, "stream", file_stream)
        try:
            stream_obj.seek(0)
        except Exception:
            pass
        with open(destination, "wb") as output_file:
            shutil.copyfileobj(stream_obj, output_file)

    relative_path = os.path.join("uploads", normalized_key).replace("\\", "/")
    logger.info("Stored file stream using local path=%s", relative_path)
    return relative_path


def upload_pdf(pdf_bytes: bytes, user_id: int) -> str:
    if not pdf_bytes:
        raise ValueError("pdf_bytes is required")

    filename = f"certificate_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid4().hex}.pdf"

    if _use_s3_for_new_uploads():
        s3_key = f"certificates/{user_id}/{filename}"
        client = _get_s3_client(require_config=True)
        client.put_object(
            Bucket=_s3_bucket_name(require_config=True),
            Key=s3_key,
            Body=pdf_bytes,
            ContentType="application/pdf",
            ServerSideEncryption="AES256",
        )
        logger.info("Stored certificate PDF in S3 key=%s", s3_key)
        return s3_key

    local_dir = os.path.join(current_app.root_path, "uploads", "certificates", str(user_id))
    os.makedirs(local_dir, exist_ok=True)
    destination = os.path.join(local_dir, filename)

    with open(destination, "wb") as pdf_file:
        pdf_file.write(pdf_bytes)

    relative_path = os.path.join("uploads", "certificates", str(user_id), filename).replace("\\", "/")
    logger.info("Stored certificate PDF locally path=%s", relative_path)
    return relative_path


def read_binary(storage_path: str):
    normalized = _normalize_storage_path(storage_path)
    if not normalized:
        return None

    if not _is_local_storage_path(normalized):
        client = _get_s3_client(require_config=False)
        bucket_name = _s3_bucket_name(require_config=False)
        if client is None or not bucket_name:
            logger.warning("Unable to read S3 object key=%s because S3 is not configured", normalized)
            return None

        response = client.get_object(Bucket=bucket_name, Key=normalized)
        return response["Body"].read()

    try:
        _validate_relative_path(normalized)
    except ValueError:
        logger.warning("Skipping invalid local storage path=%s", normalized)
        return None

    local_path = os.path.join(current_app.root_path, normalized)
    if not os.path.exists(local_path):
        return None

    with open(local_path, "rb") as binary_file:
        return binary_file.read()
