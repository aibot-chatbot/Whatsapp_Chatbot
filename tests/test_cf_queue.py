"""Tests for the Cloudflare Queues transport.

This module sits in the inbound customer-message path, so the cases that matter
most are the ones where a naive implementation would take the product down: the
switch defaulting to on, a half-configured queue being treated as usable, a
Cloudflare outage raising into a request handler, or an oversize payload being
sent to be rejected at the far end. One test also pins the logging rule -- a
message body carries customer text and must never reach a log line.

No test here performs real network I/O: an autouse fixture replaces
``requests.post`` with a tripwire that fails the test if anything calls it
without saying so first.
"""

import base64
import json

import pytest

from app.services import cf_queue


ACCOUNT_ID = "synthetic-cloudflare-account-id"
QUEUE_ID = "synthetic-queue-id"
API_TOKEN = "synthetic-cf-queue-token"

MESSAGES_URL = (
    f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}"
    f"/queues/{QUEUE_ID}/messages"
)


class _Response:
    """The parts of ``requests.Response`` this module actually touches."""

    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"success": True, "result": {}}

    def json(self):
        if self._payload is _UNPARSEABLE:
            raise ValueError("response body is not JSON")
        return self._payload


_UNPARSEABLE = object()


class _Recorder:
    """Stands in for ``requests.post`` and remembers how it was called."""

    def __init__(self, response=None, error=None):
        self.calls = []
        self._response = response if response is not None else _Response()
        self._error = error

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self._error is not None:
            raise self._error
        return self._response

    @property
    def only_call(self):
        assert len(self.calls) == 1, f"expected exactly one HTTP call, got {len(self.calls)}"
        return self.calls[0]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Unconfigured environment, and a tripwire in place of the network."""
    for name in (
        "CF_QUEUE_ENABLED",
        "CF_QUEUE_API_TOKEN",
        "CF_QUEUE_TIMEOUT_SECONDS",
        "R2_ACCOUNT_ID",
    ):
        monkeypatch.delenv(name, raising=False)

    def _tripwire(*args, **kwargs):
        raise AssertionError("the test made a real HTTP call")

    monkeypatch.setattr(cf_queue.requests, "post", _tripwire)
    yield


def _configure(monkeypatch, **overrides):
    monkeypatch.setenv("CF_QUEUE_ENABLED", "true")
    monkeypatch.setenv("CF_QUEUE_API_TOKEN", API_TOKEN)
    monkeypatch.setenv("R2_ACCOUNT_ID", ACCOUNT_ID)
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)


def _install(monkeypatch, recorder):
    monkeypatch.setattr(cf_queue.requests, "post", recorder)
    return recorder


def _pull_response(*messages):
    """A pull response in Cloudflare's documented envelope shape."""
    return _Response(payload={"success": True, "result": {"messages": list(messages)}})


# ── the switch ────────────────────────────────────────────────────────────


def test_disabled_by_default_and_nothing_reaches_the_network(monkeypatch):
    monkeypatch.setenv("R2_ACCOUNT_ID", ACCOUNT_ID)
    monkeypatch.setenv("CF_QUEUE_API_TOKEN", API_TOKEN)

    assert cf_queue.enabled() is False
    assert cf_queue.send(QUEUE_ID, {"hello": "world"}) is False
    assert cf_queue.pull(QUEUE_ID, batch_size=10, visibility_timeout_ms=30_000) == []
    assert cf_queue.ack(QUEUE_ID, acks=["lease-1"], retries=[]) is False


def test_enabled_without_a_token_is_treated_as_disabled(monkeypatch):
    monkeypatch.setenv("CF_QUEUE_ENABLED", "true")
    monkeypatch.setenv("R2_ACCOUNT_ID", ACCOUNT_ID)

    assert cf_queue.enabled() is False
    assert cf_queue.send(QUEUE_ID, {"hello": "world"}) is False


def test_enabled_without_an_account_id_is_treated_as_disabled(monkeypatch):
    monkeypatch.setenv("CF_QUEUE_ENABLED", "true")
    monkeypatch.setenv("CF_QUEUE_API_TOKEN", API_TOKEN)

    assert cf_queue.enabled() is False
    assert cf_queue.send(QUEUE_ID, {"hello": "world"}) is False


def test_the_flag_is_re_read_on_every_call(monkeypatch):
    _configure(monkeypatch)
    assert cf_queue.enabled() is True

    monkeypatch.setenv("CF_QUEUE_ENABLED", "false")
    assert cf_queue.enabled() is False, "the kill switch must not need a redeploy"


# ── send ──────────────────────────────────────────────────────────────────


def test_send_posts_the_documented_shape_to_the_documented_url(monkeypatch):
    _configure(monkeypatch)
    recorder = _install(monkeypatch, _Recorder())

    assert cf_queue.send(QUEUE_ID, {"channel": "whatsapp", "id": 7}) is True

    url, kwargs = recorder.only_call
    assert url == MESSAGES_URL
    assert kwargs["json"] == {"body": {"channel": "whatsapp", "id": 7}}
    assert kwargs["headers"]["Authorization"] == f"Bearer {API_TOKEN}"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["timeout"] == cf_queue.DEFAULT_TIMEOUT_SECONDS


def test_send_returns_false_on_http_500(monkeypatch):
    _configure(monkeypatch)
    _install(monkeypatch, _Recorder(response=_Response(status_code=500)))

    assert cf_queue.send(QUEUE_ID, {"hello": "world"}) is False


def test_send_returns_false_on_timeout_and_raises_nothing(monkeypatch):
    _configure(monkeypatch)
    _install(monkeypatch, _Recorder(error=cf_queue.requests.Timeout("timed out")))

    assert cf_queue.send(QUEUE_ID, {"hello": "world"}) is False


def test_send_returns_false_when_cloudflare_reports_failure_with_http_200(monkeypatch):
    _configure(monkeypatch)
    _install(
        monkeypatch,
        _Recorder(response=_Response(payload={"success": False, "errors": [{"code": 10000}]})),
    )

    assert cf_queue.send(QUEUE_ID, {"hello": "world"}) is False


def test_send_refuses_an_oversize_body_before_any_network_call(monkeypatch):
    _configure(monkeypatch)
    recorder = _install(monkeypatch, _Recorder())

    oversize = {"text": "x" * cf_queue.MAX_BODY_BYTES}
    assert len(json.dumps(oversize).encode("utf-8")) >= cf_queue.MAX_BODY_BYTES

    assert cf_queue.send(QUEUE_ID, oversize) is False
    assert recorder.calls == [], "an oversize body must not be put on the wire"


def test_send_refuses_a_body_that_cannot_be_serialised(monkeypatch):
    _configure(monkeypatch)
    recorder = _install(monkeypatch, _Recorder())

    assert cf_queue.send(QUEUE_ID, {"when": object()}) is False
    assert recorder.calls == []


def test_a_failure_logs_the_type_and_status_never_the_body_or_token(monkeypatch, caplog):
    _configure(monkeypatch)
    _install(monkeypatch, _Recorder(response=_Response(status_code=500)))

    with caplog.at_level("WARNING"):
        assert cf_queue.send(QUEUE_ID, {"text": "CUSTOMER-MESSAGE-TEXT"}) is False

    assert "500" in caplog.text
    assert "CUSTOMER-MESSAGE-TEXT" not in caplog.text
    assert API_TOKEN not in caplog.text


# ── pull ──────────────────────────────────────────────────────────────────


def test_pull_posts_the_documented_shape_and_maps_the_response(monkeypatch):
    _configure(monkeypatch)
    recorder = _install(
        monkeypatch,
        _Recorder(
            response=_Response(
                payload={
                    "success": True,
                    "result": {
                        "messages": [
                            {
                                "lease_id": "lease-a",
                                "body": {"channel": "whatsapp"},
                                "attempts": 1,
                            },
                            {
                                "lease_id": "lease-b",
                                "body": {"channel": "telegram"},
                                "attempts": 3,
                            },
                        ]
                    },
                }
            )
        ),
    )

    leases = cf_queue.pull(QUEUE_ID, batch_size=5, visibility_timeout_ms=30_000)

    url, kwargs = recorder.only_call
    assert url == f"{MESSAGES_URL}/pull"
    assert kwargs["json"] == {"visibility_timeout_ms": 30_000, "batch_size": 5}

    assert leases == [
        cf_queue.Lease(lease_id="lease-a", body={"channel": "whatsapp"}, attempts=1),
        cf_queue.Lease(lease_id="lease-b", body={"channel": "telegram"}, attempts=3),
    ]


def test_pull_defaults_attempts_to_one_on_first_delivery(monkeypatch):
    _configure(monkeypatch)
    _install(
        monkeypatch,
        _Recorder(
            response=_Response(
                payload={
                    "success": True,
                    "result": {"messages": [{"lease_id": "lease-a", "body": {}}]},
                }
            )
        ),
    )

    assert cf_queue.pull(QUEUE_ID, batch_size=1, visibility_timeout_ms=1000) == [
        cf_queue.Lease(lease_id="lease-a", body={}, attempts=1)
    ]


def test_pull_skips_a_message_with_no_lease_id(monkeypatch):
    _configure(monkeypatch)
    _install(
        monkeypatch,
        _Recorder(
            response=_Response(
                payload={
                    "success": True,
                    "result": {
                        "messages": [
                            {"body": {"orphan": True}},
                            {"lease_id": "lease-a", "body": {"channel": "whatsapp"}},
                        ]
                    },
                }
            )
        ),
    )

    leases = cf_queue.pull(QUEUE_ID, batch_size=2, visibility_timeout_ms=1000)
    assert [lease.lease_id for lease in leases] == ["lease-a"]
    # There is no lease to surface for the orphan: nothing can ever ack it.
    assert leases.undecodable_lease_ids == ()


def test_pull_treats_a_missing_body_as_undecodable_not_as_empty(monkeypatch):
    """Cloudflare always sends ``body``; its absence means the message is broken.

    Fabricating ``{}`` would hand the consumer a message that looks empty rather
    than unreadable, and the lease would be acked on the strength of a guess.
    """
    _configure(monkeypatch)
    _install(monkeypatch, _Recorder(response=_pull_response({"lease_id": "lease-a"})))

    leases = cf_queue.pull(QUEUE_ID, batch_size=1, visibility_timeout_ms=1000)

    assert leases == []
    assert leases.undecodable_lease_ids == ("lease-a",)


def test_pull_returns_empty_on_timeout_and_raises_nothing(monkeypatch):
    _configure(monkeypatch)
    _install(monkeypatch, _Recorder(error=cf_queue.requests.Timeout("timed out")))

    assert cf_queue.pull(QUEUE_ID, batch_size=5, visibility_timeout_ms=30_000) == []


def test_pull_returns_empty_on_an_unparseable_response(monkeypatch):
    _configure(monkeypatch)
    _install(monkeypatch, _Recorder(response=_Response(payload=_UNPARSEABLE)))

    assert cf_queue.pull(QUEUE_ID, batch_size=5, visibility_timeout_ms=30_000) == []


def test_pull_decodes_a_json_string_body(monkeypatch):
    """Cloudflare returns ``body`` as it was published, which may be a string."""
    _configure(monkeypatch)
    _install(
        monkeypatch,
        _Recorder(
            response=_pull_response(
                {"lease_id": "lease-a", "body": json.dumps({"channel": "whatsapp"}), "attempts": 1}
            )
        ),
    )

    assert cf_queue.pull(QUEUE_ID, batch_size=1, visibility_timeout_ms=1000) == [
        cf_queue.Lease(lease_id="lease-a", body={"channel": "whatsapp"}, attempts=1)
    ]


def test_pull_decodes_a_base64_encoded_json_body(monkeypatch):
    """The docs warn the body may be base64 depending on how it was published."""
    _configure(monkeypatch)
    encoded = base64.b64encode(json.dumps({"channel": "telegram"}).encode("utf-8")).decode("ascii")
    _install(
        monkeypatch,
        _Recorder(response=_pull_response({"lease_id": "lease-b", "body": encoded, "attempts": 2})),
    )

    assert cf_queue.pull(QUEUE_ID, batch_size=1, visibility_timeout_ms=1000) == [
        cf_queue.Lease(lease_id="lease-b", body={"channel": "telegram"}, attempts=2)
    ]


def test_pull_skips_an_undecodable_body_and_surfaces_its_lease_id(monkeypatch, caplog):
    """An undecodable message must not crash the pull, nor vanish silently.

    Dropping it without telling the caller would leak the lease: nothing acks
    it, nothing retries it, and it reappears every visibility timeout forever.
    """
    _configure(monkeypatch)
    _install(
        monkeypatch,
        _Recorder(
            response=_pull_response(
                {"lease_id": "lease-bad", "body": "CUSTOMER-MESSAGE-TEXT"},
                {"lease_id": "lease-good", "body": {"channel": "whatsapp"}},
            )
        ),
    )

    with caplog.at_level("WARNING"):
        leases = cf_queue.pull(QUEUE_ID, batch_size=2, visibility_timeout_ms=1000)

    assert [lease.lease_id for lease in leases] == ["lease-good"]
    assert leases.undecodable_lease_ids == ("lease-bad",)
    assert "lease-bad" in caplog.text
    assert "CUSTOMER-MESSAGE-TEXT" not in caplog.text


def test_every_pull_result_exposes_undecodable_lease_ids(monkeypatch):
    """The failure paths carry the attribute too, or a caller's check raises."""
    _configure(monkeypatch)
    _install(monkeypatch, _Recorder(error=cf_queue.requests.Timeout("timed out")))
    failed = cf_queue.pull(QUEUE_ID, batch_size=1, visibility_timeout_ms=1000)
    assert failed == [] and failed.undecodable_lease_ids == ()

    monkeypatch.setenv("CF_QUEUE_ENABLED", "false")
    disabled = cf_queue.pull(QUEUE_ID, batch_size=1, visibility_timeout_ms=1000)
    assert disabled == [] and disabled.undecodable_lease_ids == ()


@pytest.mark.parametrize(
    "requested, posted",
    [(0, 1), (-5, 1), (1, 1), (5, 5), (100, 100), (500, 100)],
)
def test_pull_clamps_batch_size_into_the_supported_range(monkeypatch, requested, posted):
    """Out of range must cost the caller a clamp, not the whole pull."""
    _configure(monkeypatch)
    recorder = _install(monkeypatch, _Recorder(response=_pull_response()))

    cf_queue.pull(QUEUE_ID, batch_size=requested, visibility_timeout_ms=1000)

    assert recorder.only_call[1]["json"]["batch_size"] == posted


# ── ack ───────────────────────────────────────────────────────────────────


def test_ack_posts_both_arrays(monkeypatch):
    _configure(monkeypatch)
    recorder = _install(monkeypatch, _Recorder())

    assert cf_queue.ack(QUEUE_ID, acks=["lease-a"], retries=[("lease-b", 600)]) is True

    url, kwargs = recorder.only_call
    assert url == f"{MESSAGES_URL}/ack"
    assert kwargs["json"] == {
        "acks": [{"lease_id": "lease-a"}],
        "retries": [{"lease_id": "lease-b", "delay_seconds": 600}],
    }


def test_ack_sends_an_empty_retries_array_when_there_are_no_retries(monkeypatch):
    _configure(monkeypatch)
    recorder = _install(monkeypatch, _Recorder())

    assert cf_queue.ack(QUEUE_ID, acks=["lease-a"], retries=[]) is True

    _, kwargs = recorder.only_call
    assert kwargs["json"]["retries"] == [], "Cloudflare requires both arrays to be present"


def test_ack_returns_false_on_http_500(monkeypatch):
    _configure(monkeypatch)
    _install(monkeypatch, _Recorder(response=_Response(status_code=500)))

    assert cf_queue.ack(QUEUE_ID, acks=["lease-a"], retries=[]) is False


# ── the url is built from trusted parts only ──────────────────────────────


def test_a_queue_id_that_could_reshape_the_url_is_refused(monkeypatch):
    _configure(monkeypatch)
    recorder = _install(monkeypatch, _Recorder())

    assert cf_queue.send("../../user/tokens", {"hello": "world"}) is False
    assert recorder.calls == []


# ── the timeout ───────────────────────────────────────────────────────────


def test_the_timeout_is_configurable_and_falls_back_when_nonsense(monkeypatch):
    _configure(monkeypatch, CF_QUEUE_TIMEOUT_SECONDS="12")
    recorder = _install(monkeypatch, _Recorder())
    cf_queue.send(QUEUE_ID, {"hello": "world"})
    assert recorder.only_call[1]["timeout"] == 12

    monkeypatch.setenv("CF_QUEUE_TIMEOUT_SECONDS", "not-a-number")
    recorder = _install(monkeypatch, _Recorder())
    cf_queue.send(QUEUE_ID, {"hello": "world"})
    assert recorder.only_call[1]["timeout"] == cf_queue.DEFAULT_TIMEOUT_SECONDS
