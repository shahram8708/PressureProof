from datetime import date, datetime, time, timedelta
import math

from flask import Blueprint, current_app, render_template, request
from flask_login import current_user

from app.models import DrillCompletion, SnapSpeakRecord
from app.utils.decorators import login_required
from app.utils.helpers import get_sidebar_context, select_snapspeak_prompt


snapspeak_bp = Blueprint("snapspeak", __name__, url_prefix="/")


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


@snapspeak_bp.get("/snapspeak")
@login_required
def capture():
    prompt_text, prompt_type = select_snapspeak_prompt(current_user)

    snapspeak_record = SnapSpeakRecord(
        user_id=current_user.id,
        captured_at=datetime.utcnow(),
        prompt_text=prompt_text,
        prompt_type=prompt_type,
        status="pending",
    )

    from app.extensions import db

    db.session.add(snapspeak_record)
    db.session.commit()

    vapid_public_key = current_app.config.get("VAPID_PUBLIC_KEY")

    return render_template(
        "snapspeak/capture.html",
        title="SnapSpeak - PressureProof",
        snapspeak_record=snapspeak_record,
        prompt_text=prompt_text,
        vapid_public_key=vapid_public_key,
        submit_endpoint=request.url_root.rstrip("/") + "/api/snapspeak/submit",
        notifications_enabled=bool(current_user.snapspeak_opted_in),
        hide_header=True,
        hide_footer=True,
        hide_sidebar=True,
        no_sidebar=True,
        **_sidebar_payload(current_user.id),
    )
@snapspeak_bp.get("/snapspeak/history")
@login_required
def history():
    active_tag_filter = (request.args.get("tag") or "").strip().lower()
    if active_tag_filter not in {"work", "casual", "preparation"}:
        active_tag_filter = None

    page = request.args.get("page", 1, type=int)
    page = max(1, page)
    per_page = 10

    snapspeaks = SnapSpeakRecord.get_user_history(
        current_user.id,
        tag_filter=active_tag_filter,
        limit=50,
    )

    total_records = len(snapspeaks)
    total_pages = max(1, math.ceil(total_records / per_page))
    page = min(page, total_pages)

    start_index = (page - 1) * per_page
    end_index = start_index + per_page
    paged_snapspeaks = snapspeaks[start_index:end_index]

    drill_stats = DrillCompletion.get_user_stats(current_user.id)
    week_start = datetime.combine(date.today() - timedelta(days=date.today().weekday()), time.min)
    week_end = week_start + timedelta(days=7)

    this_week_count = len(
        [
            record
            for record in snapspeaks
            if record.captured_at is not None and week_start <= record.captured_at < week_end
        ]
    )

    trend_direction = "flat"
    recent_trend = drill_stats.get("recent_trend") or []
    if len(recent_trend) >= 2:
        if recent_trend[-1] < recent_trend[-2]:
            trend_direction = "improving"
        elif recent_trend[-1] > recent_trend[-2]:
            trend_direction = "slower"

    return render_template(
        "snapspeak/history.html",
        title="SnapSpeak History - PressureProof",
        snapspeaks=paged_snapspeaks,
        all_snapspeaks_count=total_records,
        this_week_count=this_week_count,
        active_tag_filter=active_tag_filter,
        drill_stats=drill_stats,
        trend_direction=trend_direction,
        page=page,
        total_pages=total_pages,
        **_sidebar_payload(current_user.id),
    )
