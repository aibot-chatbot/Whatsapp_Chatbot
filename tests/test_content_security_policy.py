import pytest
from flask import Response

from app import create_app
from app.csp_policy import page_csp_header


@pytest.fixture
def process(monkeypatch):
    monkeypatch.setattr("app.load_configurations", lambda app: app.config.update(
        CORS_ORIGINS=[], RATELIMIT_ENABLED=False,
    ))
    monkeypatch.setattr("app.configure_logging", lambda: None)
    monkeypatch.setattr("app.init_sentry", lambda: None)
    monkeypatch.setenv("SENTRY_DSN", "https://example@ingest.example:8443/42")
    app = create_app()
    monkeypatch.delenv("SENTRY_DSN")

    def process_response(path="/page", mimetype="text/html", policy=None):
        with app.test_request_context(path):
            response = Response(mimetype=mimetype)
            if policy is not None:
                response.headers["Content-Security-Policy"] = policy
            return app.process_response(response).headers.get("Content-Security-Policy")

    return process_response


def test_html_receives_an_enforced_page_policy(process):
    policy = process()
    assert policy is not None
    assert policy.startswith("default-src 'self'; script-src 'self' 'unsafe-inline' ")
    assert policy.endswith("frame-ancestors 'none'")


@pytest.mark.parametrize("path,mimetype,policy", [
    ("/api/example", "application/json", None),
    ("/media/page.html", "text/html", "sandbox; default-src 'none'"),
    ("/media/missing.html", "text/html", None),
    ("/widget/example", "text/html", "frame-ancestors https://customer.example"),
    ("/widget/missing/page", "text/html", None),
    ("/page", "text/html", "default-src 'none'"),
])
def test_other_responses_keep_their_original_policy(process, path, mimetype, policy):
    assert process(path, mimetype, policy) == policy


def test_page_uses_only_the_ingest_origin_configured_at_app_creation(process):
    directives = page_csp_header(None).split("; ")
    expected = [
        directive + " https://ingest.example:8443" if directive.startswith("connect-src ") else directive
        for directive in directives
    ]
    assert process() == "; ".join(expected)


@pytest.mark.parametrize("invalid", [
    "http://example@ingest.example/42",
    "https://example@bad host/42",
    "https://example@ingest.example/4'2",
    'https://example@ingest.example/4"2',
    "https://example@ingest.example;other/42",
    "https://example@ingest.example:notaport/42",
    "https://example@ingest.example:99999/42",
    "https://ingest.example/42",
    "https://example@ingest.example/",
    "",
    None,
], ids=["http", "space", "single-quote", "double-quote", "semicolon", "port", "port-range",
        "missing-key", "missing-project", "empty", "unset"])
def test_invalid_dsn_does_not_reuse_a_previous_ingest_origin(invalid):
    baseline = page_csp_header(None)
    configured = page_csp_header("https://example@ingest.example/team/42")
    assert " https://ingest.example;" in configured
    assert page_csp_header(invalid) == baseline
