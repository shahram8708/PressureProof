import os
from datetime import datetime, timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import User


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


@pytest.fixture
def client(app):
    return app.test_client()


def _register_payload(email):
    return {
        "email": email,
        "password": "SecurePass9",
        "confirm_password": "SecurePass9",
        "country": "India",
        "l1_language": "Hindi",
        "professional_context": "IT Services",
    }


def test_register_success_sets_trial_and_display_name(app, client):
    response = client.post("/register", data=_register_payload("new.user@example.com"))

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    with app.app_context():
        user = User.query.filter_by(email="new.user@example.com").first()
        assert user is not None
        assert user.display_name == "New.User"
        expected = datetime.utcnow() + timedelta(days=14)
        assert abs((user.trial_ends_at - expected).total_seconds()) < 180


def test_register_duplicate_email_shows_error(app, client):
    first = client.post("/register", data=_register_payload("duplicate@example.com"))
    assert first.status_code == 302

    second = client.post(
        "/register",
        data=_register_payload("duplicate@example.com"),
        follow_redirects=True,
    )
    assert second.status_code == 200
    assert b"An account with that email already exists" in second.data


def test_register_weak_password_shows_validator_message(client):
    response = client.post(
        "/register",
        data={
            "email": "weakpass@example.com",
            "password": "abc",
            "confirm_password": "abc",
            "country": "India",
            "l1_language": "Hindi",
            "professional_context": "IT Services",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Password must include at least one uppercase letter and one number" in response.data


def test_login_success_updates_last_login(app, client):
    with app.app_context():
        user = User(
            email="verified@example.com",
            display_name="Verified User",
            email_verified=True,
            trial_ends_at=datetime.utcnow() + timedelta(days=14),
        )
        user.set_password("SecurePass9")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    response = client.post(
        "/login",
        data={
            "email": "verified@example.com",
            "password": "SecurePass9",
            "remember_me": "y",
        },
    )

    assert response.status_code == 302
    assert "/dashboard" in response.headers["Location"]

    with app.app_context():
        updated = User.query.get(user_id)
        assert updated.last_login_at is not None


def test_login_rejects_banned_user(app, client):
    with app.app_context():
        user = User(
            email="banned@example.com",
            email_verified=True,
            is_banned=True,
            ban_reason="abuse",
            trial_ends_at=datetime.utcnow() + timedelta(days=14),
        )
        user.set_password("SecurePass9")
        db.session.add(user)
        db.session.commit()

    response = client.post(
        "/login",
        data={"email": "banned@example.com", "password": "SecurePass9"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Your account has been suspended" in response.data


def test_login_unverified_email(app, client):
    with app.app_context():
        user = User(
            email="unverified@example.com",
            email_verified=False,
            trial_ends_at=datetime.utcnow() + timedelta(days=14),
        )
        user.set_password("SecurePass9")
        db.session.add(user)
        db.session.commit()

    response = client.post(
        "/login",
        data={"email": "unverified@example.com", "password": "SecurePass9"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Please verify your email address before logging in." in response.data


def test_forgot_password_always_returns_generic_success(client):
    response = client.post(
        "/forgot-password",
        data={"email": "no-such-user@example.com"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"If an account with that email exists, you will receive a reset link shortly." in response.data


def test_reset_password_flow_updates_password(app, client):
    with app.app_context():
        user = User(
            email="reset.user@example.com",
            email_verified=True,
            trial_ends_at=datetime.utcnow() + timedelta(days=14),
        )
        user.set_password("OldPass9")
        db.session.add(user)
        db.session.commit()
        token = user.generate_password_reset_token()

    response = client.post(
        f"/reset-password/{token}",
        data={"password": "NewPass9", "confirm_password": "NewPass9"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Password updated successfully." in response.data

    with app.app_context():
        updated = User.query.filter_by(email="reset.user@example.com").first()
        assert updated.check_password("NewPass9")
