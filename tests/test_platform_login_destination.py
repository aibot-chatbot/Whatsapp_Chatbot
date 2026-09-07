"""Staff routing is refreshed from the database for both sign-in methods."""

from unittest.mock import Mock

import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

from app.routes import auth_routes
from app.database import platform_admin_repository


@pytest.fixture
def login_client(monkeypatch):
    user = {
        "id": 17, "company_id": 8, "email": "staff@example.test",
        "full_name": "Test Staff", "role": "admin", "status": "active",
        "is_verified": True, "password_hash": generate_password_hash("Synthetic-pass-42!"),
    }
    monkeypatch.setattr(auth_routes, "get_user_by_email", lambda _email: user)
    monkeypatch.setattr(auth_routes, "get_jwt_secret", lambda: "synthetic-key-for-login-tests-123456")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "synthetic-client")
    monkeypatch.setattr("requests.get", lambda *_a, **_kw: Mock(status_code=200, json=lambda: {
        "aud": "synthetic-client", "email": user["email"], "email_verified": True,
    }))
    app = Flask(__name__)
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    app.register_blueprint(auth_routes.auth_bp)
    return app.test_client()


@pytest.mark.parametrize("method", ["login", "google"])
@pytest.mark.parametrize("mapping,destination,status", [
    (None, "bots.html", 200),
    ({"is_active": True, "platform_role": "admin", "modules": {"billing": True}}, "admin.html", 200),
    ({"is_active": True, "platform_role": "super_admin", "modules": {}}, "superadmin.html", 200),
    ({"is_active": False, "platform_role": "super_admin"}, None, 403),
    ({"is_active": True}, None, 503),
    ({"is_active": True, "platform_role": "owner"}, None, 503),
])
def test_login_destination(login_client, monkeypatch, method, mapping, destination, status):
    lookup = Mock(return_value=mapping)
    monkeypatch.setattr(platform_admin_repository, "get_platform_admin_by_user_id", lookup)
    response = login_client.post("/api/auth/" + method, json={
        "email": "staff@example.test", "password": "Synthetic-pass-42!",
        "credential": "synthetic-google-credential", "role": "super_admin",
        "redirect_url": "https://untrusted.example.test",
    })
    assert response.status_code == status
    data = response.get_json()
    if destination:
        assert data["redirect_url"] == destination
        assert data["user"]["role"] == "admin"  # Tenant role remains a separate concept.
        assert "password_hash" not in data["user"]
    else:
        assert "token" not in data
        assert "redirect_url" not in data
    lookup.assert_called_once_with(17)


@pytest.mark.parametrize("method", ["login", "google"])
def test_mapping_failure_does_not_release_token(login_client, monkeypatch, method):
    monkeypatch.setattr(platform_admin_repository, "get_platform_admin_by_user_id",
                        Mock(side_effect=RuntimeError("private database failure")))
    response = login_client.post("/api/auth/" + method, json={
        "email": "staff@example.test", "password": "Synthetic-pass-42!",
        "credential": "synthetic-google-credential",
    })
    assert response.status_code == 503
    assert "token" not in response.get_json()
    assert "private database failure" not in response.get_data(as_text=True)
