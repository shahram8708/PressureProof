import json
from datetime import date, datetime, time, timedelta

from app.extensions import db
from app.models import (
    AdminAuditLog,
    AdminUser,
    Certificate,
    CohortAggregate,
    DrillCompletion,
    Drill,
    InjectionEvent,
    LsrcScore,
    NotificationLog,
    PgiRecord,
    SessionCalibration,
    SnapSpeakRecord,
    TrainingSession,
    User,
)


DRILL_SEED_DATA = [
    {
        "category": "Filler Bridging",
        "title": "The Professional Pause",
        "description": "You learn to replace panic fillers with intentional pauses that buy cognitive time. The drill trains you to hold eye contact and maintain composure while your next sentence forms. Over repetitions, your pauses start sounding deliberate rather than uncertain.",
        "difficulty_level": 1,
        "estimated_seconds": 90,
        "filler_phrases": [
            "Let me frame that clearly.",
            "Give me a second to structure this.",
            "Here is the direct answer.",
        ],
    },
    {
        "category": "Filler Bridging",
        "title": "The Question Echo",
        "description": "You repeat the core part of the question in polished business English before answering. This creates a stabilizing bridge and prevents rushed grammar errors. It also signals active listening to the other speaker.",
        "difficulty_level": 2,
        "estimated_seconds": 90,
        "filler_phrases": [
            "You are asking about deployment risk.",
            "The key concern is release stability.",
            "Let me address that in two parts.",
        ],
    },
    {
        "category": "Filler Bridging",
        "title": "The Context Bridge",
        "description": "You anchor your response with one context sentence before moving into detail. This prevents abrupt starts and keeps your thought process linear under pressure. The result is clearer, more coherent speech during high stakes moments.",
        "difficulty_level": 3,
        "estimated_seconds": 90,
        "filler_phrases": [
            "From the current system context, the main issue is scale.",
            "In this scenario, reliability comes first.",
            "Before details, here is the decision lens.",
        ],
    },
    {
        "category": "Reformulation",
        "title": "The Clean Reset",
        "description": "When you start a sentence poorly, you practice restarting without apology loops. The drill builds a smooth reset phrase so you keep authority while correcting yourself. This reduces spirals caused by self monitoring and embarrassment.",
        "difficulty_level": 2,
        "estimated_seconds": 90,
        "filler_phrases": [
            "Let me rephrase that precisely.",
            "A clearer way to put it is this.",
            "I will restate that in practical terms.",
        ],
    },
    {
        "category": "Reformulation",
        "title": "The Precision Upgrade",
        "description": "You convert vague words into exact language while speaking in real time. The drill trains rapid lexical substitution so pressure no longer forces low precision vocabulary. Over time, your professional credibility increases in meetings and interviews.",
        "difficulty_level": 3,
        "estimated_seconds": 90,
        "filler_phrases": [
            "More specifically, the constraint is response latency.",
            "To be precise, we need staged rollout controls.",
            "The accurate term here is regression risk.",
        ],
    },
    {
        "category": "Semantic Substitution",
        "title": "The Paraphrase Recovery",
        "description": "When a target word disappears, you practice recovering meaning through paraphrase. The drill keeps momentum so silence gaps do not break your flow. This directly improves communication under surprise questioning.",
        "difficulty_level": 2,
        "estimated_seconds": 90,
        "filler_phrases": [
            "In other words, it performs the same function.",
            "Put simply, it solves the same problem differently.",
            "Another way to explain it is this.",
        ],
    },
    {
        "category": "Semantic Substitution",
        "title": "The Synonym Pivot",
        "description": "You train fast synonym pivots for common professional vocabulary failures. The objective is not perfect word recall but uninterrupted meaning delivery. This reduces freezing when one missing word blocks an entire sentence.",
        "difficulty_level": 1,
        "estimated_seconds": 90,
        "filler_phrases": [
            "A related term is scalability.",
            "You can think of it as consistency.",
            "The closest practical word is reliability.",
        ],
    },
    {
        "category": "Semantic Substitution",
        "title": "The Analogy Bridge",
        "description": "You use short analogies to communicate concepts when exact terminology is unavailable. The drill teaches concise analogy use without losing professional tone. This keeps explanations understandable under cognitive load.",
        "difficulty_level": 4,
        "estimated_seconds": 90,
        "filler_phrases": [
            "It works like a traffic signal for requests.",
            "Think of it as a safety net before release.",
            "It is similar to a backup decision path.",
        ],
    },
]


def seed_database():
    now = datetime.utcnow()
    created_demo_user = False

    demo_user = User.query.filter_by(email="demo@pressureproof.com").first()
    if demo_user is None:
        demo_user = User(
            email="demo@pressureproof.com",
            display_name="Demo User",
            country="India",
            l1_language="Hindi",
            professional_context="IT Services",
            email_verified=True,
            subscription_tier="professional",
            trial_ends_at=now + timedelta(days=14),
            onboarding_complete=True,
            preferred_snapspeak_start=time(9, 0),
            preferred_snapspeak_end=time(18, 0),
            snapspeak_opted_in=True,
        )
        demo_user.set_password("DemoUser123!")
        db.session.add(demo_user)
        db.session.flush()
        created_demo_user = True
        print("[SEED] Demo user created: demo@pressureproof.com / DemoUser123!")

    if created_demo_user:
        db.session.flush()

    existing_calibration = SessionCalibration.query.filter_by(user_id=demo_user.id).first()
    if existing_calibration is None:
        db.session.add(
            SessionCalibration(
                user_id=demo_user.id,
                next_session_type="vocabulary_pressure",
                next_injection_type="temporal",
                next_injection_intensity=0.30,
                next_injection_timing_seconds=10,
                target_dimension="lexical_diversity",
                algorithm_version="1.0",
                current_stress_threshold=0.30,
                last_session_early_exit=False,
            )
        )
        print("[SEED] Added default session calibration for demo user.")

    demo_session = (
        TrainingSession.query.filter_by(user_id=demo_user.id, status="completed")
        .order_by(TrainingSession.created_at.asc())
        .first()
    )

    if demo_session is None:
        demo_session = TrainingSession(
            user_id=demo_user.id,
            session_type="vocabulary_pressure",
            prompt_text=(
                "Describe the most challenging project you have worked on in the last year "
                "and explain your approach to the main technical obstacle."
            ),
            stress_injection_type="temporal",
            stress_injection_intensity=0.30,
            injection_timestamp_seconds=10,
            injection_actually_fired=True,
            early_exit=False,
            early_exit_reason=None,
            session_number=1,
            status="completed",
            created_at=now - timedelta(hours=1, minutes=8),
            completed_at=now - timedelta(hours=1),
            transcript=(
                "This is a demo session transcript for testing purposes. "
                "The actual transcript would contain the user's speech."
            ),
        )
        db.session.add(demo_session)
        db.session.flush()
        print("[SEED] Added completed demo training session.")

    existing_injection_event = (
        InjectionEvent.query.filter_by(session_id=demo_session.id, injection_type="temporal")
        .order_by(InjectionEvent.created_at.asc())
        .first()
    )
    if existing_injection_event is None:
        db.session.add(
            InjectionEvent(
                session_id=demo_session.id,
                injection_type="temporal",
                fired_at_seconds=10.0,
                pressure_meter_value=0.30,
                created_at=now - timedelta(hours=1),
            )
        )
        print("[SEED] Added demo injection event for training session.")

    current_week_start = date.today() - timedelta(days=date.today().weekday())
    weekly_values = [
        (4, 38.0),
        (3, 36.0),
        (2, 34.0),
        (1, 32.0),
        (0, 34.0),
    ]

    for week_offset, pgi_value in weekly_values:
        week_start = current_week_start - timedelta(days=week_offset * 7)
        existing_record = PgiRecord.query.filter_by(
            user_id=demo_user.id,
            week_start_date=week_start,
        ).first()
        if existing_record is not None:
            continue

        if week_offset == 0:
            prepared_composite = 72.0
            spontaneous_composite = 55.0
            sessions_count = 1
            snapspeak_count = 2
        else:
            prepared_composite = round(68.0 + (4 - week_offset) * 1.2, 2)
            spontaneous_composite = round(
                prepared_composite * (1.0 - (pgi_value / 100.0)),
                2,
            )
            sessions_count = 1 + (4 - week_offset)
            snapspeak_count = 1 + max(0, 3 - week_offset)

        db.session.add(
            PgiRecord(
                user_id=demo_user.id,
                week_start_date=week_start,
                pgi_score=pgi_value,
                prepared_composite=prepared_composite,
                spontaneous_composite=spontaneous_composite,
                sessions_count=sessions_count,
                snapspeak_count=snapspeak_count,
                topic_matched=False,
                calculated_at=now - timedelta(days=week_offset * 7),
            )
        )

    print("[SEED] PGI trend seeded for demo user.")

    if Drill.query.count() == 0:
        for entry in DRILL_SEED_DATA:
            db.session.add(
                Drill(
                    category=entry["category"],
                    title=entry["title"],
                    description=entry["description"],
                    difficulty_level=entry["difficulty_level"],
                    estimated_seconds=entry["estimated_seconds"],
                    filler_phrases=json.dumps(entry["filler_phrases"]),
                )
            )
        print(f"[SEED] Seeded {len(DRILL_SEED_DATA)} drill definitions.")

    if CohortAggregate.query.count() == 0:
        cohort_keys = [
            "IT Services|Hindi|B2",
            "BPO or Call Centre|Hindi|B1",
            "Healthcare|Hindi|B2",
            "Immigration Applicant|Other|B2",
            "Other|Other|B1",
        ]
        dimensions = [
            "lexical_diversity",
            "syntactic_complexity",
            "prosodic_confidence",
            "disfluency_rate",
            "sentence_completion",
            "recovery_speed",
            "pgi",
        ]

        insert_count = 0
        for cohort_key in cohort_keys:
            for dimension in dimensions:
                db.session.add(
                    CohortAggregate(
                        cohort_key=cohort_key,
                        dimension=dimension,
                        percentile_10=None,
                        percentile_25=None,
                        percentile_50=None,
                        percentile_75=None,
                        percentile_90=None,
                        user_count=0,
                    )
                )
                insert_count += 1

        print(f"[SEED] Inserted {insert_count} cohort aggregate baseline rows.")

    existing_snapspeaks = SnapSpeakRecord.query.filter_by(user_id=demo_user.id).count()
    if existing_snapspeaks == 0:
        snapspeak_seed_rows = [
            {
                "captured_at": now - timedelta(days=12, hours=2),
                "prompt_text": "Describe what your team shipped last week and why it mattered.",
                "prompt_type": "contextual",
                "context_tag": "work",
                "analysis_line_1": "Vocabulary range: 56 - 1.2 below your recent average.",
                "analysis_line_2": "Pause frequency: some hesitation present - within normal range. This is 0.8 points below your recent average.",
                "analysis_line_3": "Recovery speed: 4.8s average - baseline comparison: 0.6s slower.",
                "is_notable": False,
                "notable_annotation": None,
                "scores": {
                    "lexical_diversity": 56,
                    "syntactic_complexity": 58,
                    "prosodic_confidence": 54,
                    "disfluency_rate": 57,
                    "sentence_completion": 60,
                    "recovery_speed_seconds": 4.8,
                    "recovery_speed_score": 55,
                },
            },
            {
                "captured_at": now - timedelta(days=9, hours=5),
                "prompt_text": "What is blocking you right now at work?",
                "prompt_type": "contextual",
                "context_tag": "casual",
                "analysis_line_1": "Vocabulary range: 61 - 2.1 above your recent average.",
                "analysis_line_2": "Pause frequency: some hesitation present - within normal range. This is 1.4 points above your recent average.",
                "analysis_line_3": "Recovery speed: 4.4s - close to your best of 4.1s.",
                "is_notable": False,
                "notable_annotation": None,
                "scores": {
                    "lexical_diversity": 61,
                    "syntactic_complexity": 60,
                    "prosodic_confidence": 59,
                    "disfluency_rate": 60,
                    "sentence_completion": 62,
                    "recovery_speed_seconds": 4.4,
                    "recovery_speed_score": 58,
                },
            },
            {
                "captured_at": now - timedelta(days=6, hours=1),
                "prompt_text": "Describe the last bug you fixed and why it was tricky.",
                "prompt_type": "contextual",
                "context_tag": "work",
                "analysis_line_1": "Vocabulary range: 63 - 3.2 above your recent average.",
                "analysis_line_2": "Pause frequency: pause frequency is low - good fluency under pressure. This is 3.0 points above your recent average.",
                "analysis_line_3": "Recovery speed: 4.1s - your personal best.",
                "is_notable": True,
                "notable_annotation": "Best recovery speed to date",
                "scores": {
                    "lexical_diversity": 63,
                    "syntactic_complexity": 64,
                    "prosodic_confidence": 61,
                    "disfluency_rate": 65,
                    "sentence_completion": 64,
                    "recovery_speed_seconds": 4.1,
                    "recovery_speed_score": 62,
                },
            },
            {
                "captured_at": now - timedelta(days=3, hours=4),
                "prompt_text": "What conversation are you preparing for in the next few days?",
                "prompt_type": "random",
                "context_tag": "preparation",
                "analysis_line_1": "Vocabulary range: 68 - 4.7 above your recent average.",
                "analysis_line_2": "Pause frequency: pause frequency is low - good fluency under pressure. This is 4.2 points above your recent average.",
                "analysis_line_3": "Recovery speed: 3.9s - your personal best.",
                "is_notable": True,
                "notable_annotation": "Best lexical diversity in a SnapSpeak to date",
                "scores": {
                    "lexical_diversity": 68,
                    "syntactic_complexity": 66,
                    "prosodic_confidence": 65,
                    "disfluency_rate": 66,
                    "sentence_completion": 67,
                    "recovery_speed_seconds": 3.9,
                    "recovery_speed_score": 66,
                },
            },
            {
                "captured_at": now - timedelta(days=1, hours=2),
                "prompt_text": "Describe a meeting you had today or yesterday.",
                "prompt_type": "contextual",
                "context_tag": "work",
                "analysis_line_1": "Vocabulary range: 62 - 1.3 above your recent average.",
                "analysis_line_2": "Pause frequency: some hesitation present - within normal range. This is 0.9 points above your recent average.",
                "analysis_line_3": "Recovery speed: 4.2s - close to your best of 3.9s.",
                "is_notable": False,
                "notable_annotation": None,
                "scores": {
                    "lexical_diversity": 62,
                    "syntactic_complexity": 63,
                    "prosodic_confidence": 60,
                    "disfluency_rate": 61,
                    "sentence_completion": 63,
                    "recovery_speed_seconds": 4.2,
                    "recovery_speed_score": 60,
                },
            },
        ]

        for index, row in enumerate(snapspeak_seed_rows, start=1):
            record = SnapSpeakRecord(
                user_id=demo_user.id,
                captured_at=row["captured_at"],
                prompt_text=row["prompt_text"],
                prompt_type=row["prompt_type"],
                context_tag=row["context_tag"],
                audio_path=f"uploads/audio/{demo_user.id}/snapspeak/demo_{index}.webm",
                transcript=(
                    "This is a seeded SnapSpeak transcript for demo visualization. "
                    "It represents spontaneous speech captured in a 90-second challenge."
                ),
                duration_seconds=90,
                status="completed",
                topic_vector=json.dumps({"demo": 0.82, "speech": 0.58, "work": 0.41}),
                analysis_line_1=row["analysis_line_1"],
                analysis_line_2=row["analysis_line_2"],
                analysis_line_3=row["analysis_line_3"],
                is_notable=row["is_notable"],
                notable_annotation=row["notable_annotation"],
            )
            db.session.add(record)
            db.session.flush()

            score = row["scores"]
            db.session.add(
                LsrcScore(
                    user_id=demo_user.id,
                    source_type="snapspeak",
                    source_id=record.id,
                    scored_at=row["captured_at"] + timedelta(minutes=1),
                    condition="spontaneous",
                    lexical_diversity=score["lexical_diversity"],
                    syntactic_complexity=score["syntactic_complexity"],
                    prosodic_confidence=score["prosodic_confidence"],
                    disfluency_rate=score["disfluency_rate"],
                    sentence_completion=score["sentence_completion"],
                    recovery_speed_seconds=score["recovery_speed_seconds"],
                    recovery_speed_score=score["recovery_speed_score"],
                )
            )

        print("[SEED] Seeded 5 demo SnapSpeak records with LSRC scores.")

    if DrillCompletion.query.filter_by(user_id=demo_user.id).count() == 0:
        completion_rows = [
            (1, 4.2, "filler_bridging", now - timedelta(days=2, hours=3)),
            (4, 3.8, "reformulation", now - timedelta(days=1, hours=4)),
        ]
        for drill_id, recovery_time, pathway, completed_at in completion_rows:
            drill_exists = Drill.query.get(drill_id)
            if drill_exists is None:
                continue
            db.session.add(
                DrillCompletion(
                    user_id=demo_user.id,
                    drill_id=drill_id,
                    completed_at=completed_at,
                    recovery_time_seconds=recovery_time,
                    pathway_used=pathway,
                    transcript_excerpt="Demo drill completion transcript excerpt.",
                    audio_path=f"uploads/audio/{demo_user.id}/drill/demo_drill_{drill_id}.webm",
                    session_id=demo_session.id,
                )
            )
        print("[SEED] Seeded 2 demo drill completion records.")

    existing_log = NotificationLog.query.filter_by(
        user_id=demo_user.id,
        notification_type="snapspeak",
    ).first()
    if existing_log is None:
        two_hours_ago = now - timedelta(hours=2)
        db.session.add(
            NotificationLog(
                user_id=demo_user.id,
                notification_type="snapspeak",
                scheduled_at=two_hours_ago,
                sent_at=two_hours_ago,
                opened=False,
                push_subscription_endpoint=None,
            )
        )
        print("[SEED] Added demo SnapSpeak notification log.")

    print("[SEED] Push subscriptions are created when users opt in via the browser.")

    first_demo_session = (
        TrainingSession.query.filter_by(user_id=demo_user.id, status="completed")
        .order_by(TrainingSession.created_at.asc())
        .first()
    )
    demo_session_count = TrainingSession.query.filter_by(user_id=demo_user.id, status="completed").count()
    demo_months_active = (
        (datetime.utcnow().date() - first_demo_session.created_at.date()).days // 30
        if first_demo_session is not None
        else 0
    )

    if demo_months_active >= 6 and demo_session_count >= 20:
        if Certificate.query.filter_by(user_id=demo_user.id).first() is None:
            db.session.add(Certificate(user_id=demo_user.id, is_public=True))
            print("[SEED] Eligible demo user certificate scaffold created.")

    if AdminUser.query.count() == 0:
        super_admin = AdminUser(
            email="admin@pressureproof.com",
            full_name="Platform Administrator",
            role="super_admin",
            is_active=True,
        )
        super_admin.set_password("Admin@PressureProof2026!")
        db.session.add(super_admin)
        db.session.flush()
        print("[SEED] Super admin created: admin@pressureproof.com / Admin@PressureProof2026!")

        analyst_admin = AdminUser(
            email="analyst@pressureproof.com",
            full_name="Data Analyst",
            role="analyst",
            is_active=True,
            created_by_id=super_admin.id,
        )
        analyst_admin.set_password("Analyst@PressureProof2026!")
        db.session.add(analyst_admin)
        db.session.flush()
        print("[SEED] Analyst admin created: analyst@pressureproof.com / Analyst@PressureProof2026!")

        support_admin = AdminUser(
            email="support@pressureproof.com",
            full_name="Support Agent",
            role="support",
            is_active=True,
            created_by_id=super_admin.id,
        )
        support_admin.set_password("Support@PressureProof2026!")
        db.session.add(support_admin)
        db.session.flush()
        print("[SEED] Support admin created: support@pressureproof.com / Support@PressureProof2026!")

        db.session.add(
            AdminAuditLog(
                admin_id=super_admin.id,
                action="admin.seed_created",
                target_type="admin_user",
                target_id=super_admin.id,
                details=json.dumps({"email": super_admin.email, "role": super_admin.role}),
            )
        )
        db.session.add(
            AdminAuditLog(
                admin_id=super_admin.id,
                action="admin.seed_created",
                target_type="admin_user",
                target_id=analyst_admin.id,
                details=json.dumps({"email": analyst_admin.email, "role": analyst_admin.role}),
            )
        )
        db.session.add(
            AdminAuditLog(
                admin_id=super_admin.id,
                action="admin.seed_created",
                target_type="admin_user",
                target_id=support_admin.id,
                details=json.dumps({"email": support_admin.email, "role": support_admin.role}),
            )
        )

        print("=== ADMIN CREDENTIALS ===")
        print("Email                         Role         Password")
        print("admin@pressureproof.com       super_admin  Admin@PressureProof2026!")
        print("analyst@pressureproof.com     analyst      Analyst@PressureProof2026!")
        print("support@pressureproof.com     support      Support@PressureProof2026!")
        print("[SEED] Change all admin passwords immediately in production.")

    db.session.commit()
    print("[SEED] Database seeding complete.")
