"""Answer the messaging provider first, then generate the reply.

Both inbound webhooks used to run the whole reply inline and return 200 only
once it had been sent. A reply costs roughly seven seconds (32 PostgREST round
trips at ~124 ms, plus a 2-3 s model call), so the provider sat waiting for the
whole of it and re-delivered the message when its own timeout expired. Those
re-deliveries are already harmless in content -- ``claim_wasender_message``
de-duplicates by ``message_id`` -- but each one still occupies one of the eight
gunicorn threads for seven seconds, and eight concurrent customers saturate the
machine. Acknowledging first removes the retries at the source.

**This does not make processing more concurrent than it already was.** With
``--workers 1 --threads 8`` two webhooks delivered at the same time were already
handled on two threads with no ordering guarantee between them. Work moves off
the request thread here; it does not gain parallelism it did not have, so no
per-conversation ordering that previously held is lost.

Why a bounded queue rather than ``ThreadPoolExecutor``: the executor's queue is
unbounded, so a flood becomes memory growth and a reply latency that climbs
without limit while the provider is told everything is fine. A bounded queue
lets us say "busy" instead, and 503 is the one answer a webhook provider is
built to understand -- it redelivers later, which is exactly the backpressure we
want. Silently dropping a customer's message is the outcome worth avoiding.
"""

import logging
import os
import queue
import threading
import time

#: Concurrent replies in flight. Kept at or below the gunicorn thread count so
#: ingest, the retry loop and these workers cannot collectively outnumber the
#: cores on a shared-cpu-1x machine.
WEBHOOK_WORKERS = int(os.getenv("WEBHOOK_WORKERS", "4"))

#: Messages allowed to wait. At ~7 s per reply and 4 workers this is about two
#: minutes of backlog -- beyond that the provider redelivering later genuinely
#: is better than us answering a customer who has given up.
WEBHOOK_QUEUE_SIZE = int(os.getenv("WEBHOOK_QUEUE_SIZE", "64"))

_queue = queue.Queue(maxsize=WEBHOOK_QUEUE_SIZE)
_start_lock = threading.Lock()
_started = False


def _worker() -> None:
    while True:
        label, work = _queue.get()
        try:
            work()
        except Exception as e:
            # Type name only, never the message and never exc_info: a traceback
            # carries the exception's own message, and these quote customer text
            # and channel credentials. tests/test_wasender_logging.py pins that.
            # error level is deliberate -- this is the unhandled case, and the
            # Sentry LoggingIntegration turns it into an event with the frames.
            logging.error(
                "%s failed off the request thread (%s)", label, type(e).__name__
            )
        finally:
            _queue.task_done()


def _ensure_started() -> None:
    """Start the workers on first use, exactly once per process."""
    global _started
    if _started:
        return
    with _start_lock:
        if _started:
            return
        for index in range(WEBHOOK_WORKERS):
            threading.Thread(
                target=_worker,
                name=f"webhook-worker-{index}",
                daemon=True,
            ).start()
        _started = True


def submit(label: str, work) -> bool:
    """Queue ``work`` to run off the request thread.

    Returns False when the queue is full, which the caller should answer with
    503 so the provider redelivers rather than the message being lost.
    """
    _ensure_started()
    try:
        _queue.put_nowait((label, work))
        return True
    except queue.Full:
        return False


def drain(timeout: float = 10.0) -> bool:
    """Block until queued work has finished. Returns False if ``timeout`` expired.

    Exists so tests exercise the real queue-and-worker path rather than an
    inline test-only mode, which would pass while hiding exactly the threading
    faults this module can introduce. ``Queue.join`` cannot take a timeout, so
    a hung worker would hang the suite; this polls instead and reports.
    """
    deadline = time.monotonic() + timeout
    while _queue.unfinished_tasks:
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True
