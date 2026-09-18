"""Cloudflare Turnstile guards the four public auth endpoints, off by default.

Three properties are pinned here, in order of how badly each one hurts when it
breaks:

1. OFF is byte-identical to today. The keys do not exist yet, so an accidental
   half-configuration must not change a single response.
2. ON fails CLOSED. Missing, blank, rejected or unverifiable tokens are all
   refused before the handler runs -- a bot check that lets the request through
   on doubt is decoration.
3. No secret and no token ever reaches a response body or a log record.
"""

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from flask import Flask

from app.routes import auth_routes, invite_routes
from app.services import turnstile_service


SITE_KEY = "0x4TESTSITEKEYPUBLIC"
SECRET_KEY = "0x4TESTSECRETKEYPRIVATE"
TOKEN = "synthetic-turnstile-token"

#: (path, payload, status a reached handler answers with).
#: Each payload stops in the handler's own validation before any database call,
#: so "the handler ran" is observable without mocking the world.
GUARDED = [
    ("/api/auth/login", {"email": "a@b.test", "password": "x"}, 404),
    ("/api/auth/register", {}, 400),
    ("/api/auth/forgot-password", {}, 400),
    ("/api/invites/accept", {"unused": "x"}, 400),
]


@pytest.fixture
def app():
    application = Flask(__name__)
    application.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    auth_routes.limiter.init_app(application)
    application.register_blueprint(auth_routes.auth_bp)
    application.register_blueprint(invite_routes.invite_bp)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def reached(monkeypatch):
    """Proves a request got past the guard into the endpoint's own logic."""
    lookup = Mock(return_value=None)
    monkeypatch.setattr(auth_routes, "get_user_by_email", lookup)
    return lookup


@pytest.fixture
def siteverify(monkeypatch):
    """Records every siteverify call and serves a scripted reply."""
    calls = []

    def post(url, **kwargs):
        calls.append(SimpleNamespace(url=url, **kwargs))
        outcome = state.outcome
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(
            status_code=state.status_code,
            json=lambda: outcome,
            raise_for_status=Mock(),
        )

    state = SimpleNamespace(calls=calls, outcome={"success": True}, status_code=200)
    monkeypatch.setattr(turnstile_service.requests, "post", post)
    return state


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("TURNSTILE_ENABLED", "true")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", SECRET_KEY)
    monkeypatch.setenv("TURNSTILE_SITE_KEY", SITE_KEY)


@pytest.fixture(autouse=True)
def unconfigured(monkeypatch):
    """Every test starts from the deployed reality: no Turnstile keys at all."""
    for name in ("TURNSTILE_ENABLED", "TURNSTILE_SECRET_KEY", "TURNSTILE_SITE_KEY"):
        monkeypatch.delenv(name, raising=False)


# ── 1. Off by default ──────────────────────────────────────────────────────


@pytest.mark.parametrize("path, payload, status", GUARDED)
def test_unconfigured_requests_are_unchanged_and_never_call_cloudflare(
    client, reached, siteverify, path, payload, status
):
    response = client.post(path, json=payload)

    assert response.status_code == status
    assert siteverify.calls == []


@pytest.mark.parametrize("path, payload, status", GUARDED)
def test_disabled_response_is_identical_with_and_without_a_token(
    client, reached, siteverify, path, payload, status
):
    without = client.post(path, json=payload)
    with_token = client.post(path, json=dict(payload, **{"cf-turnstile-response": TOKEN}))

    assert (without.status_code, without.get_json()) == (status, with_token.get_json())
    assert siteverify.calls == []


@pytest.mark.parametrize("missing", ["TURNSTILE_SECRET_KEY", "TURNSTILE_SITE_KEY"])
def test_flag_without_both_keys_stays_off_rather_than_locking_everyone_out(
    client, reached, siteverify, enabled, monkeypatch, missing
):
    monkeypatch.setenv(missing, "   ")

    assert turnstile_service.is_enabled() is False
    assert client.post("/api/auth/login", json={"email": "a@b.test", "password": "x"}).status_code == 404
    assert siteverify.calls == []


def test_the_flag_is_reread_per_request_so_it_needs_no_deploy(
    client, reached, siteverify, enabled, monkeypatch
):
    assert client.post("/api/auth/login", json={"email": "a@b.test"}).status_code == 403

    monkeypatch.setenv("TURNSTILE_ENABLED", "false")

    assert client.post("/api/auth/login", json={"email": "a@b.test", "password": "x"}).status_code == 404


# ── 2. On fails closed ─────────────────────────────────────────────────────


@pytest.mark.parametrize("path, payload, status", GUARDED)
def test_enabled_with_a_solved_challenge_reaches_the_endpoint(
    client, reached, siteverify, enabled, path, payload, status
):
    response = client.post(path, json=dict(payload, **{"cf-turnstile-response": TOKEN}))

    assert response.status_code == status
    assert len(siteverify.calls) == 1
    sent = siteverify.calls[0]
    assert sent.url == turnstile_service.SITEVERIFY_URL
    assert sent.data == {"secret": SECRET_KEY, "response": TOKEN}
    assert sent.timeout


@pytest.mark.parametrize("path, payload, _status", GUARDED)
@pytest.mark.parametrize("token", [None, "", "   ", 12345, {"nested": "object"}])
def test_enabled_without_a_usable_token_is_refused_before_the_handler(
    client, reached, siteverify, enabled, path, payload, _status, token
):
    body = dict(payload)
    if token is not None:
        body["cf-turnstile-response"] = token

    response = client.post(path, json=body)

    assert response.status_code == 403
    assert response.get_json()["code"] == "turnstile_required"
    assert siteverify.calls == []
    reached.assert_not_called()


@pytest.mark.parametrize("path, payload, _status", GUARDED)
@pytest.mark.parametrize("reply", [
    {"success": False, "error-codes": ["invalid-input-response"]},
    {"success": False, "error-codes": ["timeout-or-duplicate"]},
    {"success": "true"},
    {},
])
def test_enabled_with_a_rejected_token_is_refused_before_the_handler(
    client, reached, siteverify, enabled, path, payload, _status, reply
):
    siteverify.outcome = reply

    response = client.post(path, json=dict(payload, **{"cf-turnstile-response": TOKEN}))

    assert response.status_code == 403
    assert response.get_json()["code"] == "turnstile_failed"
    assert len(siteverify.calls) == 1
    reached.assert_not_called()


@pytest.mark.parametrize("path, payload, _status", GUARDED)
@pytest.mark.parametrize("outcome", [
    requests.exceptions.ConnectTimeout("unreachable"),
    requests.exceptions.ReadTimeout("slow"),
    requests.exceptions.ConnectionError("dns"),
    ValueError("not json"),
])
def test_enabled_but_cloudflare_unreachable_fails_closed_with_503(
    client, reached, siteverify, enabled, path, payload, _status, outcome
):
    siteverify.outcome = outcome

    response = client.post(path, json=dict(payload, **{"cf-turnstile-response": TOKEN}))

    assert response.status_code == 503
    assert response.get_json()["code"] == "turnstile_unavailable"
    reached.assert_not_called()


@pytest.mark.parametrize("status_code", [400, 403, 429, 500, 502])
def test_a_non_ok_siteverify_status_fails_closed(
    client, reached, siteverify, enabled, status_code
):
    siteverify.status_code = status_code

    response = client.post("/api/auth/login", json={
        "email": "a@b.test", "password": "x", "cf-turnstile-response": TOKEN,
    })

    assert response.status_code == 503
    assert response.get_json()["code"] == "turnstile_unavailable"
    reached.assert_not_called()


def test_a_malformed_body_keeps_its_own_failure_while_turnstile_is_off(client, reached):
    """Reading the body to look for a token must not change how a bad one fails."""
    response = client.post(
        "/api/auth/login", data="{not json", content_type="application/json"
    )

    assert response.status_code == 400
    reached.assert_not_called()


def test_a_malformed_body_carries_no_token_so_it_is_refused_when_enabled(
    client, reached, siteverify, enabled
):
    response = client.post(
        "/api/auth/login", data="{not json", content_type="application/json"
    )

    assert response.status_code == 403
    assert response.get_json()["code"] == "turnstile_required"
    assert siteverify.calls == []
    reached.assert_not_called()


# ── 3. Nothing secret leaks ────────────────────────────────────────────────


def test_no_response_or_log_line_carries_the_secret_or_the_token(
    client, reached, siteverify, enabled, caplog
):
    siteverify.outcome = {"success": False, "error-codes": ["invalid-input-secret"]}

    with caplog.at_level(logging.DEBUG):
        refused = client.post("/api/auth/login", json={
            "email": "a@b.test", "password": "x", "cf-turnstile-response": TOKEN,
        })
        siteverify.outcome = requests.exceptions.ConnectionError("dns")
        unavailable = client.post("/api/auth/login", json={
            "email": "a@b.test", "password": "x", "cf-turnstile-response": TOKEN,
        })

    written = caplog.text + refused.get_data(as_text=True) + unavailable.get_data(as_text=True)
    assert SECRET_KEY not in written
    assert TOKEN not in written


def test_config_endpoint_publishes_only_the_site_key(client, enabled):
    response = client.get("/api/auth/turnstile-config")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "success",
        "data": {"site_key": SITE_KEY},
    }
    assert SECRET_KEY not in response.get_data(as_text=True)


def test_config_endpoint_reports_unavailable_while_turnstile_is_off(client):
    response = client.get("/api/auth/turnstile-config")

    assert response.status_code == 503
    assert response.get_json()["status"] == "error"


# ── 4. The widget on the four public pages ─────────────────────────────────

ROOT = Path(__file__).resolve().parents[1]
GUARD_SRC = "assets/js/turnstile-guard.js"
PUBLIC_PAGES = ["login.html", "register.html", "forgot.html", "accept-invite.html"]


def _page(name):
    return (ROOT / "frontend" / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def guard_js():
    return (ROOT / "frontend" / "assets" / "js" / "turnstile-guard.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", PUBLIC_PAGES)
def test_every_public_page_carries_a_widget_slot_and_loads_the_guard(name):
    source = _page(name)

    assert f'<script src="{GUARD_SRC}"></script>' in source
    assert 'class="cf-turnstile"' in source


@pytest.mark.parametrize("name", PUBLIC_PAGES)
def test_no_page_hardcodes_a_key_or_the_cloudflare_script(name):
    """The site key arrives from /api/auth/turnstile-config, like the Google client id."""
    source = _page(name)

    assert "data-sitekey" not in source
    assert "TURNSTILE_SECRET" not in source
    assert "challenges.cloudflare.com" not in source


def test_the_guard_attaches_the_token_to_exactly_the_guarded_endpoints(guard_js):
    for path in ("/api/auth/login", "/api/auth/register",
                 "/api/auth/forgot-password", "/api/invites/accept"):
        assert path in guard_js
    assert "/api/auth/turnstile-config" in guard_js
    # The exact quoted literal, so a rename on either side is caught rather than
    # matching the field name where it only appears in a comment.
    assert f"'{turnstile_service.TOKEN_FIELD}'" in guard_js


def test_the_guard_never_touches_the_verify_endpoint_or_a_secret(guard_js):
    assert turnstile_service.SITEVERIFY_URL not in guard_js
    assert "TURNSTILE_SECRET" not in guard_js
    assert SECRET_KEY not in guard_js


def test_the_guard_does_nothing_until_the_server_says_turnstile_is_on(guard_js):
    """No config, no widget, no fetch wrapper: the pages must work unchanged."""
    assert "site_key" in guard_js
    assert "res.ok" in guard_js or "response.ok" in guard_js
    # Every entry point is wrapped, so a thrown error cannot break a sign-in form.
    assert guard_js.count("catch") >= 4
