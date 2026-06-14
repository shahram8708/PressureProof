import hashlib
import hmac
from datetime import datetime

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from app.models import AdminAuditLog, AdminUser
from app.services.payment_service import (
    activate_subscription,
    cancel_subscription,
    create_order,
    get_subscription_status,
    verify_payment_signature,
)
from app.services.pgi_calculator import get_pgi_trend_data
from app.utils.helpers import get_sidebar_context
from app.utils.decorators import login_required


upgrade_bp = Blueprint("upgrade", __name__, url_prefix="/upgrade")


def _sidebar_payload(user_id):
    sidebar_context = get_sidebar_context(user_id)
    return {
        "pgi_summary": {
            "current_pgi": sidebar_context.get("current_pgi"),
            "pgi_direction": sidebar_context.get("pgi_direction"),
        },
        "subscription_info": {
            "subscription_tier": sidebar_context.get("subscription_tier"),
            "trial_days_remaining": sidebar_context.get("trial_days_remaining"),
        },
    }


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _audit_payment_event(action, details):
    admin = AdminUser.query.order_by(AdminUser.id.asc()).first()
    if admin is None:
        return
    AdminAuditLog.log_action(
        admin_id=admin.id,
        action=action,
        target_type="subscription",
        details=details,
        request=request,
    )


def _verify_webhook_signature(raw_payload, signature):
    webhook_secret = current_app.config.get("RAZORPAY_WEBHOOK_SECRET")
    if not webhook_secret or not signature:
        return False
    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        raw_payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@upgrade_bp.get("")
def index():
    subscription_status = None
    pgi_trend_data = []
    pgi_hook = None
    sidebar_payload = {}

    if current_user.is_authenticated:
        subscription_status = get_subscription_status(current_user.id)
        pgi_trend_data = get_pgi_trend_data(current_user.id, weeks=4)
        valid_pgi = [
            row for row in pgi_trend_data if row.get("pgi_score") is not None
        ]
        if len(valid_pgi) >= 2:
            pgi_hook = {
                "baseline": valid_pgi[0]["pgi_score"],
                "current": valid_pgi[-1]["pgi_score"],
            }
        sidebar_payload = _sidebar_payload(current_user.id)

    plan_data = {
        "monthly": {
            "label": "Professional Monthly",
            "price": 799,
            "duration": "month",
            "description": "Cancel anytime",
        },
        "annual": {
            "label": "Pro Annual",
            "price": 6499,
            "duration": "year",
            "description": "Save INR 1,089, equivalent to 1.4 months free",
        },
    }

    return render_template(
        "upgrade/index.html",
        title="Upgrade to Professional - PressureProof",
        subscription_status=subscription_status,
        pgi_trend_data=pgi_trend_data,
        pgi_hook=pgi_hook,
        plan_data=plan_data,
        razorpay_key_id=current_app.config.get("RAZORPAY_KEY_ID"),
        **sidebar_payload,
    )


@upgrade_bp.post("/checkout")
@login_required
def checkout():
    payload = request.get_json(silent=True) or {}
    plan = (payload.get("plan") or "").strip().lower()
    if plan not in {"monthly", "annual"}:
        return jsonify({"error": "Invalid plan selection."}), 400

    try:
        order_data = create_order(current_user.id, plan)
    except Exception as exc:
        return jsonify({"error": f"Unable to create checkout order: {exc}"}), 500

    return jsonify(
        {
            "order_id": order_data.get("id"),
            "amount": order_data.get("amount"),
            "currency": order_data.get("currency", "INR"),
            "razorpay_key_id": order_data.get("razorpay_key_id"),
            "user_name": current_user.display_name or current_user.email.split("@")[0],
            "user_email": current_user.email,
            "plan": plan,
        }
    )


@upgrade_bp.post("/webhook")
def webhook():
    payload = request.get_json(silent=True) or {}
    raw_body = request.get_data() or b""

    signature = request.headers.get("X-Razorpay-Signature")
    if signature:
        if not _verify_webhook_signature(raw_body, signature):
            return jsonify({"error": "Invalid webhook signature."}), 400

        event_type = payload.get("event")
        if event_type != "payment.captured":
            return jsonify({"status": "ignored", "event": event_type}), 200

        payment_entity = (
            payload.get("payload", {})
            .get("payment", {})
            .get("entity", {})
        )
        notes = payment_entity.get("notes") or {}

        user_id = notes.get("user_id")
        plan = notes.get("plan")
        order_id = payment_entity.get("order_id")
        payment_id = payment_entity.get("id")
        verification_signature = payload.get("razorpay_signature") or payment_entity.get("razorpay_signature")

        if not user_id or not plan or not order_id or not payment_id:
            return jsonify({"error": "Webhook payload is missing required payment fields."}), 400

        if verification_signature:
            is_valid = verify_payment_signature(order_id, payment_id, verification_signature)
            if not is_valid:
                return jsonify({"error": "Payment signature mismatch."}), 400

        user = activate_subscription(int(user_id), plan, payment_id)
        _audit_payment_event(
            "subscription.activate",
            {
                "source": "webhook",
                "user_id": user.id,
                "plan": plan,
                "order_id": order_id,
                "payment_id": payment_id,
                "captured_at": datetime.utcnow().isoformat(),
            },
        )
        return jsonify({"status": "ok"}), 200

    if not current_user.is_authenticated:
        return jsonify({"error": "Authentication required for checkout callback mode."}), 401

    plan = (payload.get("plan") or "").strip().lower()
    order_id = payload.get("razorpay_order_id")
    payment_id = payload.get("razorpay_payment_id")
    payment_signature = payload.get("razorpay_signature")

    if not plan or not order_id or not payment_id or not payment_signature:
        return jsonify({"error": "Missing callback payment details."}), 400

    if not verify_payment_signature(order_id, payment_id, payment_signature):
        return jsonify({"error": "Invalid payment signature."}), 400

    user = activate_subscription(current_user.id, plan, payment_id)
    _audit_payment_event(
        "subscription.activate",
        {
            "source": "checkout_callback",
            "user_id": user.id,
            "plan": plan,
            "order_id": order_id,
            "payment_id": payment_id,
        },
    )
    return jsonify({"status": "ok"}), 200


@upgrade_bp.post("/cancel")
@login_required
def cancel():
    cancel_subscription(current_user.id)
    flash("Your subscription has been moved to free tier. Access remains until your current billing period ends.", "info")
    return redirect(url_for("profile.subscription"))
