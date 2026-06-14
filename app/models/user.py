from datetime import datetime

from flask_login import UserMixin
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from flask import current_app

from app.extensions import bcrypt, db


class User(UserMixin, db.Model):
    __tablename__ = "users"
    __table_args__ = (
        db.Index("ix_users_email", "email"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    display_name = db.Column(db.String(100), nullable=True)
    country = db.Column(db.String(100), nullable=True)
    l1_language = db.Column(db.String(100), nullable=True)
    professional_context = db.Column(db.String(50), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)

    subscription_tier = db.Column(db.String(20), default="free", nullable=False)
    subscription_expires_at = db.Column(db.DateTime, nullable=True)
    trial_ends_at = db.Column(db.DateTime, nullable=True)

    onboarding_complete = db.Column(db.Boolean, default=False, nullable=False)
    preferred_snapspeak_start = db.Column(db.Time, nullable=True)
    preferred_snapspeak_end = db.Column(db.Time, nullable=True)
    snapspeak_opted_in = db.Column(db.Boolean, default=False, nullable=False)
    weekly_report_opted_in = db.Column(db.Boolean, default=True, nullable=False)
    session_reminder_opted_in = db.Column(db.Boolean, default=True, nullable=False)

    razorpay_subscription_id = db.Column(db.String(100), nullable=True)
    razorpay_customer_id = db.Column(db.String(100), nullable=True)
    razorpay_last_payment_id = db.Column(db.String(100), nullable=True)

    is_banned = db.Column(db.Boolean, default=False, nullable=False)
    ban_reason = db.Column(db.String(200), nullable=True)

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    def _serializer(self):
        return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])

    def generate_verification_token(self):
        serializer = self._serializer()
        return serializer.dumps({"email": self.email}, salt="email-verification")

    @staticmethod
    def verify_token(token, expiration=86400):
        serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        try:
            payload = serializer.loads(token, salt="email-verification", max_age=expiration)
            return payload.get("email")
        except (BadSignature, SignatureExpired):
            return None

    def generate_password_reset_token(self):
        serializer = self._serializer()
        return serializer.dumps({"email": self.email}, salt="password-reset")

    @staticmethod
    def verify_password_reset_token(token):
        serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        try:
            payload = serializer.loads(token, salt="password-reset", max_age=3600)
            return payload.get("email")
        except (BadSignature, SignatureExpired):
            return None

    @property
    def is_trial_active(self):
        return bool(self.trial_ends_at and self.trial_ends_at > datetime.utcnow())

    @property
    def is_subscribed(self):
        if self.subscription_tier == "free":
            return False
        return bool(
            self.subscription_expires_at and self.subscription_expires_at > datetime.utcnow()
        )

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "country": self.country,
            "l1_language": self.l1_language,
            "professional_context": self.professional_context,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "email_verified": self.email_verified,
            "subscription_tier": self.subscription_tier,
            "subscription_expires_at": (
                self.subscription_expires_at.isoformat()
                if self.subscription_expires_at
                else None
            ),
            "trial_ends_at": self.trial_ends_at.isoformat() if self.trial_ends_at else None,
            "onboarding_complete": self.onboarding_complete,
            "preferred_snapspeak_start": (
                self.preferred_snapspeak_start.isoformat()
                if self.preferred_snapspeak_start
                else None
            ),
            "preferred_snapspeak_end": (
                self.preferred_snapspeak_end.isoformat()
                if self.preferred_snapspeak_end
                else None
            ),
            "snapspeak_opted_in": self.snapspeak_opted_in,
            "weekly_report_opted_in": self.weekly_report_opted_in,
            "session_reminder_opted_in": self.session_reminder_opted_in,
            "razorpay_subscription_id": self.razorpay_subscription_id,
            "razorpay_customer_id": self.razorpay_customer_id,
            "razorpay_last_payment_id": self.razorpay_last_payment_id,
            "is_banned": self.is_banned,
            "ban_reason": self.ban_reason,
        }

    def __repr__(self):
        return f"<User id={self.id} email={self.email}>"
