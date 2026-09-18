"""Per-turn memo for reads that cannot change while one message is answered.

Answering one inbound WhatsApp/Telegram message costs ~57 serial PostgREST
round trips, and a round trip to this project's Supabase measures ~124 ms p50
from the deployed machine, so the count is the latency. Most of those trips
re-read the same immutable rows: the chatbot row is fetched 6 times per reply,
the company status 5 times, the plan 3 times.

Scope is one inbound turn on one thread. Nothing is shared between turns,
between threads, or between tenants, and every key is tenant-scoped by the id
it is keyed on.

Deliberately NOT cached: the escalation lookup in is_conversation_escalated.
A human can take a conversation over while the model is still generating, and
that gate has to stay live on every check.
"""

import threading
from contextlib import contextmanager


_state = threading.local()


@contextmanager
def turn_cache():
    """Memoise per-turn reads for the duration of one inbound message.

    Nesting is a no-op, so an entry point may open a turn without knowing
    whether an outer one is already open.
    """
    if getattr(_state, "cache", None) is not None:
        yield
        return

    _state.cache = {}
    try:
        yield
    finally:
        _state.cache = None


def cached(key, loader):
    """Return ``loader()``, once per turn.

    Outside a turn the loader always runs, so nothing changes for request
    handlers, jobs and tests that never open one.
    """
    cache = getattr(_state, "cache", None)
    if cache is None:
        return loader()

    if key not in cache:
        cache[key] = loader()

    return cache[key]
