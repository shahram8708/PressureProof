import os
from datetime import datetime, timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import FailureMode, SessionCalibration, TrainingSession, User
from app.services.calibration_engine import calibrate_pressure_profile, compute_next_session, get_session_prompt


@pytest.fixture
def app():
    os.environ["SECRET_KEY"] = "test-secret-key"
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"

    application = create_app("testing")
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    with application.app_context():
        db.drop_all()
        db.create_all()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


def _create_user(email):
    user = User(email=email, email_verified=True, trial_ends_at=datetime.utcnow() + timedelta(days=14))
    user.set_password("SecurePass9")
    db.session.add(user)
    db.session.commit()
    return user


def _add_session(user_id, number, early_exit=False, completed_at=None):
    session = TrainingSession(
        user_id=user_id,
        session_type="vocabulary_pressure",
        prompt_text="Explain your current project in detail.",
        stress_injection_type="temporal",
        stress_injection_intensity=0.4,
        injection_timestamp_seconds=10,
        injection_actually_fired=True,
        early_exit=early_exit,
        session_number=number,
        status="completed",
        created_at=completed_at or datetime.utcnow(),
        completed_at=completed_at or datetime.utcnow(),
    )
    db.session.add(session)
    db.session.commit()
    return session


def test_compute_next_session_for_new_user_starts_with_baseline_measurement(app):
    with app.app_context():
        user = _create_user("calibration.new@example.com")

        calibration = compute_next_session(user.id)

        assert calibration is not None
        assert calibration.next_session_type == "baseline_measurement"
        assert calibration.next_injection_type == "none"
        assert float(calibration.next_injection_intensity) == 0.3
        assert calibration.target_dimension == "lexical_diversity"
        assert 8 <= calibration.next_injection_timing_seconds <= 12


def test_compute_next_session_uses_failure_mode_dimension_and_available_injection(app):
    with app.app_context():
        user = _create_user("calibration.target@example.com")

        db.session.add(
            FailureMode(
                user_id=user.id,
                mode_code="sentence_fragmentation",
                mode_label="Sentence Fragmentation",
                mode_description="Drops sentence completion under pressure.",
                primary_dimension="sentence_completion",
                confidence_score=0.9,
                evidence_session_count=8,
            )
        )

        db.session.add(
            SessionCalibration(
                user_id=user.id,
                next_session_type="vocabulary_pressure",
                next_injection_type="temporal",
                next_injection_intensity=0.5,
                next_injection_timing_seconds=10,
                target_dimension="sentence_completion",
                current_stress_threshold=0.5,
            )
        )
        db.session.commit()

        for idx in range(1, 13):
            _add_session(user.id, number=idx, early_exit=False, completed_at=datetime.utcnow() - timedelta(days=idx))

        calibration = compute_next_session(user.id)

        assert calibration.target_dimension == "sentence_completion"
        assert calibration.next_session_type == "distractor_challenge"
        assert calibration.next_injection_type == "distractor"
        assert float(calibration.next_injection_intensity) == 0.5


def test_compute_next_session_reduces_intensity_after_early_exit(app):
    with app.app_context():
        user = _create_user("calibration.early.exit@example.com")

        db.session.add(
            SessionCalibration(
                user_id=user.id,
                next_session_type="prosodic_drill",
                next_injection_type="interlocutor",
                next_injection_intensity=0.7,
                next_injection_timing_seconds=10,
                target_dimension="prosodic_confidence",
                current_stress_threshold=0.7,
            )
        )
        db.session.commit()

        _add_session(
            user.id,
            number=1,
            early_exit=True,
            completed_at=datetime.utcnow() - timedelta(minutes=5),
        )

        calibration = compute_next_session(user.id)

        assert calibration.last_session_early_exit is True
        assert calibration.next_session_type == "recovery_focus"
        assert float(calibration.next_injection_intensity) == 0.55


def test_calibrate_pressure_profile_alias_returns_calibration(app):
    with app.app_context():
        user = _create_user("calibration.alias@example.com")

        result = calibrate_pressure_profile(user.id, baseline_sessions=[])

        assert result is not None
        assert result.user_id == user.id
        assert SessionCalibration.query.filter_by(user_id=user.id).first() is not None


def test_get_session_prompt_falls_back_for_unknown_context_and_type():
    prompt = get_session_prompt("nonexistent_type", "Unknown Context")
    assert isinstance(prompt, str)
    assert len(prompt.strip()) > 20
