from app.routes.api import api_bp
from app.routes.admin import admin_bp
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


__all__ = [
    "public_bp",
    "auth_bp",
    "onboarding_bp",
    "dashboard_bp",
    "lsrc_bp",
    "sessions_bp",
    "snapspeak_bp",
    "cohort_bp",
    "certificate_bp",
    "profile_bp",
    "upgrade_bp",
    "api_bp",
    "admin_bp",
]
