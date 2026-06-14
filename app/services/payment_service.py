import hashlib
import hmac
import time
from datetime import datetime, timedelta

import razorpay
from flask import current_app

from app.extensions import db
from app.models import User


_RAZORPAY_CLIENT = None


PLAN_PRICING_INR = {
    "monthly": 799,
    "annual": 6499,
}


def get_razorpay_client() -> razorpay.Client:
    global _RAZORPAY_CLIENT

    if _RAZORPAY_CLIENT is not None:
        return _RAZORPAY_CLIENT

    key_id = current_app.config.get("RAZORPAY_KEY_ID")
    key_secret = current_app.config.get("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        raise RuntimeError("Razorpay credentials are not configured")

    _RAZORPAY_CLIENT = razorpay.Client(auth=(key_id, key_secret))
    return _RAZORPAY_CLIENT


def create_order(user_id: int, plan: str) -> dict:
    normalized_plan = (plan or "").strip().lower()
    if normalized_plan not in PLAN_PRICING_INR:
        raise ValueError("Invalid plan. Expected 'monthly' or 'annual'.")

    amount_inr = PLAN_PRICING_INR[normalized_plan]
    amount_paise = int(amount_inr * 100)

    client = get_razorpay_client()
    order_data = client.order.create(
        {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": f"pp_{user_id}_{normalized_plan}_{int(time.time())}",
            "notes": {
                "user_id": str(user_id),
                "plan": normalized_plan,
            },
        }
    )
    order_data["razorpay_key_id"] = current_app.config.get("RAZORPAY_KEY_ID")
    return order_data


def verify_payment_signature(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> bool:
    secret = current_app.config.get("RAZORPAY_KEY_SECRET", "")
    payload = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, razorpay_signature or "")


def activate_subscription(user_id: int, plan: str, razorpay_payment_id: str) -> User:
    user = User.query.get(user_id)
    if user is None:
        raise ValueError("User not found")

    normalized_plan = (plan or "").strip().lower()
    if normalized_plan == "monthly":
        user.subscription_tier = "professional"
        user.subscription_expires_at = datetime.utcnow() + timedelta(days=30)
    elif normalized_plan == "annual":
        user.subscription_tier = "pro_annual"
        user.subscription_expires_at = datetime.utcnow() + timedelta(days=365)
    elif normalized_plan in {"professional", "pro_annual", "free"}:
        user.subscription_tier = normalized_plan
        if normalized_plan == "professional":
            user.subscription_expires_at = datetime.utcnow() + timedelta(days=30)
        elif normalized_plan == "pro_annual":
            user.subscription_expires_at = datetime.utcnow() + timedelta(days=365)
        else:
            user.subscription_expires_at = None
    else:
        raise ValueError("Invalid plan")

    user.razorpay_last_payment_id = razorpay_payment_id
    db.session.commit()
    return user


def cancel_subscription(user_id: int) -> User:
    user = User.query.get(user_id)
    if user is None:
        raise ValueError("User not found")

    user.subscription_tier = "free"
    user.subscription_expires_at = None
    db.session.commit()
    return user


def get_subscription_status(user_id: int) -> dict:
    user = User.query.get(user_id)
    if user is None:
        raise ValueError("User not found")

    now = datetime.utcnow()
    tier = user.subscription_tier or "free"
    expires_at = user.subscription_expires_at
    is_paid_tier = tier in {"professional", "pro_annual"}
    is_active = bool(is_paid_tier and expires_at and expires_at > now)

    days_remaining = None
    if expires_at is not None:
        days_remaining = max(0, (expires_at - now).days)

    is_trial = bool(tier == "free" and user.trial_ends_at and user.trial_ends_at > now)
    trial_days_remaining = None
    if user.trial_ends_at is not None:
        trial_days_remaining = max(0, (user.trial_ends_at - now).days)

    plan_label_map = {
        "free": "Free",
        "professional": "Professional Monthly",
        "pro_annual": "Pro Annual",
    }

    can_upgrade = tier == "free" or not is_active

    return {
        "tier": tier,
        "is_active": is_active,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "days_remaining": days_remaining,
        "is_trial": is_trial,
        "trial_days_remaining": trial_days_remaining,
        "can_upgrade": can_upgrade,
        "plan_label": plan_label_map.get(tier, "Free"),
    }


def create_subscription_checkout(user_id, plan_code):
    return create_order(user_id, plan_code)
