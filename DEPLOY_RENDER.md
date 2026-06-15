Render deployment notes — web + worker

Overview
- Split dependencies: lightweight `requirements.txt` for the web process, heavy ML/audio packages in `requirements-worker.txt` for a separate worker. This avoids installing large packages (and running heavy model loads) on the web dyno, preventing memory OOM.
- Key code changes: lazy-loading of spaCy and Whisper/OpenSMILE/pydub in `app/utils/nlp_helpers.py` and `app/services/speech_analyzer.py`. Also added `app = application` alias in `wsgi.py` so `gunicorn wsgi:app` works.

Web service (Render service)
- Build Command:
```bash
pip install -r requirements.txt
```
- Start Command (matches your existing command):
```bash
gunicorn wsgi:app --workers 3 --bind 0.0.0.0:$PORT --log-file -
```
- Recommended plan: small (512MB–1GB) unless you need more.
- Env vars to set in Render:
  - `FLASK_ENV=production`
  - `REDIS_URL` (if using Redis)
  - `DATABASE_URL` (Postgres)
  - `WHISPER_MODEL_SIZE` (optional; worker will use this)
  - `FFMPEG_BINARY` (optional)

Worker service (background service / separate Render service)
- Purpose: install heavy ML/audio libraries and run background tasks (Celery, model loads, transcription).
- Create a separate service on Render (type: Background Worker or Private Service).
- Build Command:
```bash
pip install -r requirements-worker.txt
```
- Start Command (example for Celery worker):
```bash
celery -A app.extensions.celery worker --loglevel=info
```
(If that form fails, try `celery -A app.extensions:celery worker --loglevel=info`.)
- Recommended plan: large (4GB–16GB) depending on the Whisper model size and number of workers.
- Important env vars for the worker:
  - `WHISPER_MODEL_SIZE=tiny|base|small|medium` (start with `tiny` for less memory)
  - `REDIS_URL`
  - `FFMPEG_BINARY` (if custom ffmpeg)

Why this prevents OOM on Render
- The web service no longer installs or imports heavy packages at startup (they are either removed from `requirements.txt` or imported lazily inside functions). The worker service installs heavy packages and can be given much more memory.

Notes & troubleshooting
- Some packages (e.g., `weasyprint`, system-level audio/FFmpeg) require OS libraries; you may need a custom Docker image or Render Private Service with build packs that provide those system deps.
- If you still see import-time errors in web logs, check files that import heavy libs at module import time and convert those imports to lazy imports (inside functions) similar to the changes already made in `app/utils/nlp_helpers.py` and `app/services/speech_analyzer.py`.
- To test locally without installing heavy packages: create a virtualenv, install only `requirements.txt`, run the web command, and verify the app starts. To run worker features locally, create a second venv and install `requirements-worker.txt`.

Files changed (examples)
- `wsgi.py` — added `app = application` alias so `gunicorn wsgi:app` works.
- `app/utils/nlp_helpers.py` — lazy-loads spaCy and provides a small fallback.
- `app/services/speech_analyzer.py` — lazy-imports whisper, opensmile, and pydub inside functions.

If you want, I can:
- Add a small `Procfile` for local testing.
- Add a sample `render.yaml` to create both services automatically.
- Convert other heavy top-level imports to lazy imports.

