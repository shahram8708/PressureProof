import os
from datetime import timedelta
from pathlib import Path

from celery.schedules import crontab


BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    WTF_CSRF_ENABLED = True
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024

    MAIL_SERVER = os.getenv("MAIL_SERVER")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "PressureProof <hello@pressureproof.com>")
    MAIL_USE_TLS = True

    REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379")
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI") or REDIS_URL or "memory://"

    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
    RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")

    CELERYBEAT_SCHEDULE = {
        "weekly-pgi-recalculation": {
            "task": "tasks.weekly_pgi_recalculation",
            "schedule": crontab(minute=0, hour=0, day_of_week="sun"),
            "options": {"queue": "lsrc_update"},
        },
        "daily-audio-cleanup": {
            "task": "tasks.daily_audio_cleanup",
            "schedule": crontab(minute=0, hour=3),
            "options": {"queue": "lsrc_update"},
        },
        "nightly-cohort-rebuild": {
            "task": "tasks.nightly_cohort_rebuild",
            "schedule": crontab(minute=0, hour=2),
            "options": {"queue": "lsrc_update"},
        },
        "weekly-report-email": {
            "task": "tasks.weekly_report_email",
            "schedule": crontab(minute=0, hour=8, day_of_week="mon"),
            "options": {"queue": "lsrc_update"},
        },
        "send-snapspeak-notifications": {
            "task": "tasks.send_snapspeak_notifications",
            "schedule": crontab(minute="*/30"),
            "options": {"queue": "lsrc_update"},
        },
    }

    VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", None)
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", None)
    VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", None)

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")

    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION")
    AWS_REGION = os.getenv("AWS_REGION") or AWS_DEFAULT_REGION
    S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

    # Default storage backend for non-production environments.
    STORAGE_BACKEND = "local"


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = False
    MAIL_SUPPRESS_SEND = False
    STORAGE_BACKEND = "local"
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{(BASE_DIR / 'pressureproof.db').as_posix()}",
    )


class ProductionConfig(Config):
    DEBUG = False
    STORAGE_BACKEND = "s3"
    SESSION_COOKIE_SECURE = True
    FORCE_HTTPS = True
    PREFERRED_URL_SCHEME = "https"


class TestingConfig(Config):
    TESTING = True
    STORAGE_BACKEND = "local"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    MAIL_SUPPRESS_SEND = True


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
