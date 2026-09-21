"""Optional Cloudflare Queue transport for the document ingest.

``knowledge_ingest_job_service`` runs an ingest on a daemon thread, which is
the right shape for a single machine and stays the default. What a thread
cannot do is survive its process: a deploy in the middle of a two-to-eight
minute pipeline loses the work, and the upload is stranded at ``processing``
with no record of why. Publishing the job to a Cloudflare Queue instead makes
the *waiting* durable -- the message outlives the deploy and is delivered to
whatever process comes back.

**Flag-gated and off by default.** ``INGEST_QUEUE_ENABLED`` plus
``CF_QUEUE_INGEST_ID``, on top of the switches ``cf_queue`` already reads. With
the flag off, :func:`publish` returns False before it touches anything and
``start_pdf_ingest`` runs exactly the code it ran before this module existed.
Same reasoning as ``ai_gateway`` and ``turnstile_service``: the environment is
re-read per call so an operator can switch the transport off with a Fly secret
rather than a deploy.

**THE HAZARD: at-least-once delivery meets per-chunk billing.** Cloudflare
delivers a message at least once and orders it only on a best-effort basis, and
``extract_and_store_graph_supabase`` makes one billed LLM call *per chunk*. A
redelivered message that re-ran the pipeline would bill the tenant a second
time for one document. Two things stop that here, in this order:

1. **The claim, which is the decision.** Before any billed work,
   :func:`_claim` moves ``knowledge_files.processing_status`` from
   ``processing`` to ``ingesting`` with the old value as the predicate, so the
   update matches no row if anyone got there first. A delivery that loses the
   claim acknowledges and runs nothing. This is what makes duplicates safe.
2. **The visibility timeout, which only buys time.** It is set well past the
   worst-case pipeline so a redelivery is rare rather than routine -- see
   :data:`VISIBILITY_TIMEOUT_MS`. A timeout is a race that is eventually lost;
   the claim is not.

**What is NOT deferred, and has not moved.** ``verify_chatbot_access`` and the
billing gates run on the request thread before the file is accepted, exactly as
before. Nothing that reaches this module was ever un-authorised, and no part of
this path re-checks or relaxes them.

ponytail: a process that dies *after* claiming leaves the row at ``ingesting``,
and the redelivery acknowledges rather than re-running -- because from here a
crashed run and a duplicate ack look identical, and guessing wrong costs the
tenant a second bill. That is the same visible outcome as today's daemon thread
dying, one word different. The upgrade path is a claim timestamp
(``knowledge_files.ingest_claimed_at``) so a stale claim can be re-offered,
which needs a migration this change deliberately does not carry.

Bodies are never logged. A job descriptor names a tenant's document; failures
log the exception type and nothing else, the same rule ``cf_queue`` and
``webhook_worker`` hold.
"""

from __future__ import annotations

import logging
import os
import threading
from functools import lru_cache
from typing import Any, Final

from app.services import cf_queue

logger = logging.getLogger(__name__)

#: How long a pulled message stays invisible to other pulls.
#:
#: The pipeline is two to eight minutes for a scanned document
#: (``knowledge_ingest_job_service`` module docstring), almost all of it the
#: per-chunk graph extraction. Thirty minutes is roughly four times the
#: documented worst case, which covers a slow day at the model provider or a
#: retrying HTTP client without being near Cloudflare's twelve-hour ceiling.
#: Generosity is cheap here precisely because the claim -- not this number --
#: is what stops a duplicate: an over-long timeout only delays the redelivery
#: after a genuine crash, while an under-long one guarantees a redelivery
#: *during* every large upload.
VISIBILITY_TIMEOUT_MS: Final[int] = 30 * 60 * 1000

#: One message per pull. There is one consumer thread and each message occupies
#: it for minutes, so a larger batch would hold the extra leases idle until
#: their claim expired -- turning one slow upload into several redeliveries.
BATCH_SIZE: Final[int] = 1

#: Deliveries allowed before the ingest is recorded as failed instead of tried
#: again. Each attempt can cost a full billed pipeline, so the budget is small:
#: two transient failures are a bad minute, three are a broken document.
MAX_INGEST_ATTEMPTS: Final[int] = 3

#: Delay asked for when a delivery could not even be claimed. Long enough for a
#: brief Supabase outage to pass, short enough that the client's poll still
#: resolves within a few minutes.
RETRY_DELAY_SECONDS: Final[int] = 60

#: Idle poll interval. Cloudflare's HTTP pull is short polling -- it answers
#: immediately with whatever is there -- so the loop has to set its own pace.
#: At $0.40 per million operations a twenty-second poll is a few cents a year;
#: a publish wakes the loop immediately, so this is the empty-queue cadence and
#: not the latency an upload actually sees.
POLL_INTERVAL_SECONDS: Final[int] = 20

#: Exactly the keys ``process_uploaded_pdf`` reads. Ids, names and relative
#: paths -- never the document, which is already in R2 and in ``knowledge_files``
#: and would blow the 128 KB message limit besides.
_DESCRIPTOR_FIELDS: Final[tuple[str, ...]] = (
    "chatbot_id",
    "file_id",
    "filepath",
    "file_name",
    "original_file_name",
    "relative_pdf_path",
    "target_role",
)

_TRUTHY = ("1", "true", "yes", "on")

_wake = threading.Event()
_start_lock = threading.Lock()
_started = False


@lru_cache(maxsize=None)
def _warn_once(message: str) -> None:
    """Log a configuration problem once per process instead of per upload."""
    logger.warning(message)


def _queue_id() -> str:
    return os.getenv("CF_QUEUE_INGEST_ID", "").strip()


def enabled() -> bool:
    """Whether an accepted upload should be published instead of threaded.

    Read from the environment on every call, never cached, and refusing to turn
    on halfway: without the queue id or without ``cf_queue`` itself configured,
    every publish would fail and every upload would take the fallback anyway.
    """
    if os.getenv("INGEST_QUEUE_ENABLED", "").strip().lower() not in _TRUTHY:
        return False
    if not _queue_id():
        _warn_once(
            "INGEST_QUEUE_ENABLED is set but CF_QUEUE_INGEST_ID is missing; "
            "document ingest stays on the in-process thread."
        )
        return False
    if not cf_queue.enabled():
        _warn_once(
            "INGEST_QUEUE_ENABLED is set but Cloudflare Queues is not "
            "configured; document ingest stays on the in-process thread."
        )
        return False
    return True


def _descriptor(accepted: dict) -> dict:
    """The job as it travels: ids, names and relative paths only."""
    return {field: accepted[field] for field in _DESCRIPTOR_FIELDS}


def publish(accepted: dict) -> bool:
    """Hand one accepted upload to the queue. False means "run it here".

    Never raises. A Cloudflare outage, a revoked token or a malformed
    descriptor must degrade to the in-process thread -- a paid customer's
    upload is not something to drop because a transport is unavailable.
    """
    if not enabled():
        return False

    try:
        body = _descriptor(accepted)
        # Started before the publish, not after: this is also the process that
        # has to pick up whatever a previous deploy left sitting in the queue.
        _ensure_started()
        if not cf_queue.send(_queue_id(), body):
            return False
    except Exception as exc:  # noqa: BLE001 - the fallback is the whole point
        logger.warning(
            "[IngestQueue] Publishing an ingest failed, running it in-process (%s)",
            type(exc).__name__,
        )
        return False

    _wake.set()
    return True


# ── The durable claim ─────────────────────────────────────────────────────


def _transition(chatbot_id: int, file_id: int, *, expected: str, new: str) -> bool:
    """Move one row's ``processing_status``, but only from ``expected``.

    True only when this caller made the change. The predicate is what turns an
    update into a claim: two deliveries racing the same row leave exactly one
    winner, the same shape as ``claim_queued_automation_events`` and
    ``claim_telegram_channel_operation``.

    ponytail: the conditional update is written here rather than in
    ``app/database/knowledge_file_repository.py`` because
    ``update_knowledge_file_status`` cannot express a predicate and returns
    ``result.data[0]``, which raises on the "someone else won" case this
    depends on. ``knowledge_service`` and ``rag_service`` already reach for the
    client this way. Moving it into the repository is the tidier home and
    belongs with whoever owns that file.
    """
    from app.database.db import supabase

    result = (
        supabase.table("knowledge_files")
        .update({"processing_status": new})
        .eq("id", int(file_id))
        .eq("chatbot_id", int(chatbot_id))
        .eq("processing_status", expected)
        .execute()
    )
    return bool(result.data)


def _claim(chatbot_id: int, file_id: int) -> bool:
    """Take ownership of one ingest. False means someone already has it.

    The gate on every billed call in this path. A row that has moved on to
    ``ingesting``, ``completed`` or ``failed`` is not claimable, so a
    redelivered message reads False here and runs nothing.
    """
    from app.services.knowledge_ingest_job_service import (
        STATUS_INGESTING,
        STATUS_PROCESSING,
    )

    return _transition(
        chatbot_id, file_id, expected=STATUS_PROCESSING, new=STATUS_INGESTING
    )


def _release(chatbot_id: int, file_id: int) -> bool:
    """Give the claim back so a redelivery is allowed to try again."""
    from app.services.knowledge_ingest_job_service import (
        STATUS_INGESTING,
        STATUS_PROCESSING,
    )

    return _transition(
        chatbot_id, file_id, expected=STATUS_INGESTING, new=STATUS_PROCESSING
    )


def _give_up(chatbot_id: int, file_id: int) -> None:
    """Record a readable failure instead of paying for another attempt.

    Only an unclaimed row is failed: a document that reached ``completed``
    between deliveries must not be rewritten as broken.
    """
    from app.services.knowledge_ingest_job_service import (
        PHASE_DONE,
        STATUS_FAILED,
        STATUS_PROCESSING,
        _record,
    )

    try:
        _transition(
            chatbot_id, file_id, expected=STATUS_PROCESSING, new=STATUS_FAILED
        )
    except Exception as exc:  # noqa: BLE001 - the message still has to settle
        logger.error(
            "[IngestQueue] Could not record the give-up status for chatbot_id=%s, "
            "file_id=%s (%s)",
            chatbot_id,
            file_id,
            type(exc).__name__,
        )

    _record(
        chatbot_id,
        file_id,
        status=STATUS_FAILED,
        phase=PHASE_DONE,
        error_code="ingest_failed",
        message=(
            "We could not finish reading this document. Nothing about your "
            "current knowledge has changed - please try uploading it again."
        ),
    )


# ── The consumer ──────────────────────────────────────────────────────────


def _accepted_from(body: Any) -> dict | None:
    """One message body as an ``accepted`` record, or None if it is not one.

    A queue body is external input: it is validated here rather than trusted
    into ``process_uploaded_pdf``, which indexes every key without checking.
    """
    if not isinstance(body, dict):
        return None
    try:
        accepted = {field: body[field] for field in _DESCRIPTOR_FIELDS}
        accepted["chatbot_id"] = int(accepted["chatbot_id"])
        accepted["file_id"] = int(accepted["file_id"])
    except (KeyError, TypeError, ValueError):
        return None
    if accepted["chatbot_id"] <= 0 or accepted["file_id"] <= 0:
        return None
    if not all(
        isinstance(accepted[field], str) and accepted[field]
        for field in _DESCRIPTOR_FIELDS[2:]
    ):
        return None
    return accepted


def _run_delivery(lease) -> bool:
    """Handle one delivery. True to acknowledge, False to redeliver later."""
    accepted = _accepted_from(lease.body)
    if accepted is None:
        # No number of redeliveries makes a malformed descriptor succeed, so
        # acknowledging it is the only way it ever leaves the queue.
        logger.warning("[IngestQueue] Discarded a message that is not a job descriptor")
        return True

    chatbot_id = accepted["chatbot_id"]
    file_id = accepted["file_id"]

    if lease.attempts > MAX_INGEST_ATTEMPTS:
        logger.error(
            "[IngestQueue] Giving up on chatbot_id=%s, file_id=%s after %s deliveries",
            chatbot_id,
            file_id,
            lease.attempts,
        )
        _give_up(chatbot_id, file_id)
        return True

    try:
        claimed = _claim(chatbot_id, file_id)
    except Exception as exc:  # noqa: BLE001 - unclaimed work is retryable work
        logger.warning(
            "[IngestQueue] Could not claim chatbot_id=%s, file_id=%s (%s)",
            chatbot_id,
            file_id,
            type(exc).__name__,
        )
        return False

    if not claimed:
        # Another delivery already owns this ingest, or it has already reached
        # a terminal status. Either way the billed work must not run again.
        return True

    from app.services.knowledge_ingest_job_service import _run

    try:
        _run(accepted)
    except Exception as exc:  # noqa: BLE001 - _run handles its own failures
        logger.error(
            "[IngestQueue] Ingest crashed past its own handler for chatbot_id=%s, "
            "file_id=%s (%s)",
            chatbot_id,
            file_id,
            type(exc).__name__,
        )
        try:
            _release(chatbot_id, file_id)
        except Exception as release_error:  # noqa: BLE001
            logger.error(
                "[IngestQueue] Could not release the claim on file_id=%s (%s)",
                file_id,
                type(release_error).__name__,
            )
            return True
        return False

    return True


def _consume_once() -> int:
    """Pull and settle at most one message. Returns how many were handled."""
    queue_id = _queue_id()
    leases = cf_queue.pull(
        queue_id, batch_size=BATCH_SIZE, visibility_timeout_ms=VISIBILITY_TIMEOUT_MS
    )

    for lease in leases:
        if _run_delivery(lease):
            cf_queue.ack(queue_id, acks=[lease.lease_id], retries=[])
        else:
            cf_queue.ack(
                queue_id, acks=[], retries=[(lease.lease_id, RETRY_DELAY_SECONDS)]
            )

    return len(leases)


def _loop() -> None:
    while True:
        handled = 0
        try:
            if enabled():
                handled = _consume_once()
        except Exception as exc:  # noqa: BLE001 - a thread body must not die
            logger.warning("[IngestQueue] Consumer poll failed (%s)", type(exc).__name__)

        if handled:
            # Drain a backlog -- after a deploy there may be several waiting.
            continue
        _wake.wait(POLL_INTERVAL_SECONDS)
        _wake.clear()


def _ensure_started() -> None:
    """Start the consumer on first use, exactly once per process.

    Same shape as ``webhook_worker._ensure_started``. There is one consumer
    because there is one machine: the deployment is a single Fly machine with
    one gunicorn worker and ``--ha=false``.
    """
    global _started
    if _started:
        return
    with _start_lock:
        if _started:
            return
        threading.Thread(
            target=_loop,
            name="knowledge-ingest-consumer",
            daemon=True,
        ).start()
        _started = True


def start_consumer() -> None:
    """Start the consumer at boot, so a stranded message drains on its own.

    ``publish`` starts it too, but that alone leaves the queue unattended after
    a deploy: a message whose consumer died mid-ingest waits for the next upload
    before anyone pulls it again, which on a quiet day is hours.

    Safe to call while the feature is off. :func:`_loop` re-reads :func:`enabled`
    on every iteration, so with ``INGEST_QUEUE_ENABLED`` unset this is one
    sleeping thread that costs nothing, and turning the flag on becomes a secret
    change rather than a deploy. Idempotent -- ``_ensure_started`` starts the
    thread exactly once per process.
    """
    _ensure_started()
