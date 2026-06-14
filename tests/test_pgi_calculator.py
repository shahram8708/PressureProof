import os
from datetime import date, datetime, timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import LsrcScore, User
from app.services.pgi_calculator import (
    calculate_preparation_gap_index,
    compute_pgi_projection,
    compute_weekly_pgi,
    get_pgi_trend_data,
)


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


def _add_lsrc_score(user_id, condition, source_type, source_id, scored_at, base):
    score = LsrcScore(
        user_id=user_id,
        source_type=source_type,
        source_id=source_id,
        condition=condition,
        scored_at=scored_at,
        lexical_diversity=base,
        syntactic_complexity=base,
        prosodic_confidence=base,
        disfluency_rate=base,
        sentence_completion=base,
        recovery_speed_seconds=2.0,
        recovery_speed_score=base,
    )
    db.session.add(score)


def test_calculate_preparation_gap_index_returns_expected_values():
    assert calculate_preparation_gap_index({"prepared_composite": 80, "spontaneous_composite": 60}) == 25.0
    assert calculate_preparation_gap_index({"prepared_composite": 0, "spontaneous_composite": 60}) is None
    assert calculate_preparation_gap_index({"prepared_composite": 70}) is None


def test_compute_pgi_projection_detects_improving_trend():
    trend_data = [
        {"week_label": "W1", "pgi_score": 40},
        {"week_label": "W2", "pgi_score": 35},
        {"week_label": "W3", "pgi_score": 31},
        {"week_label": "W4", "pgi_score": 27},
    ]

    projection = compute_pgi_projection(trend_data)

    assert projection["projection_available"] is True
    assert projection["trend_direction"] == "improving"
    assert projection["slope"] < 0


def test_compute_pgi_projection_requires_at_least_two_points():
    projection = compute_pgi_projection([{"week_label": "W1", "pgi_score": None}])
    assert projection == {"projection_available": False}


def test_compute_weekly_pgi_creates_fallback_record_without_scores(app):
    with app.app_context():
        user = _create_user("pgi.empty@example.com")
        week_start = date.today() - timedelta(days=date.today().weekday())

        record = compute_weekly_pgi(user.id, week_start=week_start)

        assert record.user_id == user.id
        assert record.week_start_date == week_start
        assert record.pgi_score is None


def test_compute_weekly_pgi_and_trend_data_with_scores(app):
    with app.app_context():
        user = _create_user("pgi.full@example.com")
        week_start = date.today() - timedelta(days=date.today().weekday())
        week_start_dt = datetime.combine(week_start, datetime.min.time())

        _add_lsrc_score(
            user.id,
            condition="prepared",
            source_type="session",
            source_id=1,
            scored_at=week_start_dt + timedelta(days=1),
            base=80,
        )
        _add_lsrc_score(
            user.id,
            condition="prepared",
            source_type="session",
            source_id=2,
            scored_at=week_start_dt + timedelta(days=2),
            base=78,
        )
        _add_lsrc_score(
            user.id,
            condition="spontaneous",
            source_type="snapspeak",
            source_id=11,
            scored_at=week_start_dt + timedelta(days=1, hours=1),
            base=60,
        )
        _add_lsrc_score(
            user.id,
            condition="spontaneous",
            source_type="snapspeak",
            source_id=12,
            scored_at=week_start_dt + timedelta(days=2, hours=2),
            base=58,
        )
        db.session.commit()

        record = compute_weekly_pgi(user.id, week_start=week_start)

        assert record.pgi_score is not None
        assert float(record.pgi_score) > 0
        assert record.sessions_count >= 1
        assert record.snapspeak_count >= 1

        trend = get_pgi_trend_data(user.id, weeks=6)
        assert len(trend) == 6
        assert any(point["pgi_score"] is not None for point in trend)
