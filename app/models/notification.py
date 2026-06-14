from datetime import datetime

from app.extensions import db


class NotificationLog(db.Model):
    __tablename__ = "notification_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    notification_type = db.Column(db.String(50), nullable=False)
    scheduled_at = db.Column(db.DateTime, nullable=False)
    sent_at = db.Column(db.DateTime, nullable=True)
    opened = db.Column(db.Boolean, nullable=False, default=False)
    push_subscription_endpoint = db.Column(db.String(500), nullable=True)

    user = db.relationship("User", backref=db.backref("notification_logs", lazy="dynamic"))

    @classmethod
    def get_last_notification(cls, user_id, notification_type):
        return (
            cls.query.filter_by(user_id=user_id, notification_type=notification_type)
            .order_by(cls.sent_at.desc())
            .first()
        )

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "notification_type": self.notification_type,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "opened": self.opened,
            "push_subscription_endpoint": self.push_subscription_endpoint,
        }


class PushSubscription(db.Model):
    __tablename__ = "push_subscriptions"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    endpoint = db.Column(db.String(500), nullable=False, unique=True)
    p256dh_key = db.Column(db.String(200), nullable=False)
    auth_key = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    user = db.relationship("User", backref=db.backref("push_subscriptions", lazy="dynamic"))

    @classmethod
    def get_active_subscriptions(cls, user_id):
        return cls.query.filter_by(user_id=user_id, is_active=True).all()

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "endpoint": self.endpoint,
            "p256dh_key": self.p256dh_key,
            "auth_key": self.auth_key,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "is_active": self.is_active,
        }
