"""Exercise OTP budgets through the normal application, without external calls."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app import create_app


@pytest.fixture
def reset_client(monkeypatch):
    monkeypatch.setenv("RATELIMIT_ENABLED", "true")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "memory://")
    monkeypatch.setenv("RATELIMIT_OTP", "3/hour")
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def reset_payload(email="victim@example.test", otp="000000"):
    return {"email": email, "otp": otp, "password": "NewPassword1!",
            "confirm_password": "NewPassword1!"}


def post(client, endpoint, payload, address="198.51.100.1"):
    return client.post("/api/auth/" + endpoint, json=payload,
                       environ_base={"REMOTE_ADDR": address})


def otp_record():
    return {"otp_code": "123456", "verified": True,
            "otp_expiry": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()}


def test_reset_guess_budget_survives_ip_endpoint_and_email_variations(reset_client):
    with patch("app.routes.auth_routes.get_password_reset_otp", return_value=otp_record()) as lookup, \
            patch("app.routes.auth_routes.mark_password_reset_otp_verified") as verified:
        for index, endpoint in enumerate(["verify-reset-otp", "reset-password", "verify-reset-otp"]):
            response = post(reset_client, endpoint,
                            reset_payload("  VICTIM@example.test  "), f"198.51.100.{index + 1}")
            assert response.status_code == 400
        blocked = post(reset_client, "verify-reset-otp", reset_payload(otp="123456"), "198.51.100.9")
        assert blocked.status_code == 429
        assert lookup.call_count == 3
        verified.assert_not_called()
        assert post(reset_client, "reset-password", reset_payload(otp="123456"), "198.51.100.10").status_code == 429


def test_correct_verify_then_reset_still_works_and_consumes_the_challenge(reset_client):
    database = MagicMock()
    with patch("app.routes.auth_routes.get_password_reset_otp", return_value=otp_record()), \
            patch("app.routes.auth_routes.mark_password_reset_otp_verified") as verified, \
            patch("app.routes.auth_routes.delete_password_reset_otp") as delete, \
            patch("app.database.db.supabase", database):
        payload = reset_payload(otp="123456")
        assert post(reset_client, "verify-reset-otp", payload).status_code == 200
        assert post(reset_client, "reset-password", payload).status_code == 200
        verified.assert_called_once_with("victim@example.test")
        delete.assert_called_once_with("victim@example.test")
        database.table.return_value.update.return_value.eq.assert_called_once_with("email", "victim@example.test")


def test_other_accounts_keep_an_independent_verification_budget(reset_client):
    with patch("app.routes.auth_routes.get_password_reset_otp", return_value=otp_record()), \
            patch("app.routes.auth_routes.mark_password_reset_otp_verified") as verified:
        for index in range(4):
            post(reset_client, "verify-reset-otp", reset_payload(), f"198.51.100.{index + 1}")
        response = post(reset_client, "verify-reset-otp",
                        reset_payload("other@example.test", "123456"), "198.51.100.20")
        assert response.status_code == 200
        verified.assert_called_once_with("other@example.test")


def test_reissuing_an_otp_does_not_reset_the_guess_budget(reset_client):
    with patch("app.routes.auth_routes.get_password_reset_otp", return_value=otp_record()), \
            patch("app.routes.auth_routes.get_user_by_email", return_value={"full_name": "Test"}), \
            patch("app.routes.auth_routes.upsert_password_reset_otp") as issue, \
            patch("app.services.email_service.send_reset_email", return_value=True), \
            patch("app.routes.auth_routes.mark_password_reset_otp_verified") as verified:
        for index in range(3):
            assert post(reset_client, "verify-reset-otp", reset_payload(), f"198.51.100.{index + 1}").status_code == 400
        assert post(reset_client, "forgot-password", {"email": "victim@example.test"}, "198.51.100.8").status_code == 200
        issue.assert_called_once()
        assert post(reset_client, "verify-reset-otp", reset_payload(otp="123456"), "198.51.100.9").status_code == 429
        verified.assert_not_called()


def test_registration_rate_limit_stops_password_hashing_and_email_abuse(reset_client):
    with patch("app.database.db.supabase"), \
            patch("app.routes.auth_routes.get_user_by_email", return_value=None), \
            patch("app.routes.auth_routes.generate_password_hash", return_value="synthetic-hash") as hashing, \
            patch("app.routes.auth_routes.send_otp_email", return_value=True) as email:
        payload = {**reset_payload(), "first_name": "Test", "last_name": "User", "company_name": "Test"}
        for index in range(3):
            payload["email"] = f"test{index}@example.test"
            assert post(reset_client, "register", payload).status_code == 200
        assert post(reset_client, "register", payload).status_code == 429
        assert hashing.call_count == 3
        assert email.call_count == 3


def test_signup_otp_guesses_share_an_account_budget_across_ips(reset_client):
    with patch("app.database.db.supabase") as database, \
            patch("app.routes.auth_routes.create_company") as create:
        database.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [otp_record()]
        for index in range(3):
            assert post(reset_client, "verify-otp", reset_payload(), f"198.51.100.{index + 1}").status_code == 400
        assert post(reset_client, "verify-otp", reset_payload("  VICTIM@example.test  "), "198.51.100.9").status_code == 429
        create.assert_not_called()


def test_pending_signup_password_budget_follows_email_across_ips(reset_client):
    with patch("app.database.db.supabase") as database, \
            patch("app.routes.auth_routes.get_user_by_email", return_value=None), \
            patch("app.routes.auth_routes.generate_password_hash", return_value="synthetic-hash"), \
            patch("app.routes.auth_routes.check_password_hash", return_value=False) as compare, \
            patch("app.routes.auth_routes.send_otp_email") as email:
        database.table.return_value.upsert.return_value.execute.return_value.data = []
        database.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"password_hash": "synthetic-hash"}]
        payload = {**reset_payload(), "first_name": "Test", "last_name": "User", "company_name": "Test"}
        for index in range(3):
            assert post(reset_client, "register", payload, f"198.51.100.{index + 1}").status_code == 409
        payload["email"] = "  VICTIM@example.test  "
        assert post(reset_client, "register", payload, "198.51.100.9").status_code == 429
        assert compare.call_count == 3
        email.assert_not_called()
