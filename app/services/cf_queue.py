"""Optional Cloudflare Queues transport: publish, pull, ack/retry.

This module moves messages and nothing else. It does not decide what belongs on
a queue, it does not retry, and it does not know what a consumer will do with a
body -- those are the callers' decisions, kept out of here so the fallback path
stays visible where it is chosen rather than buried in a transport.

WHY EVERY FUNCTION RETURNS FALSY INSTEAD OF RAISING. These calls sit in the
inbound customer-message path. A Cloudflare outage, a revoked token or a typo in
a queue id must degrade the feature that uses the queue -- never propagate an
exception into a request handler and take the product down with it. So a failure
is reported as False or [], the reason is logged, and the caller decides between
falling back and dropping the work.

THE SWITCH IS OFF AND IS RE-READ PER CALL. Same reasoning as
app/services/ai_gateway.py and app/services/turnstile_service.py: an operator
must be able to stop queueing by changing a Fly secret, not by shipping a
deploy. enabled() therefore touches the environment on every call and is never
cached. It also refuses to turn on halfway -- the flag alone, without the
account id and the API token, would mean every publish travelled to an address
that cannot authenticate, so a missing credential reads as "off".

BODIES ARE NEVER LOGGED. A message body carries customer message text and
channel identifiers. The logging tests verify that customer text does
not reach logs, and the same rule holds here: failures log the exception type
and the HTTP status, never the body, never the response, never the token.

Operational notes for whoever wires this up:
  - HTTP pull must be enabled on the queue out of band --
    ``wrangler queues consumer http add <queue>`` or the dashboard. It cannot be
    set from a config file and this module cannot turn it on.
  - Delivery is at-least-once and ordering is best-effort. A consumer must be
    idempotent; a lease that expires before ack() is redelivered.
  - A pulled body arrives as it was published and may be base64 encoded, so
    pull() decodes it. A body it cannot read is reported in the batch's
    undecodable_lease_ids rather than dropped -- see LeaseBatch.
  - Publish, pull and ack each bill as one operation ($0.40 per million), so a
    tight poll loop on an idle queue is a real line item.

The account id is R2_ACCOUNT_ID: the queue lives in the same Cloudflare account
as the document-storage bucket, and a second account-id variable would only be
one more thing to set wrong.
"""

import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

import requests

logger = logging.getLogger(__name__)

_API_ROOT = "https://api.cloudflare.com/client/v4/accounts"

#: Cloudflare rejects a message larger than this, so refusing here turns a
#: wasted round trip into an immediate, logged False.
MAX_BODY_BYTES = 128 * 1024

#: One hung call must not pin a gunicorn thread; the machine runs a single
#: worker with eight of them.
DEFAULT_TIMEOUT_SECONDS = 5

#: Cloudflare's own bounds on a pull. A batch_size outside them fails the whole
#: pull, so pull() clamps instead: a caller asking for too much should get the
#: most it can have, not nothing.
MIN_BATCH_SIZE = 1
MAX_BATCH_SIZE = 100

#: Queue ids are opaque Cloudflare identifiers. Anything else is refused rather
#: than interpolated into an authenticated API URL.
_QUEUE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_TRUTHY = ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Lease:
    """One pulled message and the claim on it.

    The claim expires after the pull's visibility timeout, after which the
    message is redelivered to any consumer -- so ``attempts`` can be greater
    than 1 even when nothing failed. It is 1 on first delivery.
    """

    lease_id: str
    body: dict = field(default_factory=dict)
    attempts: int = 1


class LeaseBatch(list):
    """What one pull returned: the usable leases, and the ones it could not read.

    A real ``list`` of ``Lease``, so a caller may treat it exactly as the
    documented ``list[Lease]`` -- iterate it, compare it to ``[]``, index it.
    ``undecodable_lease_ids`` rides alongside because dropping an unreadable
    message silently would leak its lease: nothing acks it, nothing retries it,
    and it reappears on every visibility timeout forever. The caller decides
    whether those ids get a retry with backoff or a dead-letter.

    Every return path from pull() is one of these, including the failures, so
    reading the attribute never raises.
    """

    def __init__(self, leases=(), undecodable_lease_ids=()):
        super().__init__(leases)
        self.undecodable_lease_ids: tuple[str, ...] = tuple(undecodable_lease_ids)


def _account_id() -> str:
    return os.getenv("R2_ACCOUNT_ID", "").strip()


def _api_token() -> str:
    """Never logged, never returned to a caller."""
    return os.getenv("CF_QUEUE_API_TOKEN", "").strip()


def _timeout_seconds() -> float:
    """Seconds to wait for Cloudflare, falling back when the value is nonsense.

    A mistyped secret must not mean "wait forever" or "time out instantly".
    """
    raw = os.getenv("CF_QUEUE_TIMEOUT_SECONDS", "").strip()
    try:
        timeout = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return timeout if timeout > 0 else DEFAULT_TIMEOUT_SECONDS


@lru_cache(maxsize=None)
def _warn_once(message: str) -> None:
    """Log a configuration problem once per process instead of per call."""
    logger.warning(message)


def enabled() -> bool:
    """Whether queue operations should be attempted at all.

    Read from the environment on every call, never cached: an operator must be
    able to switch queueing off without waiting for a deploy.
    """
    if os.getenv("CF_QUEUE_ENABLED", "").strip().lower() not in _TRUTHY:
        return False
    if _account_id() and _api_token():
        return True
    _warn_once(
        "CF_QUEUE_ENABLED is set but R2_ACCOUNT_ID or CF_QUEUE_API_TOKEN is "
        "missing; Cloudflare Queues stays off."
    )
    return False


def _post(queue_id: str, path: str, payload: dict) -> dict | None:
    """POST one Queues request. Returns the parsed envelope, or None on failure.

    The whole call is wrapped because this is the single point where the outside
    world can fail: the caller's contract is that nothing raises past here.
    """
    if not _QUEUE_ID_PATTERN.match(queue_id or ""):
        logger.warning("Cloudflare Queues %s refused: malformed queue id", path or "publish")
        return None

    url = f"{_API_ROOT}/{_account_id()}/queues/{queue_id}/messages{path}"
    try:
        response = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {_api_token()}",
                "Content-Type": "application/json",
            },
            timeout=_timeout_seconds(),
        )
        status = response.status_code
        if not 200 <= status < 300:
            logger.warning("Cloudflare Queues %s returned HTTP %s", path or "publish", status)
            return None
        envelope = response.json()
    except Exception as exc:  # noqa: BLE001 - a transport failure must not escape
        logger.warning("Cloudflare Queues %s failed: %s", path or "publish", type(exc).__name__)
        return None

    if not isinstance(envelope, dict):
        logger.warning("Cloudflare Queues %s returned an unexpected envelope", path or "publish")
        return None
    if envelope.get("success") is False:
        # Cloudflare's error codes name the failure kind; they carry neither the
        # message body nor the token.
        codes = [
            error.get("code")
            for error in envelope.get("errors") or []
            if isinstance(error, dict)
        ]
        logger.warning("Cloudflare Queues %s rejected: %s", path or "publish", codes or "unspecified")
        return None
    return envelope


def send(queue_id: str, body: dict) -> bool:
    """Publish one message. False on any failure, and never raises.

    No retry and no backoff on purpose: the caller owns the fallback, and a
    transport that silently retried would hide how long a request really took.
    """
    if not enabled():
        return False

    try:
        encoded_bytes = len(json.dumps(body).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        logger.warning("Cloudflare Queues publish refused: body is not JSON (%s)", type(exc).__name__)
        return False

    if encoded_bytes >= MAX_BODY_BYTES:
        logger.warning(
            "Cloudflare Queues publish refused: body is %d bytes, limit is %d",
            encoded_bytes,
            MAX_BODY_BYTES,
        )
        return False

    return _post(queue_id, "", {"body": body}) is not None


def pull(queue_id: str, *, batch_size: int, visibility_timeout_ms: int) -> LeaseBatch:
    """Claim up to ``batch_size`` messages. An empty batch on any failure.

    ``batch_size`` is clamped to 1..100 (Cloudflare's range; it defaults to 5
    server-side) -- an out-of-range ask costs the caller a clamp rather than the
    whole pull. ``visibility_timeout_ms`` is how long the claim holds before the
    message is redelivered to any consumer: acknowledge inside that window. It
    defaults to 30 seconds server-side and cannot exceed 12 hours; a value above
    that ceiling is Cloudflare's to reject, not this module's to silently
    rewrite, because shortening a caller's timeout would cause the double
    delivery it was trying to avoid.

    The result is a LeaseBatch: a ``list[Lease]`` that also carries
    ``undecodable_lease_ids`` for messages whose body could not be read. Check
    it -- those leases are still held and need a retry or a dead-letter.
    """
    if not enabled():
        return LeaseBatch()

    envelope = _post(
        queue_id,
        "/pull",
        {
            "visibility_timeout_ms": visibility_timeout_ms,
            "batch_size": min(max(batch_size, MIN_BATCH_SIZE), MAX_BATCH_SIZE),
        },
    )
    if envelope is None:
        return LeaseBatch()

    leases: list[Lease] = []
    undecodable: list[str] = []
    for message in _messages(envelope):
        lease_id = _lease_id(message)
        if lease_id is None:
            continue
        body, failure = _decoded_body(message.get("body"))
        if body is None:
            # The lease id is an opaque Cloudflare token and the failure is a
            # class name; neither carries the customer text in the body.
            logger.warning(
                "Cloudflare Queues pull could not decode the body of lease %s: %s",
                lease_id,
                failure,
            )
            undecodable.append(lease_id)
            continue
        leases.append(Lease(lease_id=lease_id, body=body, attempts=_attempts(message)))

    return LeaseBatch(leases, undecodable)


def _messages(envelope: dict) -> list:
    """The message array out of a pull response."""
    result = envelope.get("result")
    messages = result.get("messages") if isinstance(result, dict) else None
    return messages if isinstance(messages, list) else []


def _lease_id(message) -> str | None:
    """The claim on a pulled message, or None when there is nothing to hold.

    Without a lease id the message can never be acked, so letting it expire and
    be redelivered beats handing the caller a broken claim.
    """
    if not isinstance(message, dict):
        return None
    lease_id = message.get("lease_id")
    if isinstance(lease_id, str) and lease_id:
        return lease_id
    logger.warning("Cloudflare Queues pull returned a message with no lease id")
    return None


def _attempts(message: dict) -> int:
    """Delivery count, 1 on the first. A redelivered message reports more."""
    attempts = message.get("attempts")
    return attempts if isinstance(attempts, int) and attempts > 0 else 1


def _decoded_body(raw) -> tuple[dict | None, str]:
    """A pulled body as a dict, or ``(None, <failure kind>)``.

    Cloudflare returns ``body`` as it was published: already an object when the
    publisher sent JSON, otherwise a string that may be base64 encoded --
    ``metadata["CF-Content-Type"]`` records which, but trying both costs less
    than trusting a field the publisher controls. The failure kind is an
    exception class name, never any part of the body, which carries customer
    message text.
    """
    if isinstance(raw, dict):
        return raw, ""
    if not isinstance(raw, str):
        return None, type(raw).__name__

    failure = "not-a-json-object"
    for decode in (_from_json, _from_base64_json):
        try:
            candidate = decode(raw)
        except (ValueError, TypeError) as exc:
            failure = type(exc).__name__
            continue
        if isinstance(candidate, dict):
            return candidate, ""
    return None, failure


def _from_json(raw: str):
    return json.loads(raw)


def _from_base64_json(raw: str):
    return json.loads(base64.b64decode(raw, validate=True))


def ack(queue_id: str, *, acks: list[str], retries: list[tuple[str, int]]) -> bool:
    """Settle claimed messages: ack these, redeliver those after a delay.

    ``retries`` is a list of ``(lease_id, delay_seconds)``. Both arrays are sent
    on every call -- Cloudflare requires both to be present, empty or not.
    Returns False on any failure, and never raises.
    """
    if not enabled():
        return False

    payload = {
        "acks": [{"lease_id": lease_id} for lease_id in acks],
        "retries": [
            {"lease_id": lease_id, "delay_seconds": delay_seconds}
            for lease_id, delay_seconds in retries
        ],
    }
    return _post(queue_id, "/ack", payload) is not None
