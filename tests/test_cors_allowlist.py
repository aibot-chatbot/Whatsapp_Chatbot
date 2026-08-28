"""The CORS allowlist must actually be enforced.

app/__init__.py used to call CORS(origins="*") before load_configurations()
and a second, config-driven CORS() after it. Flask-CORS registers an
after_request hook per call, the wildcard one won, and every response echoed
back whatever Origin the caller sent - so CORS_ORIGINS crash-looped the app
when missing while enforcing nothing when present. These tests fail if a
wildcard registration is ever reintroduced.
"""

import pytest

from app import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_a_foreign_origin_is_not_reflected(client):
    response = client.get("/", headers={"Origin": "https://evil.example.com"})

    assert response.headers.get("Access-Control-Allow-Origin") != "https://evil.example.com"


def test_no_response_carries_a_wildcard_allow_origin(client):
    """A bare "*" would defeat the allowlist just as completely as reflection."""
    response = client.get("/", headers={"Origin": "https://evil.example.com"})

    assert response.headers.get("Access-Control-Allow-Origin") != "*"


def test_a_configured_origin_is_still_allowed(client):
    """The fix must restrict the allowlist, not disable CORS altogether."""
    allowed = create_app().config["CORS_ORIGINS"][0]
    response = client.get("/", headers={"Origin": allowed})

    assert response.headers.get("Access-Control-Allow-Origin") == allowed
