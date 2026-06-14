import os
from dotenv import load_dotenv

load_dotenv()

from datetime import datetime
from flask import Flask, redirect, render_template, request, session, url_for
from flask_login import current_user
import redis

from app.config import config
from app.extensions import bcrypt, celery, csrf, db, limiter, login_manager, mail, migrate, talisman
from seed import seed_database


def _resolve_config_name(config_name):
    if config_name and config_name != "default":
        return str(config_name).strip().lower()

    return (
        os.getenv("FLASK_CONFIG")
        or os.getenv("FLASK_ENV")
        or "default"
    ).strip().lower()


def _check_env_vars(config_name):
    critical_vars = ["SECRET_KEY", "DATABASE_URL"]
    optional_vars = [
        "REDIS_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "S3_BUCKET_NAME",
        "RAZORPAY_KEY_ID",
        "RAZORPAY_KEY_SECRET",
        "RAZORPAY_WEBHOOK_SECRET",
        "ADMIN_SECRET_KEY",
        "MAIL_SERVER",
        "MAIL_PORT",
        "MAIL_USERNAME",
        "MAIL_PASSWORD",
        "VAPID_PRIVATE_KEY",
        "VAPID_PUBLIC_KEY",
        "VAPID_CLAIMS_EMAIL",
        "WHISPER_MODEL_SIZE",
    ]

    print("[STARTUP] Environment configuration checklist")
    missing_critical = []

    for var_name in critical_vars:
        if os.getenv(var_name):
            print(f"[OK] {var_name} is set.")
        else:
            print(f"[ERROR] {var_name} is missing.")
            missing_critical.append(var_name)

    for var_name in optional_vars:
        if os.getenv(var_name):
            print(f"[OK] {var_name} is set.")
        else:
            print(f"[WARNING] {var_name} is not set.")

    if config_name == "production":
        s3_required_vars = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "S3_BUCKET_NAME"]
        for var_name in s3_required_vars:
            if os.getenv(var_name):
                print(f"[OK] {var_name} is set for production S3 storage.")
            else:
                print(f"[ERROR] {var_name} is missing for production S3 storage.")
                missing_critical.append(var_name)

        if os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"):
            print("[OK] AWS region is set for production S3 storage.")
        else:
            print("[ERROR] AWS region is missing. Set AWS_REGION or AWS_DEFAULT_REGION.")
            missing_critical.append("AWS_REGION/AWS_DEFAULT_REGION")

    if missing_critical:
        raise RuntimeError(
            "Missing critical environment variables: " + ", ".join(missing_critical)
        )


def _configure_celery(app):
    celery.conf.update(
        broker_url=app.config.get("CELERY_BROKER_URL"),
        result_backend=app.config.get("CELERY_RESULT_BACKEND"),
        beat_schedule=app.config.get("CELERYBEAT_SCHEDULE", {}),
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
    )


def _register_blueprints(app):
    from app.routes.admin import admin_bp
    from app.routes.api import api_bp
    from app.routes.auth import auth_bp
    from app.routes.certificate import certificate_bp
    from app.routes.cohort import cohort_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.lsrc import lsrc_bp
    from app.routes.onboarding import onboarding_bp
    from app.routes.profile import profile_bp
    from app.routes.public import public_bp
    from app.routes.sessions import sessions_bp
    from app.routes.snapspeak import snapspeak_bp
    from app.routes.upgrade import upgrade_bp

    app.register_blueprint(admin_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(onboarding_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(lsrc_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(snapspeak_bp)
    app.register_blueprint(cohort_bp)
    app.register_blueprint(certificate_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(upgrade_bp)
    app.register_blueprint(api_bp)


def _get_redis_client(app):
    redis_url = (
        app.config.get("REDIS_URL")
        or app.config.get("CELERY_BROKER_URL")
        or os.getenv("REDIS_URL")
        or "redis://localhost:6379/0"
    )
    return redis.Redis.from_url(redis_url, decode_responses=True)


def _register_filters(app):
    @app.template_filter("strftime")
    def strftime_filter(value, fmt="%d %b %Y, %I:%M %p"):
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.strftime(fmt)
        return value

    @app.template_filter("round")
    def round_filter(value, precision=2):
        try:
            return round(float(value), int(precision))
        except (TypeError, ValueError):
            return value

    @app.template_filter("pgi_color")
    def pgi_color_filter(value):
        try:
            score = float(value)
        except (TypeError, ValueError):
            return "text-secondary"

        if score <= 20:
            return "text-accent"
        if score <= 30:
            return "text-primary"
        return "text-secondary"


def _register_context_processors(app):
    @app.context_processor
    def inject_sidebar_context():
        if not current_user.is_authenticated:
            return {}

        from app.utils.helpers import get_sidebar_context

        sidebar = get_sidebar_context(current_user.id)
        return {
            "pgi_summary": {
                "current_pgi": sidebar.get("current_pgi"),
                "pgi_direction": sidebar.get("pgi_direction"),
            },
            "subscription_info": {
                "subscription_tier": sidebar.get("subscription_tier"),
                "trial_days_remaining": sidebar.get("trial_days_remaining"),
            },
        }


def _register_onboarding_guard(app):
    @app.before_request
    def enforce_onboarding_completion():
        if not current_user.is_authenticated:
            return None
        if current_user.onboarding_complete:
            return None
        if request.endpoint is None or request.endpoint == "static":
            return None
        if request.blueprint in {"onboarding", "auth", "api"}:
            return None

        if request.method in {"GET", "HEAD"}:
            next_url = request.full_path if request.query_string else request.path
            session["post_onboarding_next"] = next_url

        return redirect(url_for("onboarding.step1"))


def create_app(config_name="default"):
    resolved_config_name = _resolve_config_name(config_name)
    _check_env_vars(resolved_config_name)

    app = Flask(__name__, template_folder="../templates", static_folder="../static")

    config_class = config.get(resolved_config_name, config["default"])
    app.config.from_object(config_class)
    app.config["APP_ENV_NAME"] = resolved_config_name

    db.init_app(app)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    mail.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)
    csrf.init_app(app)
    _configure_celery(app)

    _register_blueprints(app)
    _register_filters(app)
    _register_context_processors(app)
    _register_onboarding_guard(app)

    talisman.init_app(
        app,
        content_security_policy={
            "default-src": ["'self'"],
            "script-src": ["'self'", "'unsafe-inline'", "https://checkout.razorpay.com"],
            "worker-src": ["'self'", "blob:"],
            "style-src": ["'self'", "'unsafe-inline'"],
            "img-src": ["'self'", "data:"],
            "font-src": ["'self'", "data:"],
            "connect-src": ["'self'", "https://api.razorpay.com", "https://checkout.razorpay.com"],
            "media-src": ["'self'", "blob:"],
            "object-src": ["'self'"],
            "frame-src": ["'self'", "https://api.razorpay.com", "https://checkout.razorpay.com"],
            "frame-ancestors": ["'self'"],
            "base-uri": ["'self'"],
            "form-action": ["'self'"],
        },
    )

    @app.route("/maintenance")
    def maintenance_page():
        return render_template(
            "public/maintenance.html",
            hide_header=True,
            hide_footer=True,
            hide_sidebar=True,
            no_sidebar=True,
            title="Maintenance - PressureProof",
        )

    @app.before_request
    def maintenance_mode_guard():
        path = request.path or "/"
        if path.startswith("/admin") or path.startswith("/static") or path == "/maintenance":
            return None
        try:
            redis_client = _get_redis_client(app)
            if redis_client.get("maintenance_mode") == "1":
                return redirect(url_for("maintenance_page"))
        except Exception:
            return None
        return None

    with app.app_context():
        db.create_all()
        seed_database()

    return app
