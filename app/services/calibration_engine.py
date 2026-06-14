from datetime import datetime, timedelta
import random

from app.extensions import db
from app.models import FailureMode, LsrcScore, SessionCalibration


TARGET_TO_INJECTION = {
    "lexical_diversity": "temporal",
    "syntactic_complexity": "topic_pivot",
    "disfluency_rate": "interlocutor",
    "prosodic_confidence": "interlocutor",
    "sentence_completion": "distractor",
    "recovery_speed": "temporal",
}

TARGET_TO_SESSION_TYPE = {
    "lexical_diversity": "vocabulary_pressure",
    "recovery_speed": "vocabulary_pressure",
    "prosodic_confidence": "prosodic_drill",
    "disfluency_rate": "prosodic_drill",
    "sentence_completion": "distractor_challenge",
    "syntactic_complexity": "distractor_challenge",
}

DIMENSION_FIELD_MAP = {
    "lexical_diversity": "lexical_diversity",
    "syntactic_complexity": "syntactic_complexity",
    "prosodic_confidence": "prosodic_confidence",
    "disfluency_rate": "disfluency_rate",
    "sentence_completion": "sentence_completion",
    "recovery_speed": "recovery_speed_score",
}


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _available_injections(session_count):
    if session_count <= 3:
        return ["temporal"]
    if session_count <= 6:
        return ["temporal", "distractor"]
    if session_count <= 11:
        return ["temporal", "distractor", "interlocutor"]
    return ["temporal", "distractor", "interlocutor", "topic_pivot"]


def _resolve_target_dimension(user_id):
    failure_mode = FailureMode.query.filter_by(user_id=user_id).first()
    if failure_mode and failure_mode.mode_code != "insufficient_data" and failure_mode.primary_dimension:
        return failure_mode.primary_dimension
    return "lexical_diversity"


def _resolve_session_count_and_last_session(user_id):
    session_count = 0
    last_session = None
    try:
        from app.models import TrainingSession

        session_count = TrainingSession.query.filter_by(user_id=user_id).count()
        last_session = (
            TrainingSession.query.filter_by(user_id=user_id)
            .order_by(TrainingSession.completed_at.desc(), TrainingSession.created_at.desc())
            .first()
        )
    except Exception:
        session_count = 0
        last_session = None
    return session_count, last_session


def _latest_dimension_values(recent_scores, target_dimension):
    field_name = DIMENSION_FIELD_MAP.get(target_dimension, "lexical_diversity")
    values = []
    for score in recent_scores:
        value = _safe_float(getattr(score, field_name, None))
        if value is not None:
            values.append(value)
    return values


def compute_next_session(user_id: int) -> SessionCalibration:
    fourteen_days_ago = datetime.utcnow() - timedelta(days=14)
    recent_scores = (
        LsrcScore.query.filter(
            LsrcScore.user_id == user_id,
            LsrcScore.scored_at >= fourteen_days_ago,
        )
        .order_by(LsrcScore.scored_at.asc())
        .all()
    )

    session_count, last_session = _resolve_session_count_and_last_session(user_id)
    available_injections = _available_injections(session_count)
    target_dimension = _resolve_target_dimension(user_id)

    preferred_injection = TARGET_TO_INJECTION.get(target_dimension, "temporal")
    if preferred_injection not in available_injections:
        preferred_injection = available_injections[-1]

    session_type = TARGET_TO_SESSION_TYPE.get(target_dimension, "vocabulary_pressure")
    if session_count == 0:
        session_type = "baseline_measurement"

    existing_calibration = SessionCalibration.query.filter_by(user_id=user_id).first()
    base_threshold = _safe_float(
        existing_calibration.current_stress_threshold if existing_calibration else 0.3,
        default=0.3,
    )

    last_session_early_exit = False
    if last_session is not None:
        last_session_early_exit = bool(
            getattr(last_session, "early_exit", False)
            or getattr(last_session, "status", "") in {"early_exit", "abandoned", "incomplete"}
        )

    if last_session_early_exit:
        session_type = "recovery_focus"

    intensity = base_threshold
    if session_type == "baseline_measurement":
        preferred_injection = "none"
        intensity = 0.3
    elif last_session_early_exit:
        intensity = max(0.2, base_threshold - 0.15)
    else:
        target_values = _latest_dimension_values(recent_scores, target_dimension)
        if len(target_values) >= 6:
            latest_value = target_values[-1]
            reference_value = target_values[-6]
            if reference_value > 0:
                change_pct = ((latest_value - reference_value) / reference_value) * 100.0
                if change_pct > 10.0:
                    intensity = base_threshold + 0.1
                elif change_pct < 5.0:
                    intensity = base_threshold

    intensity = min(1.0, round(float(intensity), 2))
    injection_timing_seconds = random.randint(8, 12)

    calibration = existing_calibration
    if calibration is None:
        calibration = SessionCalibration(user_id=user_id)
        db.session.add(calibration)

    calibration.computed_at = datetime.utcnow()
    calibration.next_session_type = session_type
    calibration.next_injection_type = preferred_injection
    calibration.next_injection_intensity = intensity
    calibration.next_injection_timing_seconds = injection_timing_seconds
    calibration.target_dimension = target_dimension
    calibration.algorithm_version = "1.0"
    calibration.last_session_early_exit = last_session_early_exit
    calibration.current_stress_threshold = intensity

    db.session.commit()
    return calibration


SESSION_PROMPT_BANK = {
    "IT Services": {
        "vocabulary_pressure": [
            "Explain technical debt to a product manager and use specific business language instead of engineering jargon.",
            "Describe a production incident to a client and structure your answer as timeline, impact, mitigation, and prevention.",
            "Defend an architectural decision while your stakeholder pushes back on cost and delivery risk.",
            "Describe what went wrong in a deployment and avoid repeating the same adjectives.",
            "Explain API rate limiting to a non technical stakeholder with simple but precise language.",
            "Discuss a colleague's underperformance with your manager using diplomatic but direct wording.",
            "Present a cost benefit analysis for migrating from monolith to microservices in under two minutes.",
            "Handle a scope creep conversation with a client and clearly separate what is included versus deferred.",
        ],
        "distractor_challenge": [
            "Describe your sprint retrospective findings while handling rapid follow up questions every ten seconds.",
            "Answer an unexpected technical question in a live demo without pausing longer than two seconds.",
            "Explain a security vulnerability to leadership without causing panic while balancing risk and reassurance.",
            "Walk through your onboarding process for a new team member while switching between technical and non technical language.",
            "Negotiate a deadline extension with a project manager who insists the original date must stay.",
            "Explain why a competitor's solution is weaker than yours while staying factual and professional.",
            "Respond to a client complaint about slow response times while acknowledging responsibility and recovery steps.",
            "Handle a client asking for a refund after a failed release and propose a corrective path with clear milestones.",
        ],
        "prosodic_drill": [
            "Present quarterly engineering metrics to a VP with calm pacing and confidence in every sentence ending.",
            "Explain your biggest professional failure and what you changed after it without sounding defensive.",
            "Describe a high stakes architecture review using deliberate pauses for each major decision point.",
            "Rehearse a client escalation update with consistent tone and lower filler frequency.",
            "Deliver a two minute security incident summary with steady volume and clear emphasis shifts.",
            "Explain microservices architecture to a junior developer with stable rhythm and no rush.",
            "Present a technology migration recommendation to finance and engineering in one coherent voice.",
        ],
        "recovery_focus": [
            "Explain a failed deployment, pause deliberately, then recover with a concise restart phrase.",
            "Respond to pushback on your architecture choice and recover cleanly if you lose your wording.",
            "Handle a refund request conversation and practice restarting after each interruption.",
            "Describe a difficult client handoff and use bridge phrases whenever you hesitate.",
            "Present root cause analysis and perform one structured reset after a forced topic change.",
            "Discuss cross team conflict and recover fluently after a deliberate lexical block.",
        ],
        "baseline_measurement": [
            "Introduce your role, current project, and the speaking situations that create the most pressure.",
            "Describe a recent technical achievement and the communication challenge behind it.",
            "Explain how you currently prepare for high pressure client conversations.",
            "Share one meeting where your ideas were strong but your delivery felt weaker than expected.",
            "Describe your communication style when deadlines become aggressive.",
            "Talk about the first English speaking scenario you want to improve over the next month.",
        ],
    },
    "BPO or Call Centre": {
        "vocabulary_pressure": [
            "Handle an irate customer demanding a supervisor and vary your reassurance wording in every sentence.",
            "Explain a billing error to a confused elderly customer with plain and respectful language.",
            "De escalate a caller threatening to cancel without using repetitive apology phrases.",
            "Explain a policy the caller strongly disagrees with while staying calm and precise.",
            "Respond to a caller who comments on your accent and keep the conversation professional.",
            "Handle a call where the customer starts crying and communicate empathy with clear next steps.",
            "Describe your key performance metrics to a new manager using specific measurable language.",
            "Explain why you escalated a difficult call and defend the decision clearly.",
        ],
        "distractor_challenge": [
            "Handle a fast talking native English speaker who refuses to slow down and still keep control of the call.",
            "Respond to a caller who accuses you of lying while preserving compliance wording.",
            "Present a coaching session to a junior agent while handling interruptions from a mock customer.",
            "Describe your call center quality assurance process while switching between policy and empathy language.",
            "Handle a caller who is clearly inebriated while preserving safety protocol language.",
            "Explain why a refund cannot be processed and offer alternative actions under pressure.",
            "Close a difficult complaint while balancing concise responses with compliance requirements.",
            "Explain account verification to a frustrated caller who keeps changing identity details.",
        ],
        "prosodic_drill": [
            "Open a high tension support call with steady tone and controlled pace.",
            "Deliver empathy statements with consistent pitch during a difficult complaint.",
            "Rehearse escalation instructions with strong sentence endings and low filler usage.",
            "Practice call closure language that sounds calm, confident, and final.",
            "Handle a repeat caller and maintain composure across the full response.",
            "Explain compliance constraints to a hostile customer while preserving vocal stability.",
            "Present a quality review summary to your supervisor with clear emphasis and rhythm.",
        ],
        "recovery_focus": [
            "Start a difficult call response, pause after a mistake, and recover with one concise reset phrase.",
            "Respond to a cancellation threat and recover fluently after a deliberate interruption.",
            "Explain delayed resolution steps and rebuild flow quickly when you lose a key term.",
            "Rephrase a policy statement smoothly after a false start.",
            "Deliver a complaint summary and recover confidently after an unexpected question.",
            "Practice bridge language that restores control after short silent gaps.",
        ],
        "baseline_measurement": [
            "Describe your call handling role and the hardest conversations you manage daily.",
            "Explain how you calm a frustrated customer in your own style.",
            "Share one call where pressure affected your speaking confidence.",
            "Describe your strongest communication habit during customer interactions.",
            "Talk about a speaking challenge that appears repeatedly in live calls.",
            "Explain what better spoken English would change in your role this quarter.",
        ],
    },
    "Healthcare": {
        "vocabulary_pressure": [
            "Explain a diagnosis to a worried patient using clear language and no repeated reassurance phrases.",
            "Present a patient case in an MDT meeting with accurate clinical sequencing.",
            "Deliver handover notes for an incoming shift with concise prioritization.",
            "Explain a medication change to a resistant patient in calm, plain language.",
            "Respond to a family member demanding information while maintaining confidentiality boundaries.",
            "Describe an adverse event in a clinical review using exact and accountable wording.",
            "Explain a treatment plan to a patient with low health literacy without losing precision.",
            "Discuss end of life care options sensitively while keeping the message understandable.",
        ],
        "distractor_challenge": [
            "Respond to a complaint about wait times while multiple follow up questions interrupt your answer.",
            "Present audit findings to a ward manager while switching between data and action points.",
            "Explain a procedural complication to a patient while handling emotional interruptions.",
            "Discuss a referral with a specialist while clarifying missing information quickly.",
            "Handle an aggressive patient scenario and preserve calm communication structure.",
            "Explain why a test result is delayed and keep reassurance factual.",
            "Deliver triage priorities while reacting to sudden scenario changes.",
            "Describe medication safety checks while a colleague asks rapid clarifications.",
        ],
        "prosodic_drill": [
            "Practice calm voice delivery for an emergency room family briefing.",
            "Rehearse patient reassurance language with measured pace and stable tone.",
            "Deliver a clinical handover with emphasis on risk and next actions.",
            "Explain a treatment plan while keeping vocal confidence consistent.",
            "Present a shift summary using deliberate pauses at key decisions.",
            "Practice informed consent language with clear articulation and low filler use.",
            "Deliver difficult news simulation with controlled breathing and steady cadence.",
        ],
        "recovery_focus": [
            "Start a handover, restart after one misstatement, and recover without apology loops.",
            "Explain a delayed test result and recover smoothly when interrupted mid sentence.",
            "Deliver urgent instructions and use a bridge phrase after intentional pauses.",
            "Respond to a difficult family question and recover quickly from lexical blocks.",
            "Practice short clinical reset phrases that restore clarity after breakdowns.",
            "Describe a complex case and rebuild flow immediately after a verbal stumble.",
        ],
        "baseline_measurement": [
            "Describe your role in patient care and the speaking situations that challenge you most.",
            "Explain how you currently communicate under clinical pressure.",
            "Share one moment where speaking clarity affected patient confidence.",
            "Describe your strongest communication behavior in difficult consultations.",
            "Talk about what happens to your speaking pace when stress rises.",
            "Explain one communication goal you want to improve this month.",
        ],
    },
    "Immigration Applicant": {
        "vocabulary_pressure": [
            "Explain your professional qualifications to an immigration officer with precise language.",
            "Describe your reasons for choosing your destination country with concrete evidence.",
            "Answer why you left your previous country while staying clear and consistent.",
            "Describe your financial self sufficiency plan with specific details.",
            "Explain a gap in your employment history without sounding defensive.",
            "Discuss your English learning journey and how it supports integration.",
            "Describe your integration and community involvement plan in practical steps.",
            "Answer whether you already have family in the country and how that affects your plan.",
        ],
        "distractor_challenge": [
            "Explain a legal issue scenario from your past and then answer skeptical follow up questions.",
            "Describe professional achievements and why they match your visa category while interrupted.",
            "Respond to skeptical questions about whether your skills are truly in demand.",
            "Explain your long term career plan while the interviewer changes topic abruptly.",
            "Handle fast follow up questions about your financial documents without losing structure.",
            "Describe relocation logistics while adapting to surprise policy questions.",
            "Answer credibility questions about job offers and timelines under pressure.",
            "Present your profile summary while interruptions force concise recovery.",
        ],
        "prosodic_drill": [
            "Practice interview introductions with confident tone and controlled pacing.",
            "Deliver your motivation statement with clear intonation and low filler usage.",
            "Rehearse your work history summary while maintaining vocal stability.",
            "Practice high stakes answers with deliberate pauses and firm sentence endings.",
            "Explain transition goals with composed voice under simulated stress.",
            "Deliver eligibility details with clarity and consistent energy.",
            "Present your settlement intent statement with calm authority.",
        ],
        "recovery_focus": [
            "Answer a difficult interview question, pause, then recover with a precise restatement.",
            "Describe a career gap and rebuild flow quickly after one lexical block.",
            "Explain documentation delays and recover smoothly after interruption.",
            "Handle a surprise follow up and use a bridge phrase to restart clearly.",
            "Practice resetting after a false start without reducing confidence in tone.",
            "Respond to pressure questions and restore fluency after short pauses.",
        ],
        "baseline_measurement": [
            "Introduce your background and your reason for immigration in clear language.",
            "Describe your current profession and what you aim to do after relocation.",
            "Share one interview situation where stress changed your speech.",
            "Explain how you currently prepare for spoken English interviews.",
            "Describe what part of spontaneous English feels hardest for you.",
            "Talk about your biggest communication goal before your next interview.",
        ],
    },
    "Other": {
        "vocabulary_pressure": [
            "Describe a high stakes presentation and explain the hardest audience question you handled.",
            "Explain a performance review conversation where you had to discuss difficult feedback.",
            "Present a salary negotiation argument with clear value evidence and concise language.",
            "Describe a resignation conversation with your manager while keeping tone professional.",
            "Introduce yourself to a new client and explain your service value without vague wording.",
            "Defend a difficult work decision when a senior stakeholder disagrees with you.",
            "Explain a project delay to leadership and propose a revised recovery plan.",
            "Describe a conflict mediation conversation between two team members.",
        ],
        "distractor_challenge": [
            "Present a weekly update while frequent follow up questions interrupt your flow.",
            "Describe your priorities while switching tone for peer, manager, and client audiences.",
            "Handle an unexpected objection in the middle of your proposal.",
            "Discuss a conflict scenario while recovering from forced topic pivots.",
            "Deliver a short pitch while managing repeated interruptions.",
            "Respond to a skeptical salary negotiation follow up without losing sentence completion.",
            "Explain onboarding steps for a new client while handling fast clarifications.",
            "Answer difficult feedback questions from your team after a failed initiative.",
        ],
        "prosodic_drill": [
            "Deliver a one minute professional introduction with stable confidence in tone.",
            "Practice a difficult response with controlled pace and clear articulation.",
            "Explain a work process while maintaining vocal energy from start to end.",
            "Rehearse a feedback conversation with calm rhythm and deliberate pauses.",
            "Present an update where sentence endings sound firm and complete.",
            "Practice speaking with low filler frequency and steady vocal control.",
            "Close a negotiation statement with calm authority and clear commitment language.",
        ],
        "recovery_focus": [
            "Start a challenging explanation, then recover cleanly after one intentional break.",
            "Respond to a pressure question and use a bridge phrase when you hesitate.",
            "Rephrase a sentence smoothly after a false start in the first clause.",
            "Describe a stressful event and regain flow quickly after interruption.",
            "Practice concise reset language that restores confidence after a pause.",
            "Handle a difficult scenario and recover immediately from word search delays.",
        ],
        "baseline_measurement": [
            "Describe your work context and the speaking situations that matter most.",
            "Explain one communication strength you rely on in professional settings.",
            "Share a recent moment when pressure affected your spoken English.",
            "Describe how you currently prepare for important conversations.",
            "Talk about the part of speaking under stress you want to improve first.",
            "Explain what progress would look like for your confidence this month.",
        ],
    },
}


def get_session_prompt(session_type: str, professional_context: str) -> str:
    context_key = professional_context if professional_context in SESSION_PROMPT_BANK else "Other"
    session_key = session_type if session_type in SESSION_PROMPT_BANK[context_key] else "baseline_measurement"
    return random.choice(SESSION_PROMPT_BANK[context_key][session_key])


def calibrate_pressure_profile(user_id, baseline_sessions):
    return compute_next_session(user_id)
