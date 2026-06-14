from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_mail import Message
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db, mail
from app.forms.auth_forms import (
    ForgotPasswordForm,
    LoginForm,
    RegistrationForm,
    ResetPasswordForm,
)
from app.models import User


auth_bp = Blueprint("auth", __name__, url_prefix="/")


def _is_safe_next_url(target):
    if not target:
        return False

    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


def _send_html_email(subject, recipient, html_body):
    message = Message(subject=subject, recipients=[recipient], html=html_body)
    try:
        mail.send(message)
    except Exception as exc:
        current_app.logger.warning("Email delivery failed: %s", exc)


def send_verification_email(user):
    verification_link = url_for("auth.verify_email", token=user.generate_verification_token(), _external=True)
    html_body = f"""
    <div style="font-family: Inter, Arial, sans-serif; background: #F9FAFB; padding: 32px; color: #111827;">
      <table style="max-width: 600px; margin: 0 auto; background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 12px; border-collapse: collapse; overflow: hidden;">
        <tr>
          <td style="background: #1E1B4B; color: #FFFFFF; padding: 20px 24px; font-size: 22px; font-weight: 700;">PressureProof</td>
        </tr>
        <tr>
          <td style="padding: 24px; line-height: 1.6; font-size: 15px;">
            <p style="margin-top: 0;">Hi {user.display_name or 'there'},</p>
            <p>Welcome to PressureProof. Please verify your email address to activate your account and start your free assessment.</p>
            <p style="margin: 28px 0;">
              <a href="{verification_link}" style="display: inline-block; background: #F59E0B; color: #111827; text-decoration: none; padding: 12px 20px; border-radius: 8px; font-weight: 600;">Verify email address</a>
            </p>
            <p>If the button does not work, copy and paste this link into your browser:</p>
            <p style="word-break: break-word; color: #4F46E5;">{verification_link}</p>
            <p style="margin-bottom: 0; color: #6B7280;">If you did not create this account, you can safely ignore this email.</p>
          </td>
        </tr>
      </table>
    </div>
    """
    _send_html_email("Verify your PressureProof email", user.email, html_body)


def send_password_reset_email(user):
    reset_link = url_for(
        "auth.reset_password_get",
        token=user.generate_password_reset_token(),
        _external=True,
    )
    html_body = f"""
    <div style="font-family: Inter, Arial, sans-serif; background: #F9FAFB; padding: 32px; color: #111827;">
      <table style="max-width: 600px; margin: 0 auto; background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 12px; border-collapse: collapse; overflow: hidden;">
        <tr>
          <td style="background: #1E1B4B; color: #FFFFFF; padding: 20px 24px; font-size: 22px; font-weight: 700;">PressureProof</td>
        </tr>
        <tr>
          <td style="padding: 24px; line-height: 1.6; font-size: 15px;">
            <p style="margin-top: 0;">Hi {user.display_name or 'there'},</p>
            <p>We received a request to reset your password. This link is valid for one hour.</p>
            <p style="margin: 28px 0;">
              <a href="{reset_link}" style="display: inline-block; background: #F59E0B; color: #111827; text-decoration: none; padding: 12px 20px; border-radius: 8px; font-weight: 600;">Reset password</a>
            </p>
            <p>If the button does not work, copy and paste this link into your browser:</p>
            <p style="word-break: break-word; color: #4F46E5;">{reset_link}</p>
            <p style="margin-bottom: 0; color: #6B7280;">If you did not request this reset, no action is required.</p>
          </td>
        </tr>
      </table>
    </div>
    """
    _send_html_email("Reset your PressureProof password", user.email, html_body)


@auth_bp.get("/register")
def register_get():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = RegistrationForm()
    return render_template("auth/register.html", form=form, title="Create your PressureProof account")


@auth_bp.post("/register")
def register_post():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = RegistrationForm()
    if not form.validate_on_submit():
        return render_template("auth/register.html", form=form, title="Create your PressureProof account")

    existing_user = User.query.filter_by(email=form.email.data.strip().lower()).first()
    if existing_user:
        flash("An account with that email already exists. Please log in instead.", "error")
        return render_template("auth/register.html", form=form, title="Create your PressureProof account")

    user = User(
        email=form.email.data.strip().lower(),
        display_name=form.email.data.strip().split("@")[0].title(),
        country=form.country.data,
        l1_language=form.l1_language.data,
        professional_context=form.professional_context.data,
        trial_ends_at=datetime.utcnow() + timedelta(days=14),
    )
    user.set_password(form.password.data)

    try:
        db.session.add(user)
        db.session.commit()
        send_verification_email(user)
        flash("Account created! Please check your email to verify your address.", "success")
        return redirect(url_for("auth.login_get"))
    except SQLAlchemyError:
        db.session.rollback()
        flash("We could not create your account right now. Please try again.", "error")
        return render_template("auth/register.html", form=form, title="Create your PressureProof account")


@auth_bp.get("/login")
def login_get():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()
    return render_template("auth/login.html", form=form, title="Log in to PressureProof")


@auth_bp.post("/login")
def login_post():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()
    if not form.validate_on_submit():
        return render_template("auth/login.html", form=form, title="Log in to PressureProof")

    user = User.query.filter_by(email=form.email.data.strip().lower()).first()
    if user is None or not user.check_password(form.password.data):
        flash("Invalid email or password.", "error")
        return render_template("auth/login.html", form=form, title="Log in to PressureProof")

    if user.is_banned:
        flash("Your account has been suspended. Contact support@pressureproof.com.", "error")
        return render_template("auth/login.html", form=form, title="Log in to PressureProof")

    if not user.email_verified:
        flash("Please verify your email address before logging in.", "warning")
        return render_template("auth/login.html", form=form, title="Log in to PressureProof")

    user.last_login_at = datetime.utcnow()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    login_user(user, remember=form.remember_me.data)
    display_name = user.display_name or user.email.split("@")[0]
    flash(f"Welcome back, {display_name}!", "success")

    next_url = request.args.get("next")
    if not user.onboarding_complete:
        if next_url and _is_safe_next_url(next_url):
            session["post_onboarding_next"] = next_url
        return redirect(url_for("onboarding.step1"))
    if next_url and _is_safe_next_url(next_url):
        return redirect(next_url)
    return redirect(url_for("dashboard.index"))


@auth_bp.get("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("public.index"))


@auth_bp.get("/verify-email/<token>")
def verify_email(token):
    email = User.verify_token(token)
    if email is None:
        flash("This verification link is invalid or has expired.", "error")
        return redirect(url_for("auth.login_get"))

    user = User.query.filter_by(email=email).first()
    if user is None:
        flash("This verification link is invalid or has expired.", "error")
        return redirect(url_for("auth.login_get"))

    user.email_verified = True
    db.session.commit()
    flash("Email verified successfully! You can now log in.", "success")
    return redirect(url_for("auth.login_get"))


@auth_bp.get("/forgot-password")
def forgot_password_get():
    form = ForgotPasswordForm()
    return render_template("auth/forgot_password.html", form=form, title="Reset your password")


@auth_bp.post("/forgot-password")
def forgot_password_post():
    form = ForgotPasswordForm()

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.strip().lower()).first()
        if user and user.email_verified:
            send_password_reset_email(user)

    flash(
        "If an account with that email exists, you will receive a reset link shortly.",
        "info",
    )
    return redirect(url_for("auth.forgot_password_get"))


@auth_bp.get("/reset-password/<token>")
def reset_password_get(token):
    email = User.verify_password_reset_token(token)
    if email is None:
        flash("This password reset link is invalid or has expired.", "error")
        return redirect(url_for("auth.forgot_password_get"))

    form = ResetPasswordForm()
    return render_template(
        "auth/reset_password.html",
        form=form,
        token=token,
        title="Choose a new password",
    )


@auth_bp.post("/reset-password/<token>")
def reset_password_post(token):
    email = User.verify_password_reset_token(token)
    if email is None:
        flash("This password reset link is invalid or has expired.", "error")
        return redirect(url_for("auth.forgot_password_get"))

    form = ResetPasswordForm()
    if not form.validate_on_submit():
        return render_template(
            "auth/reset_password.html",
            form=form,
            token=token,
            title="Choose a new password",
        )

    user = User.query.filter_by(email=email).first()
    if user is None:
        flash("This password reset link is invalid or has expired.", "error")
        return redirect(url_for("auth.forgot_password_get"))

    user.set_password(form.password.data)
    db.session.commit()
    flash("Password updated successfully.", "success")
    return redirect(url_for("auth.login_get"))
