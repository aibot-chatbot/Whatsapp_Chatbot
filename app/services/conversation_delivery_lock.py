"""Order persisted handoffs and automatic provider calls in one worker process.

The final pause check and provider call share this lock with handoff writes.
A send that acquires it first may finish before the handoff is persisted; an
already-started provider delivery cannot be cancelled. Model calls stay outside.
This supports the deployed one-process/eight-thread topology, not coordination
between multiple workers or Machines. Scaling requires a shared delivery gate.
"""

from contextlib import contextmanager
from threading import Lock, RLock
from weakref import WeakValueDictionary


# ponytail: Keep one worker process; multiple workers need a shared delivery gate.
_registry_lock = Lock()
_conversation_locks = WeakValueDictionary()


@contextmanager
def conversation_delivery_lock(conversation_id):
    """Hold a reentrant lock for a real conversation; reclaim it once idle."""
    if isinstance(conversation_id, bool) or not isinstance(conversation_id, int) or conversation_id <= 0:
        raise ValueError("A positive conversation_id is required for delivery coordination")
    with _registry_lock:
        lock = _conversation_locks.get(conversation_id)
        if lock is None:
            lock = RLock()
            _conversation_locks[conversation_id] = lock
    # Keep a strong reference while holding or waiting, so every contender uses
    # the same lock. The registry guard never spans a database or provider call.
    with lock:
        yield
