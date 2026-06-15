import logging
import os
import tempfile
import shutil

import opensmile
import whisper
from flask import current_app, has_app_context
from pydub import AudioSegment


logger = logging.getLogger(__name__)

_whisper_model = None
_whisper_model_name = None
_smile_instance = None
_ffmpeg_path = None


WHISPER_MODEL_PRIORITY = ["tiny", "base", "small", "medium"]


def _empty_analysis_result() -> dict:
    return {
        "transcript": "",
        "word_timestamps": [],
        "audio_features": None,
        "duration_seconds": 0.0,
        "word_count": 0,
        "segments": [],
    }


def _resolve_ffmpeg_path():
    global _ffmpeg_path

    if _ffmpeg_path is not None:
        return _ffmpeg_path

    configured_path = os.getenv("FFMPEG_BINARY") or os.getenv("IMAGEIO_FFMPEG_EXE")
    if not configured_path and has_app_context():
        configured_path = current_app.config.get("FFMPEG_BINARY")

    if configured_path and os.path.exists(configured_path):
        _ffmpeg_path = configured_path
        return _ffmpeg_path

    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        resolved_path = get_ffmpeg_exe()
        if resolved_path and os.path.exists(resolved_path):
            _ffmpeg_path = resolved_path
            return _ffmpeg_path
    except Exception:
        logger.debug("imageio_ffmpeg is not available for ffmpeg resolution", exc_info=True)

    resolved_path = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if resolved_path and os.path.exists(resolved_path):
        _ffmpeg_path = resolved_path
        return _ffmpeg_path

    _ffmpeg_path = None
    return _ffmpeg_path


def _configure_ffmpeg_backend():
    ffmpeg_path = _resolve_ffmpeg_path()
    if not ffmpeg_path:
        return False

    AudioSegment.converter = ffmpeg_path
    AudioSegment.ffmpeg = ffmpeg_path

    ffmpeg_dir = os.path.dirname(ffmpeg_path)
    if ffmpeg_dir and ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

    return True


def _get_whisper_model_candidates():
    configured_size = str(current_app.config.get("WHISPER_MODEL_SIZE", "base")).strip().lower()
    if configured_size not in WHISPER_MODEL_PRIORITY:
        configured_size = "base"

    configured_index = WHISPER_MODEL_PRIORITY.index(configured_size)
    return list(reversed(WHISPER_MODEL_PRIORITY[: configured_index + 1]))


def get_whisper_model():
    global _whisper_model
    global _whisper_model_name

    if _whisper_model is not None:
        return _whisper_model

    for model_size in _get_whisper_model_candidates():
        try:
            _whisper_model = whisper.load_model(model_size, in_memory=False)
            _whisper_model_name = model_size
            logger.info("Loaded Whisper model: %s", model_size)
            return _whisper_model
        except MemoryError:
            logger.warning("Whisper model %s used too much memory, trying a smaller model.", model_size)
        except Exception:
            logger.warning("Unable to load Whisper model %s, trying a smaller model.", model_size, exc_info=True)

    _whisper_model = None
    _whisper_model_name = None
    logger.warning("Whisper could not be loaded with any configured fallback model.")
    return None


def get_smile_instance():
    global _smile_instance
    if _smile_instance is None:
        _smile_instance = opensmile.Smile(
            feature_set=opensmile.FeatureSet.ComParE_2016,
            feature_level=opensmile.FeatureLevel.Functionals,
        )
    return _smile_instance


def convert_audio_to_wav(input_path: str) -> str:
    fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    _configure_ffmpeg_backend()

    audio_segment = AudioSegment.from_file(input_path)
    audio_segment.export(wav_path, format="wav")
    return wav_path


def analyze_audio(audio_path: str) -> dict:
    wav_path = None

    try:
        wav_path = convert_audio_to_wav(audio_path)
        model = get_whisper_model()
        transcript = ""
        segments = []

        if model is not None:
            try:
                result = model.transcribe(
                    wav_path,
                    word_timestamps=True,
                    verbose=False,
                    language="en",
                )
                transcript = (result.get("text") or "").strip()
                segments = result.get("segments") or []
            except MemoryError:
                logger.warning("Whisper transcription used too much memory for %s; continuing with empty transcript.", wav_path)
            except Exception:
                logger.exception("Whisper transcription failed for %s; continuing with empty transcript.", wav_path)

        word_timestamps = []
        for segment in segments:
            for word_data in segment.get("words", []):
                raw_word = str(word_data.get("word", "")).strip()
                if not raw_word:
                    continue
                word_timestamps.append(
                    {
                        "word": raw_word,
                        "start": float(word_data.get("start", 0.0)),
                        "end": float(word_data.get("end", 0.0)),
                    }
                )

        features_df = None
        try:
            smile = get_smile_instance()
            features_df = smile.process_file(wav_path)
        except Exception:
            logger.warning("OpenSMILE feature extraction failed for %s", wav_path, exc_info=True)
            features_df = None

        duration_seconds = 0.0
        if word_timestamps:
            duration_seconds = max(0.0, float(word_timestamps[-1].get("end", 0.0)))

        return {
            "transcript": transcript,
            "word_timestamps": word_timestamps,
            "audio_features": features_df,
            "duration_seconds": duration_seconds,
            "word_count": len(word_timestamps),
            "segments": segments,
        }
    except Exception:
        logger.exception("Audio analysis failed for %s; returning empty analysis", audio_path)
        return _empty_analysis_result()
    finally:
        try:
            if wav_path and os.path.exists(wav_path):
                os.remove(wav_path)
        except OSError:
            logger.warning("Unable to remove temporary wav file %s", wav_path, exc_info=True)


def analyze_speech_recording(audio_file_path, language="en"):
    return analyze_audio(audio_file_path)
