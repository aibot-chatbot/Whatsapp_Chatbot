import json
import logging

import pytest
import sentry_sdk
from flask import Flask
from sentry_sdk.transport import Transport

from app.observability import init_sentry, scrub_event
from app.utils.api_errors import server_error


class MemoryTransport(Transport):
    def __init__(self, options):
        super().__init__(options)
        self.envelopes = []

    def capture_envelope(self, envelope):
        self.envelopes.append(envelope)


@pytest.fixture
def monitoring(monkeypatch):
    old_client = sentry_sdk.get_client()
    original_init = sentry_sdk.init
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "test")
    monkeypatch.setenv("SENTRY_RELEASE", "test-release")
    monkeypatch.setattr(sentry_sdk, "init", lambda **options: original_init(**options, transport=MemoryTransport))
    init_sentry()
    client = sentry_sdk.get_client()
    yield client
    client.close()
    sentry_sdk.get_global_scope().set_client(old_client)


def test_no_dsn_does_not_initialize(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "")
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: pytest.fail("Reporting should be disabled"))
    init_sentry()


@pytest.mark.parametrize("kind", ["handled", "unhandled", "logged"])
def test_capture_real_sdk_pipeline_without_private_data(monitoring, kind):
    app = Flask(__name__)
    app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
    marker = "private-customer-token@example.test"

    @app.post("/probe/<customer>")
    def probe(customer):
        sentry_sdk.set_user({"email": marker, "id": marker})
        sentry_sdk.set_context("customer", {"message": marker})
        sentry_sdk.set_tag("tenant", marker)
        sentry_sdk.set_extra("password", marker)
        sentry_sdk.add_breadcrumb(message=marker)
        if kind == "logged":
            logging.getLogger(__name__).error("Provider failure %s", marker)
            return {}, 500
        if kind == "unhandled":
            raise ValueError(marker)
        try:
            raise ValueError(marker)
        except ValueError as exc:
            return server_error("probe", exc)

    response = app.test_client().post(
        "/probe/" + marker + "?token=" + marker,
        json={"message": marker},
        headers={"Authorization": "Bearer " + marker, "Cookie": "session=" + marker},
    )
    assert response.status_code == 500
    sentry_sdk.flush()
    events = [item.get_event() for envelope in monitoring.transport.envelopes
              for item in envelope.items if item.headers.get("type") == "event"]
    assert len(events) == 1, "A failure must produce exactly one event"
    event = events[0]
    assert event["transaction"] == "/probe/<customer>"
    assert event["release"] == "test-release"
    assert event["environment"] == "test"
    assert marker not in b"".join(envelope.serialize() for envelope in monitoring.transport.envelopes).decode()
    assert "request" not in event and "user" not in event
    if kind != "logged":
        assert event["exception"]["values"][0]["type"] == "ValueError"
    assert "test_observability.py" in json.dumps(event)
    assert not ({"openai", "httpx", "supabase", "requests"} & monitoring.integrations.keys())


def test_background_error_is_captured(monitoring):
    logging.getLogger(__name__).error("worker failed with private-worker-secret")
    sentry_sdk.flush()
    payload = b"".join(e.serialize() for e in monitoring.transport.envelopes).decode()
    assert "Server error" in payload
    assert "private-worker-secret" not in payload


def test_scrubber_drops_unknown_fields_and_source_content():
    event = {
        "future_sdk_field": "private-marker",
        "exception": {"values": [{"type": "ValueError", "value": "private-marker",
            "stacktrace": {"frames": [{"filename": "handler.py", "lineno": 42,
                "context_line": "private-marker", "vars": {"token": "private-marker"}}]}}]},
    }
    safe = scrub_event(event, {})
    assert "private-marker" not in json.dumps(safe)
    assert safe["exception"]["values"][0]["stacktrace"]["frames"][0]["lineno"] == 42
