from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import wraps
import secrets

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_mail import Message
from sqlalchemy import func, or_
import redis

from app.extensions import celery, db, mail
from app.models import (
    AdminAuditLog,
    AdminUser,
    AdminUserNote,
    Assessment,
    Certificate,
    CohortAggregate,
    DrillCompletion,
    FailureMode,
    InjectionEvent,
    LsrcScore,
    NotificationLog,
    PgiRecord,
    PushSubscription,
    SessionCalibration,
    SnapSpeakRecord,
    TrainingSession,
    User,
)
from app.services import certificate_generator, cohort_service
from app.services.payment_service import activate_subscription, cancel_subscription
from app.services.pgi_calculator import get_pgi_trend_data
from app.tasks import nightly_cohort_rebuild, send_snapspeak_notifications, weekly_report_email


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _redis_client():
    redis_url = (
        current_app.config.get("REDIS_URL")
        or current_app.config.get("CELERY_BROKER_URL")
        or "redis://localhost:6379/0"
    )
    return redis.Redis.from_url(redis_url, decode_responses=True)


def _get_admin_from_session():
    admin_id = session.get("admin_user_id")
    if not admin_id:
        return None
    return AdminUser.query.get(int(admin_id))


def admin_required(view_function):
    @wraps(view_function)
    def wrapped(*args, **kwargs):
        admin = _get_admin_from_session()
        if admin is None or not admin.is_active or admin.is_locked:
            abort(403)
        g.admin_user = admin
        return view_function(*args, **kwargs)

    return wrapped


def permission_required(permission):
    def decorator(view_function):
        @wraps(view_function)
        def wrapped(*args, **kwargs):
            admin = _get_admin_from_session()
            if admin is None or not admin.is_active or admin.is_locked:
                abort(403)
            if not admin.has_permission(permission):
                abort(403)
            g.admin_user = admin
            return view_function(*args, **kwargs)

        return wrapped

    return decorator


@admin_bp.context_processor
def admin_context():
    return {
        "admin_user": _get_admin_from_session(),
        "is_impersonating": bool(session.get("impersonating_user_id")),
        "impersonating_user_id": session.get("impersonating_user_id"),
    }


def _add_audit(action, target_type=None, target_id=None, details=None):
    admin = _get_admin_from_session()
    if admin is None:
        return
    AdminAuditLog.log_action(
        admin_id=admin.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
        request=request,
    )


@admin_bp.get("/login")
def login_get():
    admin = _get_admin_from_session()
    if admin is not None and admin.is_active and not admin.is_locked:
        return redirect(url_for("admin.dashboard"))
    return render_template("admin/login.html", title="Admin Login")


@admin_bp.post("/login")
def login_post():
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    admin = AdminUser.query.filter_by(email=email).first()
    if admin is None:
        flash("Invalid admin credentials.", "error")
        return render_template("admin/login.html", title="Admin Login"), 401

    if admin.is_locked:
        lock_until = admin.locked_until.strftime("%d %b %Y %H:%M UTC")
        flash(f"Account is locked until {lock_until}.", "error")
        return render_template("admin/login.html", title="Admin Login"), 423

    if not admin.check_password(password):
        admin.failed_login_attempts += 1
        if admin.failed_login_attempts >= 5:
            admin.locked_until = datetime.utcnow() + timedelta(minutes=30)
        db.session.commit()
        flash("Invalid admin credentials.", "error")
        return render_template("admin/login.html", title="Admin Login"), 401

    admin.unlock()
    admin.last_login_at = datetime.utcnow()
    admin.last_login_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    db.session.commit()

    session["admin_user_id"] = admin.id
    session.modified = True

    AdminAuditLog.log_action(
        admin_id=admin.id,
        action="admin.login",
        details={"role": admin.role},
        request=request,
    )

    return redirect(url_for("admin.dashboard"))


@admin_bp.get("/logout")
def logout():
    admin = _get_admin_from_session()
    if admin is not None:
        AdminAuditLog.log_action(
            admin_id=admin.id,
            action="admin.logout",
            request=request,
        )
    session.pop("admin_user_id", None)
    session.pop("impersonating_user_id", None)
    session.pop("impersonation_target_user_id", None)
    return redirect(url_for("admin.login_get"))


def _latest_user_pgi_map(user_ids):
    if not user_ids:
        return {}

    records = (
        PgiRecord.query.filter(PgiRecord.user_id.in_(user_ids))
        .order_by(PgiRecord.user_id.asc(), PgiRecord.week_start_date.desc())
        .all()
    )
    latest_map = {}
    for record in records:
        if record.user_id not in latest_map:
            latest_map[record.user_id] = _safe_float(record.pgi_score)
    return latest_map


def _session_count_map(user_ids):
    if not user_ids:
        return {}
    rows = (
        db.session.query(TrainingSession.user_id, func.count(TrainingSession.id))
        .filter(TrainingSession.user_id.in_(user_ids))
        .group_by(TrainingSession.user_id)
        .all()
    )
    return {user_id: int(count) for user_id, count in rows}


def _queue_health(redis_client):
    result = {}
    for queue_name in ["celery", "speech_analysis", "lsrc_update"]:
        try:
            result[queue_name] = int(redis_client.llen(queue_name))
        except Exception:
            result[queue_name] = 0
    return result


def _last_task_run(redis_client):
    keys = {
        "last_weekly_pgi_recalculation": "last_weekly_pgi_recalculation",
        "last_audio_cleanup": "last_audio_cleanup",
        "last_cohort_rebuild": "last_cohort_rebuild",
        "last_weekly_report_email": "last_weekly_report_email",
    }
    data = {}
    for label, key in keys.items():
        data[label] = redis_client.get(key)
    return data


@admin_bp.get("/dashboard")
@admin_required
def dashboard():
    now = datetime.utcnow()
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)

    total_users = User.query.count()
    verified_users = User.query.filter_by(email_verified=True).count()
    unverified_users = total_users - verified_users

    new_users_week = User.query.filter(User.created_at >= week_start).count()
    new_users_month = User.query.filter(User.created_at >= month_start).count()

    total_sessions = TrainingSession.query.count()
    sessions_week = TrainingSession.query.filter(TrainingSession.created_at >= week_start).count()

    total_snapspeaks = SnapSpeakRecord.query.count()
    snapspeaks_week = SnapSpeakRecord.query.filter(SnapSpeakRecord.captured_at >= week_start).count()

    monthly_subscriptions = User.query.filter_by(subscription_tier="professional").count()
    annual_subscriptions = User.query.filter_by(subscription_tier="pro_annual").count()
    total_paid = monthly_subscriptions + annual_subscriptions
    estimated_mrr = int((monthly_subscriptions * 799) + (annual_subscriptions * (6499 / 12)))

    free_trial_users = User.query.filter(
        User.subscription_tier == "free",
        User.trial_ends_at.isnot(None),
        User.trial_ends_at > now,
    ).count()
    trial_converted = User.query.filter(
        User.subscription_tier.in_(["professional", "pro_annual"]),
        User.trial_ends_at.isnot(None),
    ).count()
    trial_conversion_rate = round((trial_converted / max(1, free_trial_users + trial_converted)) * 100.0, 2)

    onboarding_complete = User.query.filter_by(onboarding_complete=True).count()

    avg_pgi_rows = db.session.query(PgiRecord.user_id, func.max(PgiRecord.week_start_date)).group_by(PgiRecord.user_id).all()
    latest_pgi_values = []
    for user_id, week_start_date in avg_pgi_rows:
        record = PgiRecord.query.filter_by(user_id=user_id, week_start_date=week_start_date).first()
        score = _safe_float(record.pgi_score if record else None)
        if score is not None:
            latest_pgi_values.append(score)
    average_pgi = round(sum(latest_pgi_values) / len(latest_pgi_values), 2) if latest_pgi_values else None

    active_user_count = db.session.query(TrainingSession.user_id).distinct().count()
    average_sessions_per_active_user = round(total_sessions / max(1, active_user_count), 2)

    total_certificates = Certificate.query.count()

    redis_client = _redis_client()
    queue_health = _queue_health(redis_client)
    last_run = _last_task_run(redis_client)

    recent_activity = (
        AdminAuditLog.query.order_by(AdminAuditLog.performed_at.desc())
        .limit(20)
        .all()
    )
    recent_registrations = (
        User.query.order_by(User.created_at.desc())
        .limit(10)
        .all()
    )

    failed_analysis = {
        "assessments": Assessment.query.filter_by(status="failed").count(),
        "sessions": TrainingSession.query.filter_by(status="failed").count(),
        "snapspeaks": SnapSpeakRecord.query.filter_by(status="failed").count(),
    }

    expiring_subscriptions = User.query.filter(
        User.subscription_tier.in_(["professional", "pro_annual"]),
        User.subscription_expires_at.isnot(None),
        User.subscription_expires_at <= now + timedelta(days=7),
        User.subscription_expires_at >= now,
    ).count()

    stats = {
        "total_users": total_users,
        "verified_users": verified_users,
        "unverified_users": unverified_users,
        "new_users_week": new_users_week,
        "new_users_month": new_users_month,
        "total_sessions": total_sessions,
        "sessions_week": sessions_week,
        "total_snapspeaks": total_snapspeaks,
        "snapspeaks_week": snapspeaks_week,
        "total_paid": total_paid,
        "monthly_subscriptions": monthly_subscriptions,
        "annual_subscriptions": annual_subscriptions,
        "estimated_mrr": estimated_mrr,
        "free_trial_users": free_trial_users,
        "trial_conversion_rate": trial_conversion_rate,
        "onboarding_complete": onboarding_complete,
        "average_pgi": average_pgi,
        "average_sessions_per_active_user": average_sessions_per_active_user,
        "total_certificates": total_certificates,
    }

    return render_template(
        "admin/dashboard.html",
        title="Admin Dashboard",
        stats=stats,
        queue_health=queue_health,
        last_run=last_run,
        recent_activity=recent_activity,
        recent_registrations=recent_registrations,
        failed_analysis=failed_analysis,
        expiring_subscriptions=expiring_subscriptions,
    )


@admin_bp.get("/users")
@permission_required("view_users")
def users_list():
    page = max(1, request.args.get("page", 1, type=int))
    search = (request.args.get("search") or "").strip()

    subscription_tier = (request.args.get("subscription_tier") or "all").strip()
    email_verified = (request.args.get("email_verified") or "all").strip()
    onboarding_complete = (request.args.get("onboarding_complete") or "all").strip()
    country = (request.args.get("country") or "").strip()
    l1_language = (request.args.get("l1_language") or "").strip()
    professional_context = (request.args.get("professional_context") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    sort_by = (request.args.get("sort_by") or "created_at").strip()

    query = User.query

    if search:
        term = f"%{search}%"
        query = query.filter(or_(User.email.ilike(term), User.display_name.ilike(term)))

    if subscription_tier in {"free", "professional", "pro_annual"}:
        query = query.filter(User.subscription_tier == subscription_tier)

    if email_verified == "verified":
        query = query.filter(User.email_verified.is_(True))
    elif email_verified == "unverified":
        query = query.filter(User.email_verified.is_(False))

    if onboarding_complete == "complete":
        query = query.filter(User.onboarding_complete.is_(True))
    elif onboarding_complete == "incomplete":
        query = query.filter(User.onboarding_complete.is_(False))

    if country:
        query = query.filter(User.country == country)
    if l1_language:
        query = query.filter(User.l1_language == l1_language)
    if professional_context:
        query = query.filter(User.professional_context == professional_context)

    if date_from:
        try:
            start_dt = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(User.created_at >= start_dt)
        except ValueError:
            pass

    if date_to:
        try:
            end_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(User.created_at < end_dt)
        except ValueError:
            pass

    if sort_by == "last_login":
        query = query.order_by(User.last_login_at.desc().nullslast(), User.created_at.desc())
    else:
        query = query.order_by(User.created_at.desc())

    pagination = query.paginate(page=page, per_page=25, error_out=False)
    users = list(pagination.items)

    user_ids = [user.id for user in users]
    session_map = _session_count_map(user_ids)
    pgi_map = _latest_user_pgi_map(user_ids)

    if sort_by in {"session_count", "current_pgi"}:
        reverse = True
        if sort_by == "session_count":
            users.sort(key=lambda item: session_map.get(item.id, 0), reverse=reverse)
        if sort_by == "current_pgi":
            users.sort(key=lambda item: pgi_map.get(item.id, -1), reverse=False)

    countries = [row[0] for row in db.session.query(User.country).filter(User.country.isnot(None)).distinct().order_by(User.country.asc()).all()]
    l1_languages = [row[0] for row in db.session.query(User.l1_language).filter(User.l1_language.isnot(None)).distinct().order_by(User.l1_language.asc()).all()]
    contexts = [row[0] for row in db.session.query(User.professional_context).filter(User.professional_context.isnot(None)).distinct().order_by(User.professional_context.asc()).all()]

    return render_template(
        "admin/users/list.html",
        title="User Management",
        users=users,
        pagination=pagination,
        session_map=session_map,
        pgi_map=pgi_map,
        countries=countries,
        l1_languages=l1_languages,
        contexts=contexts,
        filters={
            "search": search,
            "subscription_tier": subscription_tier,
            "email_verified": email_verified,
            "onboarding_complete": onboarding_complete,
            "country": country,
            "l1_language": l1_language,
            "professional_context": professional_context,
            "date_from": date_from,
            "date_to": date_to,
            "sort_by": sort_by,
        },
    )


@admin_bp.get("/users/<int:user_id>")
@permission_required("view_users")
def users_detail(user_id):
    user = User.query.get_or_404(user_id)

    sessions = (
        TrainingSession.query.filter_by(user_id=user.id)
        .order_by(TrainingSession.created_at.desc())
        .all()
    )
    session_ids = [row.id for row in sessions]
    lsrc_scores = (
        LsrcScore.query.filter_by(user_id=user.id)
        .order_by(LsrcScore.scored_at.desc())
        .all()
    )
    snapspeaks = (
        SnapSpeakRecord.query.filter_by(user_id=user.id)
        .order_by(SnapSpeakRecord.captured_at.desc())
        .all()
    )
    pgi_records = (
        PgiRecord.query.filter_by(user_id=user.id)
        .order_by(PgiRecord.week_start_date.asc())
        .all()
    )

    failure_mode = FailureMode.query.filter_by(user_id=user.id).first()
    certificate = Certificate.query.filter_by(user_id=user.id).first()
    drill_completions = (
        DrillCompletion.query.filter_by(user_id=user.id)
        .order_by(DrillCompletion.completed_at.desc())
        .all()
    )
    push_subscriptions = PushSubscription.query.filter_by(user_id=user.id).all()
    notification_logs = (
        NotificationLog.query.filter_by(user_id=user.id)
        .order_by(NotificationLog.scheduled_at.desc())
        .all()
    )
    admin_notes = (
        AdminUserNote.query.filter_by(user_id=user.id)
        .order_by(AdminUserNote.created_at.desc())
        .all()
    )

    radar_data = {
        "labels": [
            "Lexical Diversity",
            "Syntactic Complexity",
            "Prosodic Confidence",
            "Disfluency Rate",
            "Sentence Completion",
            "Recovery Speed",
        ],
        "datasets": [
            {
                "label": "Prepared",
                "data": [0, 0, 0, 0, 0, 0],
                "borderColor": "#4F46E5",
                "backgroundColor": "rgba(79,70,229,0.15)",
            },
            {
                "label": "Spontaneous",
                "data": [0, 0, 0, 0, 0, 0],
                "borderColor": "#F59E0B",
                "backgroundColor": "rgba(245,158,11,0.15)",
            },
        ],
        "has_data": False,
    }

    prepared = [score for score in lsrc_scores if score.condition == "prepared"][:10]
    spontaneous = [score for score in lsrc_scores if score.condition == "spontaneous"][:10]
    if prepared or spontaneous:
        radar_data["has_data"] = True

        def avg(entries, field):
            values = [_safe_float(getattr(entry, field, None)) for entry in entries]
            values = [value for value in values if value is not None]
            if not values:
                return 0
            return round(sum(values) / len(values), 2)

        radar_data["datasets"][0]["data"] = [
            avg(prepared, "lexical_diversity"),
            avg(prepared, "syntactic_complexity"),
            avg(prepared, "prosodic_confidence"),
            avg(prepared, "disfluency_rate"),
            avg(prepared, "sentence_completion"),
            avg(prepared, "recovery_speed_score"),
        ]
        radar_data["datasets"][1]["data"] = [
            avg(spontaneous, "lexical_diversity"),
            avg(spontaneous, "syntactic_complexity"),
            avg(spontaneous, "prosodic_confidence"),
            avg(spontaneous, "disfluency_rate"),
            avg(spontaneous, "sentence_completion"),
            avg(spontaneous, "recovery_speed_score"),
        ]

    pgi_trend = get_pgi_trend_data(user.id, weeks=12)

    return render_template(
        "admin/users/detail.html",
        title=f"User {user.display_name or user.email}",
        user=user,
        sessions=sessions,
        session_ids=session_ids,
        lsrc_scores=lsrc_scores,
        snapspeaks=snapspeaks,
        pgi_records=pgi_records,
        failure_mode=failure_mode,
        certificate=certificate,
        drill_completions=drill_completions,
        push_subscriptions=push_subscriptions,
        notification_logs=notification_logs,
        admin_notes=admin_notes,
        radar_data=radar_data,
        pgi_trend=pgi_trend,
    )


@admin_bp.get("/users/<int:user_id>/edit")
@permission_required("edit_users")
def users_edit_get(user_id):
    user = User.query.get_or_404(user_id)
    return render_template(
        "admin/users/edit.html",
        title=f"Edit {user.display_name or user.email}",
        user=user,
    )


@admin_bp.post("/users/<int:user_id>/edit")
@permission_required("edit_users")
def users_edit_post(user_id):
    user = User.query.get_or_404(user_id)

    tracked_fields = {
        "display_name": user.display_name,
        "email": user.email,
        "country": user.country,
        "l1_language": user.l1_language,
        "professional_context": user.professional_context,
        "subscription_tier": user.subscription_tier,
        "subscription_expires_at": user.subscription_expires_at.isoformat() if user.subscription_expires_at else None,
        "email_verified": user.email_verified,
        "onboarding_complete": user.onboarding_complete,
        "snapspeak_opted_in": user.snapspeak_opted_in,
    }

    user.display_name = (request.form.get("display_name") or "").strip() or user.display_name
    user.email = (request.form.get("email") or "").strip().lower() or user.email
    user.country = (request.form.get("country") or "").strip() or None
    user.l1_language = (request.form.get("l1_language") or "").strip() or None
    user.professional_context = (request.form.get("professional_context") or "").strip() or None

    tier = (request.form.get("subscription_tier") or user.subscription_tier).strip()
    if tier in {"free", "professional", "pro_annual"}:
        user.subscription_tier = tier

    expires_text = (request.form.get("subscription_expires_at") or "").strip()
    if expires_text:
        try:
            user.subscription_expires_at = datetime.fromisoformat(expires_text)
        except ValueError:
            try:
                user.subscription_expires_at = datetime.strptime(expires_text, "%Y-%m-%d")
            except ValueError:
                pass

    user.email_verified = bool(request.form.get("email_verified"))
    user.onboarding_complete = bool(request.form.get("onboarding_complete"))
    user.snapspeak_opted_in = bool(request.form.get("snapspeak_opted_in"))

    db.session.commit()

    updated_fields = {
        "display_name": user.display_name,
        "email": user.email,
        "country": user.country,
        "l1_language": user.l1_language,
        "professional_context": user.professional_context,
        "subscription_tier": user.subscription_tier,
        "subscription_expires_at": user.subscription_expires_at.isoformat() if user.subscription_expires_at else None,
        "email_verified": user.email_verified,
        "onboarding_complete": user.onboarding_complete,
        "snapspeak_opted_in": user.snapspeak_opted_in,
    }

    diff = {}
    for key, old_value in tracked_fields.items():
        new_value = updated_fields.get(key)
        if old_value != new_value:
            diff[key] = {"old": old_value, "new": new_value}

    _add_audit(
        "user.edit",
        target_type="user",
        target_id=user.id,
        details={"diff": diff},
    )

    flash("User profile updated.", "success")
    return redirect(url_for("admin.users_detail", user_id=user.id))


@admin_bp.post("/users/<int:user_id>/delete")
@permission_required("delete_users")
def users_delete(user_id):
    user = User.query.get_or_404(user_id)
    payload = request.get_json(silent=True) or {}
    confirmation = (payload.get("confirm") or "").strip().lower()

    if confirmation != (user.email or "").lower():
        return jsonify({"error": "Confirmation email does not match user email."}), 400

    session_ids = [row[0] for row in db.session.query(TrainingSession.id).filter_by(user_id=user.id).all()]
    if session_ids:
        InjectionEvent.query.filter(InjectionEvent.session_id.in_(session_ids)).delete(synchronize_session=False)

    Assessment.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    LsrcScore.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    PgiRecord.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    TrainingSession.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    SnapSpeakRecord.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    DrillCompletion.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    NotificationLog.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    PushSubscription.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    FailureMode.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    SessionCalibration.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    Certificate.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    AdminUserNote.query.filter_by(user_id=user.id).delete(synchronize_session=False)

    db.session.delete(user)
    db.session.commit()

    _add_audit(
        "user.delete",
        target_type="user",
        target_id=user_id,
        details={"email": user.email},
    )

    return jsonify({"status": "deleted"})


@admin_bp.get("/users/<int:user_id>/impersonate")
@admin_required
def users_impersonate(user_id):
    admin = g.admin_user
    if admin.role != "super_admin":
        abort(403)

    user = User.query.get_or_404(user_id)
    session["impersonating_user_id"] = user.id
    session["impersonation_target_user_id"] = user.id

    _add_audit(
        "user.impersonate",
        target_type="user",
        target_id=user.id,
        details={"email": user.email},
    )

    return redirect(url_for("dashboard.index"))


@admin_bp.get("/users/exit-impersonate")
@admin_required
def exit_impersonate():
    target_user_id = session.get("impersonation_target_user_id")
    session.pop("impersonating_user_id", None)
    session.pop("impersonation_target_user_id", None)

    _add_audit("user.exit_impersonate")

    if target_user_id:
        return redirect(url_for("admin.users_detail", user_id=target_user_id))
    return redirect(url_for("admin.users_list"))


@admin_bp.post("/users/<int:user_id>/add-note")
@permission_required("add_user_notes")
def users_add_note(user_id):
    user = User.query.get_or_404(user_id)
    payload = request.get_json(silent=True) or request.form

    note_text = (payload.get("note_text") or "").strip()
    note_type = (payload.get("note_type") or "general").strip().lower()
    if not note_text:
        return jsonify({"error": "note_text is required"}), 400

    if note_type not in {"general", "support", "billing", "technical", "risk"}:
        note_type = "general"

    note = AdminUserNote(
        user_id=user.id,
        admin_id=g.admin_user.id,
        note_text=note_text,
        note_type=note_type,
    )
    db.session.add(note)
    db.session.commit()

    _add_audit(
        "user.note",
        target_type="user",
        target_id=user.id,
        details={"note_id": note.id, "note_type": note_type},
    )

    return jsonify({"status": "created", "note_id": note.id})


@admin_bp.post("/users/<int:user_id>/subscription")
@permission_required("manage_subscriptions")
def users_subscription_action(user_id):
    user = User.query.get_or_404(user_id)
    payload = request.get_json(silent=True) or {}

    action = (payload.get("action") or "").strip().lower()
    plan = (payload.get("plan") or "").strip().lower()
    days = int(payload.get("days") or 0)

    if action == "upgrade":
        if plan not in {"professional", "pro_annual", "monthly", "annual"}:
            return jsonify({"error": "Invalid plan for upgrade."}), 400
        activate_subscription(user.id, plan, razorpay_payment_id="admin_override")

    elif action == "downgrade":
        cancel_subscription(user.id)

    elif action == "extend":
        if days <= 0:
            return jsonify({"error": "days must be a positive integer"}), 400
        if not user.subscription_expires_at:
            user.subscription_expires_at = datetime.utcnow() + timedelta(days=days)
        else:
            user.subscription_expires_at = user.subscription_expires_at + timedelta(days=days)
        db.session.commit()

    else:
        return jsonify({"error": "Invalid action."}), 400

    _add_audit(
        "subscription.modify",
        target_type="user",
        target_id=user.id,
        details={"action": action, "plan": plan, "days": days},
    )

    return jsonify({"status": "ok"})


@admin_bp.get("/sessions")
@permission_required("view_sessions")
def sessions_list():
    page = max(1, request.args.get("page", 1, type=int))

    query = TrainingSession.query

    user_id = request.args.get("user_id", type=int)
    if user_id:
        query = query.filter(TrainingSession.user_id == user_id)

    session_type = (request.args.get("session_type") or "").strip()
    if session_type:
        query = query.filter(TrainingSession.session_type == session_type)

    status = (request.args.get("status") or "").strip()
    if status:
        query = query.filter(TrainingSession.status == status)

    injection_type = (request.args.get("injection_type") or "").strip()
    if injection_type:
        query = query.filter(TrainingSession.stress_injection_type == injection_type)

    early_exit = (request.args.get("early_exit") or "").strip().lower()
    if early_exit in {"true", "false"}:
        query = query.filter(TrainingSession.early_exit.is_(early_exit == "true"))

    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()

    if date_from:
        try:
            query = query.filter(TrainingSession.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(TrainingSession.created_at < datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1))
        except ValueError:
            pass

    pagination = query.order_by(TrainingSession.created_at.desc()).paginate(page=page, per_page=50, error_out=False)
    sessions = list(pagination.items)

    user_ids = [row.user_id for row in sessions]
    users_map = {user.id: user for user in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}

    session_lsrc_map = {}
    if sessions:
        for item in sessions:
            score = (
                LsrcScore.query.filter_by(user_id=item.user_id, source_type="session", source_id=item.id)
                .order_by(LsrcScore.scored_at.desc())
                .first()
            )
            session_lsrc_map[item.id] = _safe_float(score.composite_score if score else None)

    return render_template(
        "admin/sessions/list.html",
        title="Sessions",
        sessions=sessions,
        users_map=users_map,
        session_lsrc_map=session_lsrc_map,
        pagination=pagination,
    )


def _count_series(model, datetime_column, days):
    today = date.today()
    start_date = today - timedelta(days=days - 1)

    grouped = (
        db.session.query(func.date(datetime_column), func.count(model.id))
        .filter(datetime_column >= datetime.combine(start_date, datetime.min.time()))
        .group_by(func.date(datetime_column))
        .all()
    )

    grouped_map = {str(row[0]): int(row[1]) for row in grouped}
    labels = []
    values = []
    for offset in range(days):
        d = start_date + timedelta(days=offset)
        key = d.isoformat()
        labels.append(d.strftime("%d %b"))
        values.append(grouped_map.get(key, 0))
    return labels, values


@admin_bp.get("/analytics")
@permission_required("view_analytics")
def analytics():
    user_labels, user_values = _count_series(User, User.created_at, 90)
    session_labels, session_values = _count_series(TrainingSession, TrainingSession.created_at, 30)
    snap_labels, snap_values = _count_series(SnapSpeakRecord, SnapSpeakRecord.captured_at, 30)

    registered = User.query.count()
    verified = User.query.filter_by(email_verified=True).count()
    onboarded = User.query.filter_by(onboarding_complete=True).count()
    first_session_users = db.session.query(TrainingSession.user_id).distinct().count()
    paid = User.query.filter(User.subscription_tier.in_(["professional", "pro_annual"])).count()

    pgi_distribution = [0] * 10
    latest_records = (
        PgiRecord.query.order_by(PgiRecord.user_id.asc(), PgiRecord.week_start_date.desc())
        .all()
    )
    seen = set()
    for record in latest_records:
        if record.user_id in seen:
            continue
        seen.add(record.user_id)
        value = _safe_float(record.pgi_score)
        if value is None:
            continue
        bucket = min(9, max(0, int(value // 10)))
        pgi_distribution[bucket] += 1

    context_rows = (
        db.session.query(User.professional_context, func.count(User.id))
        .group_by(User.professional_context)
        .order_by(func.count(User.id).desc())
        .all()
    )
    l1_rows = (
        db.session.query(User.l1_language, func.count(User.id))
        .group_by(User.l1_language)
        .order_by(func.count(User.id).desc())
        .all()
    )

    cohort_rows = CohortAggregate.query.filter_by(dimension="pgi").order_by(CohortAggregate.user_count.desc()).all()

    analytics_payload = {
        "registrations": {"labels": user_labels, "data": user_values},
        "sessions": {"labels": session_labels, "data": session_values},
        "snapspeaks": {"labels": snap_labels, "data": snap_values},
        "funnel": {
            "labels": ["Registered", "Verified", "Onboarded", "First Session", "Paid"],
            "data": [registered, verified, onboarded, first_session_users, paid],
        },
        "pgi_distribution": {
            "labels": ["0-9", "10-19", "20-29", "30-39", "40-49", "50-59", "60-69", "70-79", "80-89", "90-100"],
            "data": pgi_distribution,
        },
        "professional_context": {
            "labels": [row[0] or "Unknown" for row in context_rows],
            "data": [int(row[1]) for row in context_rows],
        },
        "l1_distribution": {
            "labels": [row[0] or "Unknown" for row in l1_rows],
            "data": [int(row[1]) for row in l1_rows],
        },
        "cohort_improvement": {
            "labels": [row.cohort_key for row in cohort_rows],
            "data": [_safe_float(row.percentile_50) or 0 for row in cohort_rows],
        },
    }

    return render_template(
        "admin/analytics/index.html",
        title="Analytics",
        analytics_payload=analytics_payload,
    )


@admin_bp.get("/cohorts")
@permission_required("manage_cohorts")
def cohorts_index():
    cohort_rows = CohortAggregate.query.order_by(CohortAggregate.cohort_key.asc()).all()
    grouped = defaultdict(dict)
    for row in cohort_rows:
        grouped[row.cohort_key][row.dimension] = row

    items = []
    for cohort_key, dimensions in grouped.items():
        pgi_row = dimensions.get("pgi")
        median_pgi = _safe_float(pgi_row.percentile_50) if pgi_row else None
        user_count = pgi_row.user_count if pgi_row else max((value.user_count for value in dimensions.values()), default=0)
        last_updated = pgi_row.last_updated if pgi_row else None
        items.append(
            {
                "cohort_key": cohort_key,
                "user_count": user_count,
                "median_pgi": median_pgi,
                "last_updated": last_updated,
            }
        )

    return render_template(
        "admin/cohorts/index.html",
        title="Cohorts",
        cohorts=items,
    )


@admin_bp.post("/cohorts/rebuild")
@permission_required("manage_cohorts")
def cohorts_rebuild():
    task = nightly_cohort_rebuild.delay()
    _add_audit("cohort.rebuild", details={"task_id": task.id})
    return jsonify({"status": "queued", "task_id": task.id})


@admin_bp.get("/certificates")
@permission_required("view_certificates")
def certificates_index():
    query = Certificate.query.join(User, User.id == Certificate.user_id)

    user_search = (request.args.get("user") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()

    if user_search:
        term = f"%{user_search}%"
        query = query.filter(or_(User.email.ilike(term), User.display_name.ilike(term)))

    if date_from:
        try:
            query = query.filter(Certificate.generated_at >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(Certificate.generated_at < datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1))
        except ValueError:
            pass

    certificates = query.order_by(Certificate.generated_at.desc()).all()
    return render_template(
        "admin/certificates/index.html",
        title="Certificates",
        certificates=certificates,
    )


@admin_bp.post("/certificates/<int:certificate_id>/revoke")
@permission_required("view_certificates")
def certificates_revoke(certificate_id):
    certificate = Certificate.query.get_or_404(certificate_id)
    certificate.is_public = False
    db.session.commit()

    _add_audit(
        "certificate.revoke",
        target_type="certificate",
        target_id=certificate.id,
        details={"user_id": certificate.user_id},
    )
    return jsonify({"status": "ok"})


@admin_bp.post("/certificates/<int:certificate_id>/regenerate")
@permission_required("view_certificates")
def certificates_regenerate(certificate_id):
    certificate = Certificate.query.get_or_404(certificate_id)
    certificate_generator.generate_certificate(certificate.user_id)

    _add_audit(
        "certificate.regenerate",
        target_type="certificate",
        target_id=certificate.id,
        details={"user_id": certificate.user_id},
    )
    return jsonify({"status": "ok"})


@admin_bp.get("/notifications")
@permission_required("send_notifications")
def notifications_index():
    query = NotificationLog.query

    notification_type = (request.args.get("type") or "").strip()
    sent_status = (request.args.get("sent") or "").strip().lower()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()

    if notification_type:
        query = query.filter(NotificationLog.notification_type == notification_type)

    if sent_status == "sent":
        query = query.filter(NotificationLog.sent_at.isnot(None))
    elif sent_status == "pending":
        query = query.filter(NotificationLog.sent_at.is_(None))

    if date_from:
        try:
            query = query.filter(NotificationLog.scheduled_at >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass

    if date_to:
        try:
            query = query.filter(NotificationLog.scheduled_at < datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1))
        except ValueError:
            pass

    notifications = query.order_by(NotificationLog.scheduled_at.desc()).limit(500).all()
    total_sent = NotificationLog.query.filter(NotificationLog.sent_at.isnot(None)).count()
    total_opened = NotificationLog.query.filter(NotificationLog.sent_at.isnot(None), NotificationLog.opened.is_(True)).count()
    opened_rate = round((total_opened / max(1, total_sent)) * 100.0, 2)

    return render_template(
        "admin/notifications/index.html",
        title="Notifications",
        notifications=notifications,
        total_sent=total_sent,
        opened_rate=opened_rate,
    )


@admin_bp.post("/notifications/bulk-send")
@permission_required("send_notifications")
def notifications_bulk_send():
    payload = request.get_json(silent=True) or request.form

    notification_type = (payload.get("notification_type") or "").strip().lower()
    segment = (payload.get("segment") or "all_users").strip().lower()
    custom_message = (payload.get("custom_message") or "").strip()

    if notification_type == "snapspeak reminder":
        task = send_snapspeak_notifications.delay()
        _add_audit("notification.bulk_send", details={"type": notification_type, "task_id": task.id})
        return jsonify({"status": "queued", "task_id": task.id})

    if notification_type == "weekly report":
        task = weekly_report_email.delay()
        _add_audit("notification.bulk_send", details={"type": notification_type, "task_id": task.id})
        return jsonify({"status": "queued", "task_id": task.id})

    query = User.query
    if segment == "free_users":
        query = query.filter(User.subscription_tier == "free")
    elif segment == "paid_users":
        query = query.filter(User.subscription_tier.in_(["professional", "pro_annual"]))
    elif segment == "inactive_7_days":
        cutoff = datetime.utcnow() - timedelta(days=7)
        active_user_ids = db.session.query(TrainingSession.user_id).filter(TrainingSession.created_at >= cutoff).distinct()
        query = query.filter(~User.id.in_(active_user_ids))

    users = query.all()
    now = datetime.utcnow()
    for user in users:
        db.session.add(
            NotificationLog(
                user_id=user.id,
                notification_type="custom",
                scheduled_at=now,
                sent_at=now,
                opened=False,
                push_subscription_endpoint=None,
            )
        )
    db.session.commit()

    _add_audit(
        "notification.bulk_send",
        details={
            "type": notification_type,
            "segment": segment,
            "user_count": len(users),
            "custom_message": custom_message,
        },
    )
    return jsonify({"status": "sent", "user_count": len(users)})


@admin_bp.get("/settings")
@admin_required
def settings_index():
    admin = g.admin_user
    if admin.role != "super_admin":
        abort(403)

    admin_users = AdminUser.query.order_by(AdminUser.created_at.asc()).all()
    redis_client = _redis_client()

    feature_flags = {
        "snapspeak_enabled": redis_client.get("feature_snapspeak_enabled") == "1",
        "new_registrations_enabled": redis_client.get("feature_new_registrations_enabled") != "0",
        "certificate_generation_enabled": redis_client.get("feature_certificate_enabled") != "0",
        "maintenance_mode": redis_client.get("maintenance_mode") == "1",
    }

    celery_schedule = current_app.config.get("CELERYBEAT_SCHEDULE", {})
    last_run = _last_task_run(redis_client)

    return render_template(
        "admin/settings/index.html",
        title="Settings",
        admin_users=admin_users,
        feature_flags=feature_flags,
        celery_schedule=celery_schedule,
        last_run=last_run,
    )


@admin_bp.post("/settings/add-admin")
@admin_required
def settings_add_admin():
    admin = g.admin_user
    if admin.role != "super_admin":
        abort(403)

    payload = request.get_json(silent=True) or request.form
    email = (payload.get("email") or "").strip().lower()
    full_name = (payload.get("full_name") or "").strip()
    role = (payload.get("role") or "admin").strip()

    if not email or not full_name:
        return jsonify({"error": "email and full_name are required"}), 400
    if role not in {"super_admin", "admin", "support", "analyst"}:
        return jsonify({"error": "invalid role"}), 400

    if AdminUser.query.filter_by(email=email).first() is not None:
        return jsonify({"error": "email already exists"}), 400

    temporary_password = f"Temp@{secrets.token_hex(6)}1"
    new_admin = AdminUser(
        email=email,
        full_name=full_name,
        role=role,
        is_active=True,
        created_by_id=admin.id,
    )
    new_admin.set_password(temporary_password)
    db.session.add(new_admin)
    db.session.commit()

    try:
        message = Message(
            subject="PressureProof Admin Access",
            recipients=[email],
            body=(
                f"Hello {full_name},\n\n"
                f"Your admin account has been created for PressureProof.\n"
                f"Role: {role}\n"
                f"Temporary password: {temporary_password}\n"
                f"Login URL: {url_for('admin.login_get', _external=True)}\n\n"
                "Please change your password immediately after login."
            ),
        )
        mail.send(message)
    except Exception:
        current_app.logger.warning("Unable to send admin welcome email", exc_info=True)

    _add_audit(
        "admin.create",
        target_type="admin_user",
        target_id=new_admin.id,
        details={"email": email, "role": role},
    )

    return jsonify({"status": "created", "admin_id": new_admin.id, "temporary_password": temporary_password})


@admin_bp.post("/settings/feature-flags")
@admin_required
def settings_feature_flags():
    admin = g.admin_user
    if admin.role != "super_admin":
        abort(403)

    payload = request.get_json(silent=True) or request.form
    redis_client = _redis_client()

    mapping = {
        "snapspeak_enabled": "feature_snapspeak_enabled",
        "new_registrations_enabled": "feature_new_registrations_enabled",
        "certificate_generation_enabled": "feature_certificate_enabled",
        "maintenance_mode": "maintenance_mode",
    }

    updated = {}
    for field_name, redis_key in mapping.items():
        if field_name in payload:
            raw = payload.get(field_name)
            truthy = str(raw).lower() in {"1", "true", "yes", "on"}
            redis_client.set(redis_key, "1" if truthy else "0")
            updated[field_name] = truthy

    _add_audit("settings.feature_flags", details={"updated": updated})
    return jsonify({"status": "ok", "updated": updated})
