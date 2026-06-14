import os
from datetime import datetime, timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import Assessment, LsrcScore, User
from app.services import lsrc_engine


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
    user = User(
        email=email,
        email_verified=True,
        trial_ends_at=datetime.utcnow() + timedelta(days=14),
    )
    user.set_password("SecurePass9")
    db.session.add(user)
    db.session.commit()
    return user


def _analysis_result(transcript=None):
    text = transcript or (
        "I explained the release timeline clearly and answered follow-up questions "
        "with specific examples from our sprint review meeting yesterday."
    )
    timestamps = []
    cursor = 0.0
    for word in text.split():
        start = cursor
        end = start + 0.2
        timestamps.append({"word": word, "start": start, "end": end})
        cursor = end + 0.12

    return {
        "transcript": text,
        "word_timestamps": timestamps,
        "audio_features": None,
    }


def test_compute_lsrc_dimensions_persists_record(app):
    with app.app_context():
        user = _create_user("lsrc.user@example.com")

        record = lsrc_engine.compute_lsrc_dimensions(
            _analysis_result(),
            user.id,
            source_type="session",
            source_id=101,
            condition="prepared",
        )

        assert record.id is not None
        assert record.user_id == user.id
        assert record.source_type == "session"
        assert record.condition == "prepared"
        assert record.lexical_diversity is not None
        assert 0 <= float(record.lexical_diversity) <= 100


def test_compute_lsrc_scores_uses_baseline_reference_when_available(app):
    with app.app_context():
        user = _create_user("lsrc.baseline@example.com")

        baseline = Assessment(
            user_id=user.id,
            assessment_type="baseline",
            status="completed",
            created_at=datetime.utcnow() - timedelta(days=21),
            transcript_prepared="This is a baseline transcript for lexical comparison.",
        )
        db.session.add(baseline)
        db.session.flush()

        baseline_score = LsrcScore(
            user_id=user.id,
            source_type="assessment",
            source_id=baseline.id,
            condition="prepared",
            lexical_diversity=50,
            syntactic_complexity=55,
            prosodic_confidence=60,
            disfluency_rate=58,
            sentence_completion=62,
            recovery_speed_seconds=2.5,
            recovery_speed_score=70,
        )
        db.session.add(baseline_score)
        db.session.commit()

        record = lsrc_engine.compute_lsrc_scores(
            _analysis_result(
                "I described the migration plan and clarified each risk with actionable mitigation steps for stakeholders."
            ),
            user.id,
            source_type="session",
            source_id=202,
            condition="prepared",
        )

        assert record.lexical_diversity is not None
        assert 0 <= float(record.lexical_diversity) <= 100
        assert record.composite_score is not None


def test_compute_lsrc_scores_handles_metric_failure_gracefully(app, monkeypatch):
    with app.app_context():
        user = _create_user("lsrc.safe.compute@example.com")

        def _raise_metric(*args, **kwargs):
            raise RuntimeError("metric failure")

        monkeypatch.setattr(lsrc_engine.nlp_helpers, "compute_lexical_diversity", _raise_metric)

        record = lsrc_engine.compute_lsrc_scores(
            _analysis_result(),
            user.id,
            source_type="session",
            source_id=303,
            condition="spontaneous",
        )

        assert record.id is not None
        assert record.lexical_diversity is None
        assert record.syntactic_complexity is not None
