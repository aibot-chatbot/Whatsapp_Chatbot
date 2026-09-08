import logging
from unittest.mock import patch

import pytest
from flask import Flask

from app.rate_limit import init_limiter, limiter


@pytest.mark.parametrize("storage_uri", [
    "redis://test-user:synthetic-private-password@cache.invalid:6379/0",
    "rediss://test-user:synthetic%40private-password@cache.invalid:6379/0?token=synthetic-secret",
])
def test_rate_limit_startup_does_not_log_connection_credentials(caplog, storage_uri):
    app = Flask(__name__)
    app.config.update(RATELIMIT_ENABLED=True, RATELIMIT_STORAGE_URI=storage_uri)
    with patch.object(limiter, "init_app") as initialize, caplog.at_level(logging.INFO):
        assert init_limiter(app) is limiter
    initialize.assert_called_once_with(app)
    assert "initialized" in caplog.text
    assert "synthetic" not in caplog.text
    assert "cache.invalid" not in caplog.text


@pytest.mark.parametrize("endpoint", ["register", "verify-otp", "reset-password"])
def test_authentication_failures_do_not_expose_database_details(endpoint, caplog, monkeypatch):
    from app import create_app

    monkeypatch.setenv("RATELIMIT_ENABLED", "false")
    app = create_app()
    app.config["TESTING"] = True
    monkeypatch.setattr(logging.getLogger(), "handlers", [caplog.handler])
    private_error = RuntimeError("synthetic-secret at internal-database.invalid for private@example.test")
    pending = {"first_name": "Test", "last_name": "User", "company_name": "Test Company",
               "password_hash": "synthetic-hash", "otp_code": "123456",
               "otp_expiry": "2099-01-01T00:00:00+00:00", "verified": True}
    with patch("app.database.db.supabase") as database, \
            patch("app.routes.auth_routes.get_user_by_email", return_value=None), \
            patch("app.routes.auth_routes.get_password_reset_otp", return_value=pending), \
            patch("app.routes.auth_routes.create_company", side_effect=private_error), \
            patch("httpx.Client.send", side_effect=AssertionError("External HTTP disabled")), \
            caplog.at_level(logging.ERROR):
        database.table.return_value.upsert.return_value.execute.side_effect = private_error
        database.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [pending]
        database.table.return_value.update.return_value.eq.return_value.execute.side_effect = private_error
        response = app.test_client().post("/api/auth/" + endpoint, json={
            "email": "test@example.test", "otp": "123456", "first_name": "Test",
            "last_name": "User", "company_name": "Test Company",
            "password": "SyntheticPassword1!", "confirm_password": "SyntheticPassword1!",
        })
    assert response.status_code == 500
    output = response.get_data(as_text=True) + caplog.text
    assert "synthetic-secret" not in output
    assert "internal-database.invalid" not in output
    assert "private@example.test" not in output


def test_signup_subscription_failure_keeps_success_without_leaking_details(caplog, monkeypatch):
    from app import create_app

    monkeypatch.setenv("RATELIMIT_ENABLED", "false")
    app = create_app()
    monkeypatch.setattr(logging.getLogger(), "handlers", [caplog.handler])
    pending = {"first_name": "Test", "last_name": "User", "company_name": "Test Company",
               "password_hash": "synthetic-hash", "otp_code": "123456",
               "otp_expiry": "2099-01-01T00:00:00+00:00"}
    with patch("app.database.db.supabase") as database, \
            patch("app.routes.auth_routes.create_company", return_value={"id": 41}), \
            patch("app.routes.auth_routes.create_user", return_value={"id": 21}), \
            patch("app.routes.auth_routes.ensure_default_company_subscription",
                  side_effect=RuntimeError("synthetic-private-billing-marker")), \
            patch("httpx.Client.send", side_effect=AssertionError("External HTTP disabled")), \
            caplog.at_level(logging.ERROR):
        database.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [pending]
        response = app.test_client().post("/api/auth/verify-otp", json={"email": "test@example.test", "otp": "123456"})
    assert response.status_code == 200
    assert "subscription" in caplog.text
    assert "synthetic-private-billing-marker" not in caplog.text
