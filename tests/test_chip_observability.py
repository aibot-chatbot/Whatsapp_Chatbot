"""Exercise CHIP diagnostics through the real SDK without network or private data."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
import sentry_sdk
from flask import Flask
from sentry_sdk.transport import Transport

from app import observability
from app.observability import capture_payment_failure, init_sentry, scrub_event


class MemoryTransport(Transport):
    def __init__(self, options):
        super().__init__(options)
        self.envelopes = []

    def capture_envelope(self, envelope):
        self.envelopes.append(envelope)


@pytest.fixture
def monitoring(monkeypatch):
    monkeypatch.setattr(observability, "_NEXT_WEBHOOK_REPORT_AT", 0.0)
    old_client = sentry_sdk.get_client()
    original_init = sentry_sdk.init
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "test")
    monkeypatch.setenv("SENTRY_RELEASE", "chip-test-release")
    monkeypatch.setattr(sentry_sdk, "init", lambda **options: original_init(**options, transport=MemoryTransport))
    init_sentry()
    client = sentry_sdk.get_client()
    yield client
    client.close()
    sentry_sdk.get_global_scope().set_client(old_client)


@pytest.mark.parametrize("with_exception", [True, False])
@pytest.mark.parametrize("reason", ["mismatch", "status_review"])
def test_chip_failure_has_searchable_tags_without_payment_data(monitoring, with_exception, reason):
    marker = "private-payment-token@example.test"
    app = Flask(__name__)

    @app.post("/api/billing/chip/webhook")
    def webhook():
        sentry_sdk.set_user({"email": marker})
        sentry_sdk.set_context("payment", {"purchase_id": marker})
        sentry_sdk.set_tag("tenant", marker)
        sentry_sdk.set_extra("api_key", marker)
        exc = None
        if with_exception:
            try:
                raise ValueError(marker)
            except ValueError as caught:
                exc = caught
        event_id = capture_payment_failure("webhook", reason=reason, mode="test", exc=exc)
        assert event_id
        return {}, 500

    response = app.test_client().post(
        "/api/billing/chip/webhook?token=" + marker,
        json={"email": marker, "purchase_id": marker},
        headers={"Authorization": "Bearer " + marker, "X-Signature": marker},
    )
    assert response.status_code == 500
    # A later event in the same execution must not inherit payment diagnostics.
    sentry_sdk.capture_message("Unrelated error", level="error")
    sentry_sdk.flush()
    events = [item.get_event() for envelope in monitoring.transport.envelopes
              for item in envelope.items if item.headers.get("type") == "event"]
    assert len(events) == 2
    event = events[0]
    assert event["tags"] == {
        "payment.gateway": "chip", "payment.operation": "webhook",
        "payment.reason": reason, "payment.mode": "test",
    }
    assert event["release"] == "chip-test-release"
    assert event["transaction"] == "/api/billing/chip/webhook"
    assert "tags" not in events[1]
    assert marker not in b"".join(envelope.serialize() for envelope in monitoring.transport.envelopes).decode()
    assert not ({"request", "user", "extra", "contexts", "breadcrumbs"} & event.keys())
    if with_exception:
        assert event["exception"]["values"][0]["type"] == "ValueError"
        assert "test_chip_observability.py" in json.dumps(event)


def test_unknown_payment_labels_cannot_leak_secrets(monitoring):
    marker = "private-payment-token@example.test"
    capture_payment_failure(marker, reason=marker, mode=marker)
    sentry_sdk.flush()
    events = [item.get_event() for envelope in monitoring.transport.envelopes
              for item in envelope.items if item.headers.get("type") == "event"]
    assert events[0]["tags"] == {
        "payment.gateway": "chip", "payment.operation": "unknown",
        "payment.reason": "unexpected", "payment.mode": "unknown",
    }
    assert marker not in b"".join(envelope.serialize() for envelope in monitoring.transport.envelopes).decode()
    safe = scrub_event({"tags": {"payment.gateway": "chip", "payment.reason": marker, "api_key": marker}}, {})
    assert safe["tags"] == {"payment.gateway": "chip"}


def test_reporting_failure_does_not_break_payment(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("Sentry unavailable")

    monkeypatch.setattr(sentry_sdk, "capture_message", unavailable)
    assert capture_payment_failure("fulfillment", reason="persistence") is None


def test_webhook_report_budget_bounds_concurrent_requests_without_hiding_fulfillment(monitoring, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(observability, "monotonic", lambda: clock[0])

    def invalid_callback(_):
        return capture_payment_failure("webhook", reason="invalid_signature", mode="test")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(invalid_callback, range(32)))
    assert sum(result is not None for result in results) == 1
    # Other anonymous error paths share the budget; paid processing remains visible.
    assert capture_payment_failure("webhook", reason="configuration", mode="test") is None
    assert capture_payment_failure("fulfillment", reason="persistence", mode="test")
    clock[0] = 159.9
    assert invalid_callback(None) is None
    clock[0] = 160.0
    assert invalid_callback(None)
    sentry_sdk.flush()
    events = [item.get_event() for envelope in monitoring.transport.envelopes
              for item in envelope.items if item.headers.get("type") == "event"]
    assert [event["tags"]["payment.operation"] for event in events] == [
        "webhook", "fulfillment", "webhook",
    ]
