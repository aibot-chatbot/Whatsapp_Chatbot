"""Pending signup credentials cannot be replaced by another unauthenticated request."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Lock
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from flask import Flask
from supabase import ClientOptions, create_client

from app.database import db
from app.routes import auth_routes


@pytest.fixture
def registration(monkeypatch):
    # Exercise the installed SDK's request encoding; all HTTP stays in this transport.
    state = SimpleNamespace(row=None, post_barrier=None, user_verified=False)
    lock = Lock()

    def database(request):
        if request.url.path.endswith("/users"):
            assert request.method == "PATCH"
            assert json.loads(request.content) == {"is_verified": True}
            state.user_verified = True
            return httpx.Response(200, json=[{"id": 301, "is_verified": True}])
        assert request.url.path.endswith("/pending_registrations")
        if request.method == "POST" and state.post_barrier:
            state.post_barrier.wait(timeout=10)
        with lock:
            if request.method == "GET":
                rows = [dict(state.row)] if state.row else []
            elif request.method == "POST":
                payload = json.loads(request.content)
                if state.row and "resolution=ignore-duplicates" in request.headers.get("Prefer", ""):
                    rows = []
                else:
                    state.row = payload
                    rows = [dict(payload)]
            elif request.method == "PATCH":
                matches = state.row and all(
                    condition.startswith("eq.") and str(state.row.get(field)) == condition[3:]
                    for field, condition in request.url.params.multi_items()
                )
                if matches:
                    state.row.update(json.loads(request.content))
                rows = [dict(state.row)] if matches else []
            elif request.method == "DELETE":
                rows = [dict(state.row)] if state.row else []
                state.row = None
            else:
                raise AssertionError(f"Unexpected database operation: {request.method}")
        return httpx.Response(200, json=rows)

    client = httpx.Client(transport=httpx.MockTransport(database))
    supabase = create_client("https://registration.example.test", "synthetic-key",
                             options=ClientOptions(httpx_client=client))
    monkeypatch.setattr(db, "supabase", supabase)
    monkeypatch.setattr(auth_routes, "get_user_by_email", Mock(return_value=None))
    monkeypatch.setattr(auth_routes, "generate_password_hash", lambda password: "test-hash:" + password)
    monkeypatch.setattr(auth_routes, "check_password_hash", lambda hashed, password: hashed == "test-hash:" + password)
    monkeypatch.setattr(auth_routes, "generate_otp", lambda: "654321")
    send = Mock(return_value=True)
    monkeypatch.setattr(auth_routes, "send_otp_email", send)
    monkeypatch.setattr("socket.socket.connect", Mock(side_effect=AssertionError("Network disabled")))
    app = Flask(__name__)
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    auth_routes.limiter.init_app(app)
    app.register_blueprint(auth_routes.auth_bp)

    def submit(name="Original", email="audit@example.test"):
        with app.test_client() as browser:
            return browser.post("/api/auth/register", json={
                "email": email, "first_name": name, "last_name": "User",
                "company_name": name + " Company", "password": name + "Pass1!",
                "confirm_password": name + "Pass1!",
            })

    yield SimpleNamespace(state=state, submit=submit, send=send, app=app)
    client.close()


def test_fresh_registration_saves_and_sends_one_challenge(registration):
    assert registration.submit().status_code == 200
    assert registration.state.row["password_hash"] == "test-hash:OriginalPass1!"
    # Registration now also passes a one-click verification link. The link is
    # None when no public base URL is configured, in which case the email
    # degrades to the code-only form. Assert the stable parts explicitly and
    # allow either shape for the link.
    registration.send.assert_called_once()
    args, kwargs = registration.send.call_args
    assert args == ("audit@example.test", "654321")
    assert kwargs["recipient_name"] == "Original"
    assert "verify_url" in kwargs, "registration must offer a verification link"
    assert kwargs["verify_url"] is None or kwargs["verify_url"].startswith("http")


def test_verified_account_cannot_be_registered_again(registration, monkeypatch):
    monkeypatch.setattr(auth_routes, "get_user_by_email", Mock(return_value={"is_verified": True}))
    assert registration.submit().status_code == 409
    assert registration.state.row is None
    registration.send.assert_not_called()


def test_active_challenge_keeps_password_profile_and_otp(registration):
    assert registration.submit().status_code == 200
    original = dict(registration.state.row)
    response = registration.submit("Replacement", "  AUDIT@example.test  ")
    assert response.status_code == 409
    assert registration.state.row == original
    assert registration.send.call_count == 1


@pytest.mark.parametrize("expired", [False, True])
def test_fresh_browser_can_resume_only_with_original_password(registration, expired):
    assert registration.submit().status_code == 200
    if expired:
        registration.state.row["otp_expiry"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    original = dict(registration.state.row)
    response = registration.submit(email="  AUDIT@example.test  ")
    assert response.status_code == 200
    assert response.get_json()["code"] == "registration_pending"
    assert response.get_json()["data"] == {"email": "audit@example.test"}
    assert registration.state.row == original
    assert registration.send.call_count == 1
    assert registration.submit("DifferentPassword").status_code == 409
    assert registration.state.row == original


def test_pending_recovery_verifies_real_stored_password_hash(registration, monkeypatch):
    from werkzeug.security import check_password_hash, generate_password_hash

    assert registration.submit().status_code == 200
    registration.state.row["password_hash"] = generate_password_hash("OriginalPass1!")
    original = dict(registration.state.row)
    monkeypatch.setattr(auth_routes, "check_password_hash", check_password_hash)
    assert registration.submit("DifferentPassword").status_code == 409
    assert registration.submit().status_code == 200
    assert registration.state.row == original
    assert registration.send.call_count == 1


def test_expired_challenge_cannot_replace_signup_credentials(registration):
    assert registration.submit().status_code == 200
    registration.state.row["otp_expiry"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    original = dict(registration.state.row)
    response = registration.submit("Replacement")
    assert response.status_code == 409
    assert registration.state.row == original
    assert registration.send.call_count == 1
    assert "wait" not in response.get_json()["message"].lower()


def test_expired_signup_resend_and_verify_keep_original_credentials(registration, monkeypatch):
    monkeypatch.setattr(auth_routes, "generate_otp", Mock(side_effect=["111111", "222222", "333333"]))
    create_company = Mock(return_value={"id": 201})
    create_user = Mock(return_value={"id": 301})
    monkeypatch.setattr(auth_routes, "create_company", create_company)
    monkeypatch.setattr(auth_routes, "create_user", create_user)
    monkeypatch.setattr(auth_routes, "ensure_default_company_subscription", Mock())
    assert registration.submit().status_code == 200
    registration.state.row["otp_expiry"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    replacement = registration.submit("Replacement")
    # The original browser's verification page retains only the email address.
    with registration.app.test_client() as browser:
        resent = browser.post("/api/auth/resend-otp", json={"email": "audit@example.test"})
        assert resent.status_code == 200
        verified = browser.post("/api/auth/verify-otp", json={"email": "audit@example.test", "otp": "333333"})
    assert verified.status_code == 200
    assert create_user.call_args.kwargs["password_hash"] == "test-hash:OriginalPass1!"
    assert create_user.call_args.kwargs["full_name"] == "Original User"
    assert create_company.call_args.kwargs["company_name"] == "Original Company"
    assert replacement.status_code == 409
    assert registration.send.call_count == 2
    assert registration.state.user_verified is True
    assert registration.state.row is None


@pytest.mark.parametrize("expiry", [None, "not-a-date"])
def test_unknown_expiry_cannot_authorize_replacement(registration, expiry):
    assert registration.submit().status_code == 200
    registration.state.row["otp_expiry"] = expiry
    original = dict(registration.state.row)
    assert registration.submit("Replacement").status_code == 409
    assert registration.state.row == original
    assert registration.send.call_count == 1


@pytest.mark.parametrize("expired", [False, True])
def test_concurrent_registrations_never_replace_pending_credentials(registration, expired):
    if expired:
        assert registration.submit().status_code == 200
        registration.state.row["otp_expiry"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        registration.send.reset_mock()
        original = dict(registration.state.row)
    registration.state.post_barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(registration.submit, ["First", "Second"]))
    if expired:
        assert [response.status_code for response in responses] == [409, 409]
        assert registration.state.row == original
        registration.send.assert_not_called()
        return
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert registration.send.call_count == 1
    winner = registration.send.call_args.kwargs["recipient_name"]
    assert registration.state.row["password_hash"] == "test-hash:" + winner + "Pass1!"
