from datetime import date, datetime, time, timedelta
import json

from flask import current_app, url_for
from pywebpush import WebPushException, webpush

from app.extensions import db, mail
from app.models import LsrcScore, PgiRecord, TrainingSession
from app.models.notification import NotificationLog, PushSubscription


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_week_bounds(week_start_date):
    start_dt = datetime.combine(week_start_date, time.min)
    end_dt = start_dt + timedelta(days=7)
    return start_dt, end_dt


def send_snapspeak_push(user) -> bool:
    subscriptions = PushSubscription.get_active_subscriptions(user.id)
    if not subscriptions:
        current_app.logger.debug("No active push subscriptions for user %s", user.id)
        return False

    vapid_private_key = current_app.config.get("VAPID_PRIVATE_KEY")
    vapid_public_key = current_app.config.get("VAPID_PUBLIC_KEY")
    if not vapid_private_key or not vapid_public_key:
        current_app.logger.warning("VAPID keys missing. Push notifications are disabled.")
        return False

    payload = {
        "title": "PressureProof SnapSpeak",
        "body": "Your 90-second speaking challenge is ready. Tap to open.",
        "url": "/snapspeak",
        "icon": "/static/img/pressureproof-icon.svg",
    }

    sender_email = current_app.config.get("VAPID_CLAIMS_EMAIL", "hello@pressureproof.com")
    delivered = False

    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {
                        "p256dh": subscription.p256dh_key,
                        "auth": subscription.auth_key,
                    },
                },
                data=json.dumps(payload),
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": f"mailto:{sender_email}"},
            )
            delivered = True
        except WebPushException as exc:
            status_code = None
            response = getattr(exc, "response", None)
            if response is not None:
                status_code = getattr(response, "status_code", None)

            if status_code in {404, 410}:
                subscription.is_active = False
                db.session.commit()
                current_app.logger.info(
                    "Marked invalid push endpoint inactive for user %s", user.id
                )
            else:
                current_app.logger.warning(
                    "Push notification failed for user %s endpoint %s: %s",
                    user.id,
                    subscription.endpoint,
                    exc,
                )

    return delivered


def send_weekly_report_email(user) -> bool:
    try:
        from flask_mail import Message

        latest_two_pgi = (
            PgiRecord.query.filter_by(user_id=user.id)
            .order_by(PgiRecord.week_start_date.desc())
            .limit(2)
            .all()
        )

        current_pgi = _safe_float(latest_two_pgi[0].pgi_score) if latest_two_pgi else None
        previous_pgi = _safe_float(latest_two_pgi[1].pgi_score) if len(latest_two_pgi) > 1 else None

        pgi_delta = None
        pgi_direction = "flat"
        if current_pgi is not None and previous_pgi is not None:
            pgi_delta = round(current_pgi - previous_pgi, 2)
            if pgi_delta < 0:
                pgi_direction = "improving"
            elif pgi_delta > 0:
                pgi_direction = "rising"

        today = date.today()
        current_week_start = today - timedelta(days=today.weekday())
        previous_week_start = current_week_start - timedelta(days=7)

        current_start, current_end = _resolve_week_bounds(current_week_start)
        previous_start, previous_end = _resolve_week_bounds(previous_week_start)

        dimensions = {
            "lexical_diversity": "Vocabulary range",
            "syntactic_complexity": "Sentence complexity",
            "prosodic_confidence": "Vocal confidence",
            "disfluency_rate": "Fluency control",
            "sentence_completion": "Sentence completion",
            "recovery_speed_score": "Recovery speed",
        }

        current_scores = LsrcScore.query.filter(
            LsrcScore.user_id == user.id,
            LsrcScore.scored_at >= current_start,
            LsrcScore.scored_at < current_end,
        ).all()
        previous_scores = LsrcScore.query.filter(
            LsrcScore.user_id == user.id,
            LsrcScore.scored_at >= previous_start,
            LsrcScore.scored_at < previous_end,
        ).all()

        top_dimension = "No clear dimension shift this week yet"
        top_delta = 0.0

        for field_name, label in dimensions.items():
            current_values = [
                _safe_float(getattr(score, field_name, None))
                for score in current_scores
                if _safe_float(getattr(score, field_name, None)) is not None
            ]
            previous_values = [
                _safe_float(getattr(score, field_name, None))
                for score in previous_scores
                if _safe_float(getattr(score, field_name, None)) is not None
            ]
            if not current_values or not previous_values:
                continue

            current_avg = sum(current_values) / len(current_values)
            previous_avg = sum(previous_values) / len(previous_values)
            delta = current_avg - previous_avg
            if delta > top_delta:
                top_delta = delta
                top_dimension = f"{label} improved by {delta:.1f} points week over week"

        session_count = TrainingSession.query.filter(
            TrainingSession.user_id == user.id,
            TrainingSession.created_at >= current_start,
            TrainingSession.created_at < current_end,
            TrainingSession.status == "completed",
        ).count()

        if pgi_direction == "improving":
            delta_text = f"\u2193 {abs(pgi_delta):.1f} vs last week" if pgi_delta is not None else "No weekly delta yet"
        elif pgi_direction == "rising":
            delta_text = f"\u2191 {abs(pgi_delta):.1f} vs last week" if pgi_delta is not None else "No weekly delta yet"
        else:
            delta_text = "No major week over week movement"

        pgi_display = f"{current_pgi:.1f}" if current_pgi is not None else "n/a"

        dashboard_url = url_for("dashboard.index", _external=True)

        html_body = f"""
        <div style=\"font-family: Inter, Arial, sans-serif; background: #F9FAFB; padding: 24px; color: #111827;\">
          <table role=\"presentation\" style=\"max-width: 640px; width: 100%; margin: 0 auto; background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 12px; border-collapse: separate; overflow: hidden;\">
            <tr>
              <td style=\"background: #1E1B4B; color: #FFFFFF; padding: 20px 24px; font-size: 22px; font-weight: 700;\">PressureProof Weekly Report</td>
            </tr>
            <tr>
              <td style=\"padding: 24px;\">
                <p style=\"margin: 0 0 12px; font-size: 15px;\">Hi {user.display_name or 'there'}, here is your weekly speaking performance snapshot.</p>
                <div style=\"margin: 20px 0; padding: 16px; border: 1px solid #E5E7EB; border-radius: 10px; background: #F9FAFB;\">
                  <div style=\"font-size: 13px; color: #6B7280; margin-bottom: 6px;\">Current PGI</div>
                                    <div style="font-size: 30px; font-weight: 700; color: #1E1B4B;">{pgi_display}</div>
                  <div style=\"font-size: 13px; color: #6B7280; margin-top: 6px;\">{delta_text}</div>
                </div>
                <p style=\"margin: 0 0 8px; font-size: 14px;\"><strong>Top dimension shift:</strong> {top_dimension}</p>
                <p style=\"margin: 0 0 20px; font-size: 14px;\"><strong>Sessions completed this week:</strong> {session_count}</p>
                <a href=\"{dashboard_url}\" style=\"display: inline-block; background: #F59E0B; color: #111827; text-decoration: none; padding: 11px 18px; border-radius: 8px; font-weight: 600;\">Open dashboard</a>
              </td>
            </tr>
          </table>
        </div>
        """

        message = Message(
            subject="Your PressureProof weekly report",
            recipients=[user.email],
            html=html_body,
        )
        mail.send(message)
        return True
    except Exception:
        current_app.logger.exception("Failed to send weekly report email for user %s", user.id)
        return False


def register_push_subscription(user_id, subscription_data):
    if not isinstance(subscription_data, dict):
        raise ValueError("subscription_data must be a dictionary")

    endpoint = (subscription_data.get("endpoint") or "").strip()
    keys = subscription_data.get("keys") or {}
    p256dh_key = (keys.get("p256dh") or "").strip()
    auth_key = (keys.get("auth") or "").strip()

    if not endpoint or not p256dh_key or not auth_key:
        raise ValueError("endpoint, keys.p256dh, and keys.auth are required")

    existing = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if existing is not None:
        existing.user_id = user_id
        existing.p256dh_key = p256dh_key
        existing.auth_key = auth_key
        existing.is_active = True
        db.session.commit()
        return existing

    record = PushSubscription(
        user_id=user_id,
        endpoint=endpoint,
        p256dh_key=p256dh_key,
        auth_key=auth_key,
        is_active=True,
    )
    db.session.add(record)
    db.session.commit()
    return record


def unregister_push_subscription(endpoint):
    target_endpoint = (endpoint or "").strip()
    if not target_endpoint:
        return False

    subscription = PushSubscription.query.filter_by(endpoint=target_endpoint).first()
    if subscription is None:
        return False

    subscription.is_active = False
    db.session.commit()
    return True


def send_transactional_notification(user_id, notification_type, payload):
    user_id = int(user_id)
    if notification_type == "snapspeak":
        from app.models import User

        user = User.query.get(user_id)
        if user is None:
            return False
        return send_snapspeak_push(user)

    current_app.logger.info(
        "Unsupported transactional notification type %s for user %s",
        notification_type,
        user_id,
    )
    return False
