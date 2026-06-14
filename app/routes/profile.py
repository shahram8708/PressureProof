import json
from datetime import datetime

from flask import Blueprint, Response, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, logout_user
from flask_wtf.csrf import validate_csrf
from wtforms.validators import ValidationError

from app.extensions import db
from app.forms.profile_forms import (
    ChangePasswordForm,
    DeleteAccountForm,
    PersonalInfoForm,
    SnapSpeakSettingsForm,
)
from app.models import DrillCompletion, LsrcScore, PgiRecord, PushSubscription, SnapSpeakRecord, TrainingSession
from app.services.payment_service import get_subscription_status
from app.utils.helpers import get_sidebar_context
from app.utils.decorators import login_required


profile_bp = Blueprint("profile", __name__, url_prefix="/profile")


def _time_to_string(value):
    if value is None:
        return ""
    return value.strftime("%H:%M")


def _parse_time(value):
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%H:%M").time()
    except ValueError:
        return None


def _validate_csrf_from_request():
    token = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
    if not token:
        return False
    try:
        validate_csrf(token)
        return True
    except ValidationError:
        return False


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


@profile_bp.get("/settings")
@login_required
def settings():
    personal_form = PersonalInfoForm(prefix="personal")
    snapspeak_form = SnapSpeakSettingsForm(prefix="snapspeak")
    password_form = ChangePasswordForm(prefix="password")
    delete_form = DeleteAccountForm(prefix="delete")

    personal_form.display_name.data = current_user.display_name or ""
    personal_form.email.data = current_user.email
    personal_form.country.data = current_user.country or ""
    personal_form.l1_language.data = current_user.l1_language or ""
    personal_form.professional_context.data = current_user.professional_context or "Other"

    snapspeak_form.snapspeak_opted_in.data = bool(current_user.snapspeak_opted_in)
    snapspeak_form.preferred_snapspeak_start.data = _time_to_string(
        current_user.preferred_snapspeak_start
    )
    snapspeak_form.preferred_snapspeak_end.data = _time_to_string(current_user.preferred_snapspeak_end)
    snapspeak_form.weekly_report_opted_in.data = bool(current_user.weekly_report_opted_in)
    snapspeak_form.session_reminder_opted_in.data = bool(current_user.session_reminder_opted_in)

    has_push_subscription = (
        PushSubscription.query.filter_by(user_id=current_user.id, is_active=True).count() > 0
    )

    return render_template(
        "profile/settings.html",
        title="Profile Settings - PressureProof",
        personal_form=personal_form,
        snapspeak_form=snapspeak_form,
        password_form=password_form,
        delete_form=delete_form,
        has_push_subscription=has_push_subscription,
        vapid_public_key=current_app.config.get("VAPID_PUBLIC_KEY"),
        **_sidebar_payload(current_user.id),
    )


@profile_bp.post("/settings/personal")
@login_required
def update_personal_settings():
    form = PersonalInfoForm(prefix="personal")
    if not form.validate_on_submit():
        for field_errors in form.errors.values():
            for error in field_errors:
                flash(error, "error")
        return redirect(url_for("profile.settings"))

    new_email = form.email.data.strip().lower()
    if new_email != current_user.email:
        existing = current_user.__class__.query.filter_by(email=new_email).first()
        if existing is not None and existing.id != current_user.id:
            flash("That email address is already in use by another account.", "error")
            return redirect(url_for("profile.settings"))

        current_user.email = new_email
        current_user.email_verified = False
        flash(
            "Email updated. Please verify your new email address before your next login.",
            "warning",
        )

    current_user.display_name = form.display_name.data.strip()
    current_user.country = form.country.data or None
    current_user.l1_language = form.l1_language.data or None
    current_user.professional_context = form.professional_context.data or "Other"

    db.session.commit()
    flash("Personal information updated successfully.", "success")
    return redirect(url_for("profile.settings"))


@profile_bp.post("/settings/snapspeak")
@login_required
def update_snapspeak_settings():
    form = SnapSpeakSettingsForm(prefix="snapspeak")
    if not form.validate_on_submit():
        for field_errors in form.errors.values():
            for error in field_errors:
                flash(error, "error")
        return redirect(url_for("profile.settings"))

    preferred_start = _parse_time(form.preferred_snapspeak_start.data)
    preferred_end = _parse_time(form.preferred_snapspeak_end.data)

    if form.snapspeak_opted_in.data and (preferred_start is None or preferred_end is None):
        flash("Choose both start and end times when SnapSpeak notifications are enabled.", "error")
        return redirect(url_for("profile.settings"))

    current_user.snapspeak_opted_in = bool(form.snapspeak_opted_in.data)
    current_user.preferred_snapspeak_start = preferred_start
    current_user.preferred_snapspeak_end = preferred_end
    current_user.weekly_report_opted_in = bool(form.weekly_report_opted_in.data)
    current_user.session_reminder_opted_in = bool(form.session_reminder_opted_in.data)

    db.session.commit()
    flash("SnapSpeak and notification preferences updated.", "success")
    return redirect(url_for("profile.settings"))


@profile_bp.post("/settings/password")
@login_required
def update_password_settings():
    form = ChangePasswordForm(prefix="password")
    if not form.validate_on_submit():
        for field_errors in form.errors.values():
            for error in field_errors:
                flash(error, "error")
        return redirect(url_for("profile.settings"))

    if not current_user.check_password(form.current_password.data):
        flash("Current password is incorrect.", "error")
        return redirect(url_for("profile.settings"))

    if current_user.check_password(form.new_password.data):
        flash("Choose a new password that is different from your current password.", "error")
        return redirect(url_for("profile.settings"))

    current_user.set_password(form.new_password.data)
    db.session.commit()
    flash("Password changed successfully.", "success")
    return redirect(url_for("profile.settings"))


@profile_bp.post("/settings/export")
@login_required
def export_profile_data():
    if not _validate_csrf_from_request():
        flash("Security token expired. Please try again.", "error")
        return redirect(url_for("profile.settings"))

    payload = {
        "user": current_user.to_dict(),
        "pgi_records": [record.to_dict() for record in current_user.pgi_records.order_by(PgiRecord.week_start_date.asc()).all()],
        "training_sessions": [
            session.to_dict()
            for session in current_user.training_sessions.order_by(TrainingSession.created_at.asc()).all()
        ],
        "lsrc_scores": [
            score.to_dict()
            for score in LsrcScore.query.filter_by(user_id=current_user.id)
            .order_by(LsrcScore.scored_at.asc())
            .all()
        ],
        "exported_at": datetime.utcnow().isoformat(),
    }

    response = Response(json.dumps(payload, indent=2), mimetype="application/json")
    response.headers["Content-Disposition"] = "attachment; filename=pressureproof_data_export.json"
    return response


@profile_bp.post("/settings/delete")
@login_required
def delete_account():
    form = DeleteAccountForm(prefix="delete")
    if not form.validate_on_submit() or (form.confirm_text.data or "").strip().upper() != "DELETE":
        flash('Type "DELETE" exactly to confirm account deletion.', "error")
        return redirect(url_for("profile.settings"))

    user = current_user._get_current_object()
    fallback_email = f"deleted_{user.id}_{int(datetime.utcnow().timestamp())}@deleted.local"

    try:
        db.session.delete(user)
        db.session.commit()
        logout_user()
        flash("Your account and associated profile have been deleted.", "success")
        return redirect(url_for("public.index"))
    except Exception:
        db.session.rollback()

    user.email = fallback_email
    user.display_name = "Deleted User"
    user.country = None
    user.l1_language = None
    user.professional_context = "Other"
    user.email_verified = False
    user.snapspeak_opted_in = False
    user.weekly_report_opted_in = False
    user.session_reminder_opted_in = False
    user.preferred_snapspeak_start = None
    user.preferred_snapspeak_end = None
    user.set_password(f"Deleted{user.id}UserA1")
    db.session.commit()

    logout_user()
    flash("Your account has been deactivated and personal details removed.", "success")
    return redirect(url_for("public.index"))


@profile_bp.get("/subscription")
@login_required
def subscription():
    subscription_status = get_subscription_status(current_user.id)
    usage_stats = None
    payment_history = []

    if subscription_status.get("tier") in {"professional", "pro_annual"} and subscription_status.get("is_active"):
        expires_at = current_user.subscription_expires_at or datetime.utcnow()
        if subscription_status.get("tier") == "pro_annual":
            period_start = expires_at - timedelta(days=365)
            amount_inr = 6499
            plan_label = "Pro Annual"
        else:
            period_start = expires_at - timedelta(days=30)
            amount_inr = 799
            plan_label = "Professional Monthly"

        usage_stats = {
            "sessions_completed": TrainingSession.query.filter(
                TrainingSession.user_id == current_user.id,
                TrainingSession.status == "completed",
                TrainingSession.created_at >= period_start,
            ).count(),
            "snapspeaks_captured": SnapSpeakRecord.query.filter(
                SnapSpeakRecord.user_id == current_user.id,
                SnapSpeakRecord.captured_at >= period_start,
            ).count(),
            "drills_completed": DrillCompletion.query.filter(
                DrillCompletion.user_id == current_user.id,
                DrillCompletion.completed_at >= period_start,
            ).count(),
            "lsrc_generated": LsrcScore.query.filter(
                LsrcScore.user_id == current_user.id,
                LsrcScore.scored_at >= period_start,
            ).count(),
        }

        payment_history.append(
            {
                "date": period_start.date().isoformat(),
                "amount": amount_inr,
                "plan": plan_label,
                "status": "Paid",
                "payment_id": current_user.razorpay_last_payment_id,
            }
        )

    compact_plan_data = {
        "monthly": {"price": 799, "label": "Professional Monthly"},
        "annual": {"price": 6499, "label": "Pro Annual"},
    }

    return render_template(
        "profile/subscription.html",
        title="My Subscription - PressureProof",
        subscription_status=subscription_status,
        usage_stats=usage_stats,
        payment_history=payment_history,
        compact_plan_data=compact_plan_data,
        **_sidebar_payload(current_user.id),
    )
