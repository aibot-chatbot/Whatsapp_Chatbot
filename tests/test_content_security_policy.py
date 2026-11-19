import base64
import hashlib
import json
from pathlib import Path

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

    def process_response(path="/page", mimetype="text/html", policy=None, report_only=None):
        with app.test_request_context(path):
            response = Response(mimetype=mimetype)
            if policy is not None:
                response.headers["Content-Security-Policy"] = policy
            if report_only is not None:
                response.headers["Content-Security-Policy-Report-Only"] = report_only
            return app.process_response(response).headers

    return process_response


def test_html_receives_an_enforced_page_policy(process):
    policy = process().get("Content-Security-Policy")
    assert policy is not None
    assert policy.startswith("default-src 'self'; script-src 'self' 'unsafe-inline' ")
    assert policy.endswith("frame-ancestors 'none'")


def test_html_reports_against_exact_script_sources_and_handler_hashes(process):
    headers = process()
    report_only = headers.get("Content-Security-Policy-Report-Only")
    assert report_only is not None
    # SHA-256 of the exact UTF-8 attribute value openCreateModal().
    assert "'sha256-8dWlFqTlofyASXwerZBU5mdaSRoMNrkaWdfAt5sIvzA='" in report_only.split()
    assert "'unsafe-inline'" not in report_only
    baseline = next(
        directive for directive in headers["Content-Security-Policy"].split("; ")
        if directive.startswith("script-src ")
    )
    manifest = Path(__file__).parents[1] / "app/csp_inline_handlers.json"
    handlers = json.loads(manifest.read_text(encoding="utf-8"))
    hashes = [
        base64.b64encode(hashlib.sha256(handler.encode("utf-8")).digest()).decode("ascii")
        for handler in handlers
    ]
    assert report_only.split() == [
        *(source for source in baseline.split() if source != "'unsafe-inline'"),
        "'unsafe-hashes'", *(f"'sha256-{digest}'" for digest in hashes),
    ]


@pytest.mark.parametrize("path,mimetype,policy", [
    ("/api/example", "application/json", None),
    ("/media/page.html", "text/html", "sandbox; default-src 'none'"),
    ("/media/missing.html", "text/html", None),
    ("/widget/example", "text/html", "frame-ancestors https://customer.example"),
    ("/widget/missing/page", "text/html", None),
    ("/chat/example", "text/html", "frame-ancestors https://customer.example"),
    ("/api/widget/example", "text/html", None),
    ("/widget.js", "text/html", "frame-ancestors *"),
])
def test_other_responses_keep_their_original_policy(process, path, mimetype, policy):
    headers = process(path, mimetype, policy)
    assert headers.get("Content-Security-Policy") == policy
    assert "Content-Security-Policy-Report-Only" not in headers


def test_page_keeps_existing_policies(process):
    headers = process(policy="default-src 'none'", report_only="script-src 'none'")
    assert headers.get("Content-Security-Policy") == "default-src 'none'"
    assert headers.get("Content-Security-Policy-Report-Only") == "script-src 'none'"


def test_page_uses_only_the_ingest_origin_configured_at_app_creation(process):
    directives = page_csp_header(None).split("; ")
    expected = [
        directive + " https://ingest.example:8443" if directive.startswith("connect-src ") else directive
        for directive in directives
    ]
    assert process()["Content-Security-Policy"] == "; ".join(expected)


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
