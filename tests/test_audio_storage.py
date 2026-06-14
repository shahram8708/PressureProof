from pathlib import Path

import pytest
from flask import Flask

from app.services import audio_storage


def _build_test_app(tmp_path, **config):
    application = Flask("audio-storage-tests", root_path=str(tmp_path))
    application.config.update(config)
    return application


def test_upload_audio_uses_local_backend_even_if_s3_settings_exist(monkeypatch, tmp_path):
    app = _build_test_app(
        tmp_path,
        STORAGE_BACKEND="local",
        AWS_ACCESS_KEY_ID="key",
        AWS_SECRET_ACCESS_KEY="secret",
        AWS_DEFAULT_REGION="ap-south-1",
        S3_BUCKET_NAME="bucket",
    )

    source_file = tmp_path / "sample.webm"
    source_file.write_bytes(b"audio-bytes")

    def _unexpected_client(*args, **kwargs):
        raise AssertionError("boto3.client should not be called for local storage")

    monkeypatch.setattr(audio_storage.boto3, "client", _unexpected_client)

    with app.app_context():
        storage_path = audio_storage.upload_audio(str(source_file), user_id=42, record_type="session")

    assert storage_path.startswith("uploads/audio/42/session/")
    saved_file = tmp_path / Path(storage_path)
    assert saved_file.exists()


def test_get_audio_download_url_uses_local_download_route(tmp_path):
    app = _build_test_app(
        tmp_path,
        STORAGE_BACKEND="local",
        SERVER_NAME="localhost",
    )

    with app.test_request_context():
        download_url = audio_storage.get_audio_download_url("uploads/audio/42/session/sample.wav")

    assert download_url == "http://localhost/api/audio/download/42/session/sample.wav"


def test_upload_audio_uses_s3_backend_in_s3_mode(monkeypatch, tmp_path):
    app = _build_test_app(
        tmp_path,
        STORAGE_BACKEND="s3",
        AWS_ACCESS_KEY_ID="key",
        AWS_SECRET_ACCESS_KEY="secret",
        AWS_DEFAULT_REGION="ap-south-1",
        S3_BUCKET_NAME="pressureproof-audio",
    )

    source_file = tmp_path / "sample.webm"
    source_file.write_bytes(b"audio-bytes")

    captured = {}

    class FakeS3Client:
        def upload_file(self, file_path, bucket, key, ExtraArgs=None):
            captured["file_path"] = file_path
            captured["bucket"] = bucket
            captured["key"] = key
            captured["extra"] = ExtraArgs

    def _fake_client(service_name, aws_access_key_id, aws_secret_access_key, region_name):
        captured["service_name"] = service_name
        captured["aws_access_key_id"] = aws_access_key_id
        captured["aws_secret_access_key"] = aws_secret_access_key
        captured["region_name"] = region_name
        return FakeS3Client()

    monkeypatch.setattr(audio_storage.boto3, "client", _fake_client)

    with app.app_context():
        storage_path = audio_storage.upload_audio(str(source_file), user_id=99, record_type="assessment")

    assert storage_path.startswith("audio/99/assessment/")
    assert captured["service_name"] == "s3"
    assert captured["bucket"] == "pressureproof-audio"
    assert captured["region_name"] == "ap-south-1"
    assert captured["extra"] == {"ServerSideEncryption": "AES256"}


def test_upload_audio_in_s3_mode_requires_complete_s3_config(tmp_path):
    app = _build_test_app(
        tmp_path,
        STORAGE_BACKEND="s3",
        AWS_ACCESS_KEY_ID="",
        AWS_SECRET_ACCESS_KEY="",
        AWS_DEFAULT_REGION="",
        S3_BUCKET_NAME="",
    )

    source_file = tmp_path / "sample.webm"
    source_file.write_bytes(b"audio-bytes")

    with app.app_context():
        with pytest.raises(RuntimeError, match="S3 storage backend is enabled but missing configuration"):
            audio_storage.upload_audio(str(source_file), user_id=1, record_type="session")
