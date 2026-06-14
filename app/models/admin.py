import hashlib
import hmac
import json
import secrets
from datetime import datetime

from flask import current_app

from app.extensions import bcrypt, db


class AdminUser(db.Model):
    __tablename__ = "admin_users"

    ROLE_PERMISSIONS = {
        "super_admin": {
            "view_users",
            "edit_users",
            "delete_users",
            "manage_subscriptions",
            "view_sessions",
            "view_analytics",
            "manage_cohorts",
            "send_notifications",
            "view_certificates",
            "add_user_notes",
            "manage_admins",
            "view_cohorts",
            "manage_feature_flags",
        },
        "admin": {
            "view_users",
            "edit_users",
            "delete_users",
            "manage_subscriptions",
            "view_sessions",
            "view_analytics",
            "manage_cohorts",
            "send_notifications",
            "view_certificates",
            "add_user_notes",
            "view_cohorts",
        },
        "support": {
            "view_users",
            "add_user_notes",
            "view_sessions",
        },
        "analyst": {
            "view_analytics",
            "view_cohorts",
        },
    }

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), nullable=False, default="admin")
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)
    last_login_ip = db.Column(db.String(45), nullable=True)

    created_by_id = db.Column(db.Integer, db.ForeignKey("admin_users.id"), nullable=True)

    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)

    created_by = db.relationship("AdminUser", remote_side=[id], uselist=False)

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    @property
    def is_locked(self):
        return bool(self.locked_until and self.locked_until > datetime.utcnow())

    def unlock(self):
        self.failed_login_attempts = 0
        self.locked_until = None

    def has_permission(self, permission):
        if self.role == "super_admin":
            return True
        role_permissions = self.ROLE_PERMISSIONS.get(self.role, set())
        return permission in role_permissions

    def generate_audit_token(self):
        secret = current_app.config.get("ADMIN_SECRET_KEY") or current_app.config.get("SECRET_KEY", "")
        payload = f"{self.id}:{datetime.utcnow().timestamp()}:{secrets.token_hex(8)}"
        signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{payload}:{signature}"

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "last_login_ip": self.last_login_ip,
            "created_by_id": self.created_by_id,
            "failed_login_attempts": self.failed_login_attempts,
            "locked_until": self.locked_until.isoformat() if self.locked_until else None,
            "is_locked": self.is_locked,
        }


class AdminAuditLog(db.Model):
    __tablename__ = "admin_audit_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("admin_users.id"), nullable=False, index=True)
    action = db.Column(db.String(100), nullable=False)
    target_type = db.Column(db.String(50), nullable=True)
    target_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(200), nullable=True)
    performed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    admin = db.relationship("AdminUser", backref=db.backref("audit_logs", lazy="dynamic"))

    @classmethod
    def log_action(
        cls,
        admin_id,
        action,
        target_type=None,
        target_id=None,
        details=None,
        request=None,
    ):
        detail_text = None
        if details is not None:
            if isinstance(details, str):
                detail_text = details
            else:
                detail_text = json.dumps(details, sort_keys=True)

        ip_address = None
        user_agent = None
        if request is not None:
            ip_address = request.headers.get("X-Forwarded-For", request.remote_addr)
            if ip_address and "," in ip_address:
                ip_address = ip_address.split(",", 1)[0].strip()
            user_agent = (request.headers.get("User-Agent") or "")[:200]

        record = cls(
            admin_id=admin_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=detail_text,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.session.add(record)
        db.session.commit()
        return record


class AdminUserNote(db.Model):
    __tablename__ = "admin_user_notes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("admin_users.id"), nullable=False)
    note_text = db.Column(db.Text, nullable=False)
    note_type = db.Column(db.String(30), default="general")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_resolved = db.Column(db.Boolean, default=False)

    admin = db.relationship("AdminUser", backref=db.backref("notes", lazy="dynamic"))
    user = db.relationship("User", backref=db.backref("admin_notes", lazy="dynamic"))

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "admin_id": self.admin_id,
            "note_text": self.note_text,
            "note_type": self.note_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "is_resolved": self.is_resolved,
        }
