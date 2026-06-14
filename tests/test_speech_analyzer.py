import os

from app.services import speech_analyzer


def test_analyze_audio_returns_empty_result_when_conversion_fails(tmp_path, monkeypatch):
    source_file = tmp_path / "sample.webm"
    source_file.write_bytes(b"not-real-audio")

    def _raise_conversion_error(*args, **kwargs):
        raise RuntimeError("ffmpeg unavailable")

    monkeypatch.setattr(speech_analyzer, "convert_audio_to_wav", _raise_conversion_error)

    result = speech_analyzer.analyze_audio(str(source_file))

    assert result["transcript"] == ""
    assert result["word_timestamps"] == []
    assert result["audio_features"] is None
    assert result["duration_seconds"] == 0.0
    assert result["word_count"] == 0
    assert result["segments"] == []