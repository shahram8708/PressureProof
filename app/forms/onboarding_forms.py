from flask_wtf import FlaskForm
from wtforms import BooleanField, RadioField, SelectField, SubmitField
from wtforms.validators import DataRequired


class OnboardingStep1Form(FlaskForm):
    target_situation = SelectField(
        "Target Situation",
        choices=[
            ("client_calls", "Client Calls"),
            ("job_interviews", "Job Interviews"),
            ("team_meetings", "Team Meetings"),
            ("test_preparation", "Test Preparation - IELTS/TOEFL/OET"),
            ("other", "Other"),
        ],
        validators=[DataRequired()],
    )

    frequency = SelectField(
        "How Often You Face This Situation",
        choices=[
            ("daily", "Daily"),
            ("few_times_week", "2-3 times per week"),
            ("weekly", "Weekly"),
            ("rarely", "Rarely"),
        ],
        validators=[DataRequired()],
    )

    tried_other_apps = RadioField(
        "Have You Tried Other English Speaking Apps Before",
        choices=[
            ("yes", "Yes"),
            ("no", "No"),
        ],
        validators=[DataRequired()],
    )

    preferred_snapspeak_window = SelectField(
        "Preferred SnapSpeak Window",
        choices=[
            ("morning", "Morning (6am-12pm)"),
            ("midday", "Midday (12pm-5pm)"),
            ("evening", "Evening (5pm-10pm)"),
        ],
        validators=[DataRequired()],
    )

    snapspeak_opt_in = BooleanField(
        "Allow PressureProof to send me a 90-second speaking challenge at random times during my selected window (essential for measuring real-world progress)"
    )

    submit = SubmitField("Continue to baseline assessment.")


OnboardingStepOneForm = OnboardingStep1Form
