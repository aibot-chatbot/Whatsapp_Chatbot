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

Why one lane per Client: the queue is shared by every channel of every Client,
so one Client's flood used to fill all 64 places and answer every other
Client's webhook with 503. Each Client now waits in its own lane, the workers
take turns between lanes, and a full lane answers 503 for that Client only.
"""

import logging
import os
import threading
from collections import Counter, deque

#: Concurrent replies in flight. Kept at or below the gunicorn thread count so
#: ingest, the retry loop and these workers cannot collectively outnumber the
#: cores on a shared-cpu-1x machine.
WEBHOOK_WORKERS = int(os.getenv("WEBHOOK_WORKERS", "4"))

#: Messages allowed to wait. At ~7 s per reply and 4 workers this is about two
#: minutes of backlog -- beyond that the provider redelivering later genuinely
#: is better than us answering a customer who has given up.
WEBHOOK_QUEUE_SIZE = int(os.getenv("WEBHOOK_QUEUE_SIZE", "64"))

#: Replies one Client may have in flight, so half the workers stay free for others.
WEBHOOK_WORKERS_PER_CLIENT = int(os.getenv("WEBHOOK_WORKERS_PER_CLIENT", "2"))

#: Messages one Client may have waiting, so no Client can take the whole queue.
WEBHOOK_QUEUE_PER_CLIENT = int(os.getenv("WEBHOOK_QUEUE_PER_CLIENT", "20"))

# shortcut: in-memory per process; upgrade when Redis lands (Part B)
# Lanes in turn order: a dict keeps insertion order, and a lane that is served
# goes to the back. Each lane is a FIFO of (label, work) for one company_id.
_lanes = {}
_running = Counter()
_waiting = 0
_changed = threading.Condition()
_start_lock = threading.Lock()
_started = False


def _take():
    """Block until a lane has work and its Client has a free slot; take its oldest job."""
    global _waiting
    with _changed:
        while True:
            for company_id, lane in _lanes.items():
                if _running[company_id] < WEBHOOK_WORKERS_PER_CLIENT:
                    break
            else:
                _changed.wait()
                continue
            del _lanes[company_id]
            label, work = lane.popleft()
            if lane:
                _lanes[company_id] = lane
            _running[company_id] += 1
            _waiting -= 1
            return company_id, label, work


def _worker() -> None:
    while True:
        company_id, label, work = _take()
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
            with _changed:
                _running[company_id] -= 1
                if not _running[company_id]:
                    del _running[company_id]
                _changed.notify_all()


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


def submit(label: str, work, company_id) -> bool:
    """Queue ``work`` in ``company_id``'s lane to run off the request thread.

    ``company_id`` must be the Client of the channel the webhook's own secret
    maps to, never a value from the payload, or a sender could spend another
    Client's places. Returns False when that Client's lane or the whole queue
    is full, which the caller should answer with 503 so the provider
    redelivers rather than the message being lost.
    """
    global _waiting
    _ensure_started()
    with _changed:
        if _waiting >= WEBHOOK_QUEUE_SIZE or len(_lanes.get(company_id, ())) >= WEBHOOK_QUEUE_PER_CLIENT:
            return False
        _lanes.setdefault(company_id, deque()).append((label, work))
        _waiting += 1
        _changed.notify_all()
    return True


def drain(timeout: float = 10.0) -> bool:
    """Block until queued work has finished. Returns False if ``timeout`` expired.

    Exists so tests exercise the real queue-and-worker path rather than an
    inline test-only mode, which would pass while hiding exactly the threading
    faults this module can introduce. A timeout keeps a hung worker from
    hanging the suite.
    """
    with _changed:
        return _changed.wait_for(lambda: not (_waiting or _running), timeout)
