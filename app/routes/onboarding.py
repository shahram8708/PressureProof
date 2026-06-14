from datetime import time

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user
from flask_wtf.csrf import generate_csrf

from app.extensions import db
from app.forms.onboarding_forms import OnboardingStep1Form
from app.models import Assessment, FailureMode, LsrcScore
from app.utils.decorators import login_required
from app.utils.helpers import (
    compute_pgi_estimate,
    generate_profile_narrative,
    get_prompt_for_context,
)


onboarding_bp = Blueprint("onboarding", __name__, url_prefix="/onboarding")


@onboarding_bp.before_request
def _redirect_if_onboarding_complete():
    if current_user.is_authenticated and current_user.onboarding_complete:
        return redirect(url_for("dashboard.index"))
    return None


@onboarding_bp.route("/step-1", methods=["GET", "POST"])
@login_required
def step1():
    form = OnboardingStep1Form()

    if request.method == "POST" and form.validate_on_submit():
        session["target_situation"] = form.target_situation.data
        session["frequency"] = form.frequency.data
        session["tried_other_apps"] = form.tried_other_apps.data

        preferred_windows = {
            "morning": (time(6, 0), time(12, 0)),
            "midday": (time(12, 0), time(17, 0)),
            "evening": (time(17, 0), time(22, 0)),
        }
        start_time, end_time = preferred_windows[form.preferred_snapspeak_window.data]
        current_user.preferred_snapspeak_start = start_time
        current_user.preferred_snapspeak_end = end_time
        current_user.snapspeak_opted_in = bool(form.snapspeak_opt_in.data)

        db.session.commit()
        return redirect(url_for("onboarding.step2"))

    return render_template(
        "onboarding/step1.html",
        title="Step 1 - Your Context",
        form=form,
        current_step=1,
        total_steps=3,
        hide_sidebar=True,
        no_sidebar=True,
    )


@onboarding_bp.get("/step-2")
@login_required
def step2():
    professional_context = current_user.professional_context or "Other"
    prepared_prompt = get_prompt_for_context(professional_context, "prepared")
    spontaneous_prompt = get_prompt_for_context(professional_context, "spontaneous")

    return render_template(
        "onboarding/step2.html",
        title="Step 2 - Your Baseline",
        current_step=2,
        total_steps=3,
        prepared_prompt=prepared_prompt,
        spontaneous_prompt=spontaneous_prompt,
        baseline_submit_url=url_for("api.submit_baseline_assessment"),
        csrf_token_value=generate_csrf(),
        hide_sidebar=True,
        no_sidebar=True,
    )


@onboarding_bp.get("/step-3")
@login_required
def step3():
    baseline_assessment = (
        Assessment.query.filter_by(
            user_id=current_user.id,
            assessment_type="baseline",
            status="completed",
        )
        .order_by(Assessment.created_at.desc())
        .first()
    )

    if baseline_assessment is None:
        flash("Please complete your baseline recording first.", "warning")
        return redirect(url_for("onboarding.step2"))

    prepared_score = (
        LsrcScore.query.filter_by(
            user_id=current_user.id,
            source_type="assessment",
            source_id=baseline_assessment.id,
            condition="prepared",
        )
        .order_by(LsrcScore.scored_at.desc())
        .first()
    )

    spontaneous_score = (
        LsrcScore.query.filter_by(
            user_id=current_user.id,
            source_type="assessment",
            source_id=baseline_assessment.id,
            condition="spontaneous",
        )
        .order_by(LsrcScore.scored_at.desc())
        .first()
    )

    if prepared_score is None or spontaneous_score is None:
        flash("Your baseline analysis is still finalizing. Please try again shortly.", "warning")
        return redirect(url_for("onboarding.step2"))

    failure_mode = FailureMode.query.filter_by(user_id=current_user.id).first()
    narrative = generate_profile_narrative(prepared_score, spontaneous_score)
    pgi_estimate = compute_pgi_estimate(prepared_score, spontaneous_score)

    return render_template(
        "onboarding/step3.html",
        title="Step 3 - Your Pressure Profile",
        current_step=3,
        total_steps=3,
        prepared_score=prepared_score,
        spontaneous_score=spontaneous_score,
        failure_mode=failure_mode,
        narrative=narrative,
        pgi_estimate=pgi_estimate,
        hide_sidebar=True,
        no_sidebar=True,
    )


@onboarding_bp.post("/step-3")
@login_required
def complete_onboarding():
    current_user.onboarding_complete = True
    db.session.commit()
    flash("Your profile is ready. Let's start training.", "success")
    next_url = session.pop("post_onboarding_next", None)
    if next_url:
        return redirect(next_url)
    return redirect(url_for("sessions.new_session"))
