# PressureProof

PressureProof is a Flask based web platform that diagnoses and trains the preparation gap in spoken English performance. It focuses on the measurable difference between calm condition fluency and high pressure fluency, then closes that gap through structured stress calibrated practice and longitudinal tracking.

## Prerequisites

1. Python 3.11 or newer
2. PostgreSQL 14 or newer
3. Redis 6 or newer
4. FFmpeg available on your system path

## Installation

1. Clone the repository and move into the project directory.

```bash
git clone <your-repo-url>
cd pressureproof
```

2. Create and activate a virtual environment.

```bash
python -m venv .venv
.venv\Scripts\activate
```

3. Install Python dependencies.

```bash
pip install -r requirements.txt
```

4. Download the spaCy English model.

```bash
python -m spacy download en_core_web_sm
```

5. Ensure self hosted vendor assets are present in the static directory.

The project expects these local files:

1. static/vendor/bootstrap/bootstrap.min.css
2. static/vendor/bootstrap/bootstrap.bundle.min.js
3. static/vendor/chartjs/chart.min.js
4. static/fonts/Inter-Regular.woff2
5. static/fonts/Inter-Medium.woff2
6. static/fonts/Inter-SemiBold.woff2
7. static/fonts/Inter-Bold.woff2

If missing, download them into those exact paths.

## Environment setup

1. Copy `.env.example` to `.env`.
2. Fill in required values.

```bash
copy .env.example .env
```

Required for startup:

1. SECRET_KEY
2. DATABASE_URL

Optional but recommended:

1. REDIS_URL
2. AWS and S3 credentials (required in production)
3. Razorpay credentials
4. SMTP credentials
5. VAPID keys
6. WHISPER_MODEL_SIZE

Storage backend behavior:

1. Development and testing always store files on local filesystem under `app/uploads/`.
2. Production always stores files in AWS S3.
3. In production, set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME`, and either `AWS_REGION` or `AWS_DEFAULT_REGION`.

## Database initialization behavior

On every app startup, the factory performs the following automatically:

1. `db.create_all()` to create any missing tables.
2. `seed_database()` to insert default records only when missing.

For initial setup, no manual `flask db upgrade` command is required. Use Flask Migrate only for future schema evolution after this baseline.

## Run the development server

```bash
python run.py
```

The app starts on `0.0.0.0` and uses the `PORT` value in `.env` or defaults to `5000`. The dev server always runs with `use_reloader=False` to avoid duplicate model loading.

## Celery workers and scheduler

Start the default and high priority workers in separate terminals.

```bash
celery -A app.tasks worker --pool=solo --loglevel=debug -Q speech_analysis,lsrc_update
```

```bash
celery -A app.extensions.celery worker --loglevel=info --hostname=priority@%h -Q priority
```

Start Celery Beat for scheduled tasks.

```bash
celery -A app.extensions.celery beat --loglevel=info
```

## Demo login

After first startup and seeding:

1. Email: demo@pressureproof.com
2. Password: DemoUser123!

## Admin access

The admin panel is available at `/admin/login`.

Seeded admin users on first startup:

1. Super admin: admin@pressureproof.com / Admin@PressureProof2026!
2. Analyst: analyst@pressureproof.com / Analyst@PressureProof2026!
3. Support: support@pressureproof.com / Support@PressureProof2026!

Important:

1. Rotate all seeded admin passwords immediately in non local environments.
2. Set `ADMIN_SECRET_KEY` in `.env` for audit token hardening.
3. Restrict admin route exposure behind network controls (VPN, allowlist, or reverse proxy auth).

## Production checklist

Before go live, verify each of the following:

1. Use strong and unique `SECRET_KEY` and `ADMIN_SECRET_KEY` values.
2. Configure PostgreSQL and Redis with authentication and backups.
3. Set `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET`.
4. Configure SMTP (`MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`).
5. Configure HTTPS termination and secure cookies.
6. Verify Celery workers and beat process are running with expected queues.
7. Confirm maintenance mode toggle works (`maintenance_mode` Redis key).
8. Validate certificate generation pipeline and PDF storage (local/S3).
9. Run the full test suite before deployment.
10. Confirm CSP allows only required domains (Razorpay checkout and API).

## Project structure overview

```text
pressureproof/
  app/
    config.py
    extensions.py
    models/
    routes/
    forms/
    services/
    utils/
  templates/
  static/
    css/
    js/
    vendor/
    fonts/
    img/
  tests/
  run.py
  wsgi.py
  seed.py
```
