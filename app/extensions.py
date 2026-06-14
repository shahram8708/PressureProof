import os

from celery import Celery
from flask_bcrypt import Bcrypt
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import has_request_context, session
from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect


db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login_get"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "warning"
login_manager.session_protection = "basic"

bcrypt = Bcrypt()
mail = Mail()
migrate = Migrate()
csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
)
talisman = Talisman()

_redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379")
celery = Celery(__name__, broker=_redis_url, backend=_redis_url)


@login_manager.user_loader
def load_user(user_id):
    from app.models import User

    if has_request_context():
        impersonating_user_id = session.get("impersonating_user_id")
        if impersonating_user_id:
            try:
                return User.query.get(int(impersonating_user_id))
            except (TypeError, ValueError):
                pass

    if user_id is None:
        return None

    return User.query.get(int(user_id))
