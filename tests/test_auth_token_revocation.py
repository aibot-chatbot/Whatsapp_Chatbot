import datetime
from unittest.mock import Mock, patch

import jwt
import pytest
from flask import Flask, jsonify
from werkzeug.security import check_password_hash, generate_password_hash

from app.decorators.auth_decorator import token_required
from app.decorators.platform_admin_decorator import platform_admin_required
from app.routes import auth_routes
from app.database import platform_admin_repository
from app.routes.user_routes import user_bp
from app.utils.auth_token import build_password_fingerprint, create_auth_token


JWT_SECRET = "synthetic-jwt-secret-for-password-revocation-tests"
OLD_PASSWORD = "OldPassword1!"
NEW_PASSWORD = "NewPassword1!"

pytestmark = pytest.mark.real_auth_token


class FakeSupabase:
    def __init__(self, user):
        self.user = user
        self.payload = None

    def table(self, name):
        self.table_name = name
        return self

    def update(self, payload):
        self.payload = dict(payload)
        return self

    def eq(self, *_args):
        return self

    def execute(self):
        if self.table_name == "users" and self.payload:
            self.user.update(self.payload)
        return Mock(data=[dict(self.user)])


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)


@pytest.fixture
def user():
    return {
        "id": 17,
        "company_id": 42,
        "full_name": "Auth User",
        "email": "auth@example.test",
        "role": "admin",
        "status": "active",
        "is_verified": True,
        "password_hash": generate_password_hash(OLD_PASSWORD),
    }


@pytest.fixture
def app_with_auth(user, monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    app.register_blueprint(auth_routes.auth_bp)
    app.register_blueprint(user_bp)

    @app.route("/protected")
    @token_required
    def protected():
        return jsonify({"status": "success"})

    monkeypatch.setattr(auth_routes, "get_user_by_email", lambda email: user)
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda _id: user)
    monkeypatch.setattr(platform_admin_repository, "get_platform_admin_by_user_id", lambda _id: None)
    return app


def _otp():
    return {
        "otp_code": "123456",
        "verified": True,
        "otp_expiry": (
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)
        ).isoformat(),
    }


def _login(client, email="auth@example.test", password=OLD_PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _protected(client, token, path="/protected"):
    return client.get(path, headers={"Authorization": f"Bearer {token}"})


def test_password_reset_revokes_existing_token_and_new_password_gets_valid_token(app_with_auth, user):
    client = app_with_auth.test_client()
    login_response = _login(client)
    assert login_response.status_code == 200
    old_token = login_response.get_json()["token"]
    assert _protected(client, old_token).status_code == 200

    fake_supabase = FakeSupabase(user)
    with patch("app.routes.auth_routes.get_password_reset_otp", return_value=_otp()), \
            patch("app.routes.auth_routes.delete_password_reset_otp") as delete_otp, \
            patch("app.database.db.supabase", fake_supabase):
        reset_response = client.post("/api/auth/reset-password", json={
            "email": user["email"],
            "otp": "123456",
            "password": NEW_PASSWORD,
            "confirm_password": NEW_PASSWORD,
        })

    assert reset_response.status_code == 200
    assert check_password_hash(user["password_hash"], NEW_PASSWORD)
    delete_otp.assert_called_once_with(user["email"])
    assert _protected(client, old_token).status_code == 401

    new_login_response = _login(client, password=NEW_PASSWORD)
    assert new_login_response.status_code == 200
    new_token = new_login_response.get_json()["token"]
    assert _protected(client, new_token).status_code == 200


def test_logged_in_password_change_revokes_existing_token_and_new_token_works(app_with_auth, user, monkeypatch):
    client = app_with_auth.test_client()
    old_token = _login(client).get_json()["token"]

    def update_user(_user_id, payload):
        user.update(payload)
        return dict(user)

    monkeypatch.setattr("app.routes.user_routes.get_user_by_id", lambda _id: user)
    monkeypatch.setattr("app.routes.user_routes.update_user", update_user)

    response = client.put("/api/user/password", headers={"Authorization": f"Bearer {old_token}"}, json={
        "current_password": OLD_PASSWORD,
        "new_password": NEW_PASSWORD,
        "confirm_password": NEW_PASSWORD,
    })

    assert response.status_code == 200
    assert _protected(client, old_token).status_code == 401
    new_token = _login(client, password=NEW_PASSWORD).get_json()["token"]
    assert _protected(client, new_token).status_code == 200


def test_explicit_null_password_hash_user_can_authenticate(monkeypatch):
    user = {
        "id": 18,
        "company_id": 42,
        "email": "google@example.test",
        "role": "member",
        "status": "active",
        "password_hash": None,
    }
    token = create_auth_token(user)
    app = Flask(__name__)
    app.config.update(TESTING=True)

    @app.route("/protected")
    @token_required
    def protected():
        return jsonify({"status": "success"})

    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda _id: user)
    assert _protected(app.test_client(), token).status_code == 200


def test_missing_password_hash_projection_fails_closed(monkeypatch):
    issuer = {
        "id": 19,
        "company_id": 42,
        "email": "missing@example.test",
        "role": "admin",
        "status": "active",
        "password_hash": None,
    }
    token = create_auth_token(issuer)
    current_user = {key: value for key, value in issuer.items() if key != "password_hash"}
    app = Flask(__name__)
    app.config.update(TESTING=True)

    @app.route("/protected")
    @token_required
    def protected():
        return jsonify({"status": "success"})

    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda _id: current_user)
    assert _protected(app.test_client(), token).status_code == 401


@pytest.mark.parametrize("platform_role", ["admin", "super_admin"])
def test_platform_staff_token_is_revoked_after_password_change(platform_role, monkeypatch, user):
    token = create_auth_token(user)
    user["password_hash"] = generate_password_hash(NEW_PASSWORD)
    app = Flask(__name__)
    app.config.update(TESTING=True)

    @app.route("/platform")
    @platform_admin_required
    def platform_route():
        return jsonify({"status": "success"})

    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda _id: user)
    mapping = {
        "id": 7,
        "user_id": user["id"],
        "is_active": True,
        "platform_role": platform_role,
        "modules": {"billing": True, "support": True, "customers": True},
    }
    monkeypatch.setattr(
        "app.decorators.platform_admin_decorator.get_active_platform_admin_by_user_id",
        Mock(return_value=mapping),
    )
    assert _protected(app.test_client(), token, "/platform").status_code == 401


def test_legacy_token_without_password_fingerprint_is_rejected(user):
    token = jwt.encode({
        "user_id": user["id"],
        "company_id": user["company_id"],
        "email": user["email"],
        "role": user["role"],
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    }, JWT_SECRET, algorithm="HS256")
    app = Flask(__name__)
    app.config.update(TESTING=True)

    @app.route("/protected")
    @token_required
    def protected():
        return jsonify({"status": "success"})

    with patch("app.database.user_repository.get_user_by_id", return_value=user):
        response = _protected(app.test_client(), token)
    assert response.status_code == 401


def test_expired_token_still_uses_existing_expiry_rejection(user):
    token = jwt.encode({
        "user_id": user["id"],
        "company_id": user["company_id"],
        "email": user["email"],
        "role": user["role"],
        "iat": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2),
        "exp": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1),
        "pwdv": build_password_fingerprint(user),
    }, JWT_SECRET, algorithm="HS256")
    app = Flask(__name__)
    app.config.update(TESTING=True)

    @app.route("/protected")
    @token_required
    def protected():
        return jsonify({"status": "success"})

    response = _protected(app.test_client(), token)
    assert response.status_code == 401
    assert response.get_json()["message"] == "Token has expired! Please log in again."
