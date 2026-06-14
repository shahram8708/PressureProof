import re

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError


COUNTRY_CHOICES = [
    ("", "Select your country"),
    ("Argentina", "Argentina"),
    ("Australia", "Australia"),
    ("Austria", "Austria"),
    ("Bangladesh", "Bangladesh"),
    ("Belgium", "Belgium"),
    ("Brazil", "Brazil"),
    ("Bulgaria", "Bulgaria"),
    ("Canada", "Canada"),
    ("Chile", "Chile"),
    ("China", "China"),
    ("Colombia", "Colombia"),
    ("Croatia", "Croatia"),
    ("Czech Republic", "Czech Republic"),
    ("Denmark", "Denmark"),
    ("Egypt", "Egypt"),
    ("Finland", "Finland"),
    ("France", "France"),
    ("Germany", "Germany"),
    ("Ghana", "Ghana"),
    ("Greece", "Greece"),
    ("Hong Kong", "Hong Kong"),
    ("Hungary", "Hungary"),
    ("India", "India"),
    ("Indonesia", "Indonesia"),
    ("Ireland", "Ireland"),
    ("Israel", "Israel"),
    ("Italy", "Italy"),
    ("Japan", "Japan"),
    ("Kenya", "Kenya"),
    ("Malaysia", "Malaysia"),
    ("Mexico", "Mexico"),
    ("Morocco", "Morocco"),
    ("Netherlands", "Netherlands"),
    ("New Zealand", "New Zealand"),
    ("Nigeria", "Nigeria"),
    ("Norway", "Norway"),
    ("Pakistan", "Pakistan"),
    ("Peru", "Peru"),
    ("Philippines", "Philippines"),
    ("Poland", "Poland"),
    ("Portugal", "Portugal"),
    ("Qatar", "Qatar"),
    ("Romania", "Romania"),
    ("Saudi Arabia", "Saudi Arabia"),
    ("Serbia", "Serbia"),
    ("Singapore", "Singapore"),
    ("Slovakia", "Slovakia"),
    ("South Africa", "South Africa"),
    ("South Korea", "South Korea"),
    ("Spain", "Spain"),
    ("Sri Lanka", "Sri Lanka"),
    ("Sweden", "Sweden"),
    ("Switzerland", "Switzerland"),
    ("Taiwan", "Taiwan"),
    ("Thailand", "Thailand"),
    ("Turkey", "Turkey"),
    ("Ukraine", "Ukraine"),
    ("United Arab Emirates", "United Arab Emirates"),
    ("United Kingdom", "United Kingdom"),
    ("United States", "United States"),
    ("Uruguay", "Uruguay"),
    ("Vietnam", "Vietnam"),
]


L1_LANGUAGE_CHOICES = [
    ("Hindi", "Hindi"),
    ("Tamil", "Tamil"),
    ("Telugu", "Telugu"),
    ("Marathi", "Marathi"),
    ("Bengali", "Bengali"),
    ("Gujarati", "Gujarati"),
    ("Punjabi", "Punjabi"),
    ("Filipino", "Filipino"),
    ("Vietnamese", "Vietnamese"),
    ("Indonesian", "Indonesian"),
    ("Polish", "Polish"),
    ("Romanian", "Romanian"),
    ("Arabic", "Arabic"),
    ("Swahili", "Swahili"),
    ("Other", "Other"),
]


PROFESSIONAL_CONTEXT_CHOICES = [
    ("IT Services", "IT Services"),
    ("BPO or Call Centre", "BPO or Call Centre"),
    ("Healthcare", "Healthcare"),
    ("Immigration Applicant", "Immigration Applicant"),
    ("Other", "Other"),
]


def validate_password_complexity(form, field):
    password = field.data or ""
    has_upper = re.search(r"[A-Z]", password)
    has_digit = re.search(r"\d", password)

    if not has_upper or not has_digit:
        raise ValidationError(
            "Password must include at least one uppercase letter and one number."
        )


class RegistrationForm(FlaskForm):
    email = StringField(
        "Email",
        validators=[DataRequired(), Email(), Length(max=255)],
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(),
            Length(min=8, max=128),
            validate_password_complexity,
        ],
    )
    confirm_password = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    country = SelectField("Country", validators=[DataRequired()], choices=COUNTRY_CHOICES)
    l1_language = SelectField(
        "First language",
        validators=[DataRequired()],
        choices=L1_LANGUAGE_CHOICES,
    )
    professional_context = SelectField(
        "Professional context",
        validators=[DataRequired()],
        choices=PROFESSIONAL_CONTEXT_CHOICES,
    )
    submit = SubmitField("Create account")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired()])
    remember_me = BooleanField("Remember me")
    submit = SubmitField("Log in")


class ForgotPasswordForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    submit = SubmitField("Send reset link")


class ResetPasswordForm(FlaskForm):
    password = PasswordField(
        "New password",
        validators=[
            DataRequired(),
            Length(min=8, max=128),
            validate_password_complexity,
        ],
    )
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Update password")
