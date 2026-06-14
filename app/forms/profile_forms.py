import re

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, ValidationError

from app.forms.auth_forms import COUNTRY_CHOICES, L1_LANGUAGE_CHOICES, PROFESSIONAL_CONTEXT_CHOICES


def _half_hour_time_choices(start_hour=6, end_hour=22):
    choices = [("", "Select time")]
    for hour in range(start_hour, end_hour + 1):
        for minute in [0, 30]:
            value = f"{hour:02d}:{minute:02d}"
            suffix = "AM" if hour < 12 else "PM"
            display_hour = hour % 12
            if display_hour == 0:
                display_hour = 12
            display = f"{display_hour}:{minute:02d} {suffix}"
            choices.append((value, display))
    return choices


TIME_WINDOW_CHOICES = _half_hour_time_choices()
PROFILE_L1_LANGUAGE_CHOICES = [("", "Prefer not to say")] + list(L1_LANGUAGE_CHOICES)
PROFILE_CONTEXT_CHOICES = [("", "Select context")] + list(PROFESSIONAL_CONTEXT_CHOICES)


def validate_password_complexity(form, field):
    password = field.data or ""
    has_upper = re.search(r"[A-Z]", password)
    has_digit = re.search(r"\d", password)
    if not has_upper or not has_digit:
        raise ValidationError("Password must include at least one uppercase letter and one number.")


class PersonalInfoForm(FlaskForm):
    display_name = StringField("Display name", validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    country = SelectField("Country", validators=[Optional()], choices=COUNTRY_CHOICES)
    l1_language = SelectField(
        "First language",
        validators=[Optional()],
        choices=PROFILE_L1_LANGUAGE_CHOICES,
    )
    professional_context = SelectField(
        "Professional context",
        validators=[Optional()],
        choices=PROFILE_CONTEXT_CHOICES,
    )
    submit_personal = SubmitField("Save personal information")


class SnapSpeakSettingsForm(FlaskForm):
    snapspeak_opted_in = BooleanField("Enable SnapSpeak random challenges")
    preferred_snapspeak_start = SelectField(
        "Preferred start time",
        validators=[Optional()],
        choices=TIME_WINDOW_CHOICES,
    )
    preferred_snapspeak_end = SelectField(
        "Preferred end time",
        validators=[Optional()],
        choices=TIME_WINDOW_CHOICES,
    )
    weekly_report_opted_in = BooleanField("Weekly email progress report")
    session_reminder_opted_in = BooleanField("Session reminder notifications")
    submit_snapspeak = SubmitField("Save SnapSpeak settings")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired()])
    new_password = PasswordField(
        "New password",
        validators=[DataRequired(), Length(min=8, max=128), validate_password_complexity],
    )
    confirm_new_password = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("new_password", message="Passwords must match.")],
    )
    submit_password = SubmitField("Change password")


class DeleteAccountForm(FlaskForm):
    confirm_text = StringField(
        "Type DELETE to confirm",
        validators=[DataRequired(), Length(min=6, max=6)],
    )
    submit_delete = SubmitField("Delete my account")


ProfileSettingsForm = PersonalInfoForm
SubscriptionPreferencesForm = SnapSpeakSettingsForm
