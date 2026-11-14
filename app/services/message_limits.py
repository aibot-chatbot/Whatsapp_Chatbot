"""Limits checked before any safety filter, retrieval or AI call reads a customer message (Phase 5).

Each limit answers with a short fixed reply. None of them hands the chat to staff or counts as a
content flag: they are about volume, not content, so the 24-hour content cooldown stays separate.

shortcut: in-memory per process, resets on restart; upgrade when Redis lands (Part B).
"""
import logging
import os
import threading
import time
from collections import deque

from app.config import _is_production

#: Longest customer message the AI will read, on every channel. The widget refuses longer ones itself.
MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "2000"))
#: Owner decision: messages one customer may send one bot per minute.
CUSTOMER_MESSAGES_PER_MINUTE = int(os.getenv("CUSTOMER_MESSAGES_PER_MINUTE", "8"))
#: Owner decision: messages all of one Client's bots may take per minute.
CLIENT_MESSAGES_PER_MINUTE = int(os.getenv("CLIENT_MESSAGES_PER_MINUTE", "120"))
WINDOW_SECONDS = 60

SILENT_REPLY = "<SILENT_BOT_RESPONSE>"
TOO_LONG_REPLY = "Sorry, that message is too long for me to read. Please send a shorter message."
SLOW_DOWN_REPLY = "You're sending messages very quickly. Please wait a minute, then send your question again."
BUSY_REPLY = "Sorry, we're receiving a lot of messages right now. Please try again in a minute."

_TRUE = ("1", "true", "yes", "on")
_lock = threading.Lock()  # gunicorn runs 8 threads in one worker
_customers = {}  # (chatbot_id, customer_id) -> _Window
_clients = {}  # company_id -> _Window
_last_sweep = 0.0


class _Window:
    """Accepted-message times in the last minute, and when this sender was last told about a limit."""

    __slots__ = ("times", "warned_at")

    def __init__(self):
        self.times = deque()
        self.warned_at = None

    def full(self, limit, now):
        while self.times and now - self.times[0] >= WINDOW_SECONDS:
            self.times.popleft()
        return len(self.times) >= limit

    def warned_recently(self, now):
        return self.warned_at is not None and now - self.warned_at < WINDOW_SECONDS


def _rate_limits_enabled():
    # The app's own rate-limit switch (app/config.py): on in production, off in development and tests.
    default = "true" if _is_production() else "false"
    return os.getenv("RATELIMIT_ENABLED", default).strip().lower() in _TRUE


def _sweep(now):
    """Forget idle senders once a minute, so rotating customer IDs cannot grow memory without end."""
    global _last_sweep
    if now - _last_sweep < WINDOW_SECONDS:
        return
    _last_sweep = now
    for table in (_customers, _clients):
        for key in [key for key, window in table.items()
                    if not window.full(1, now) and not window.warned_recently(now)]:
            del table[key]


def _rate_verdict(company_id, chatbot_id, customer_key, now):
    with _lock:
        _sweep(now)
        customer = _customers.get(customer_key) if customer_key is not None else None
        if customer is not None and customer.full(CUSTOMER_MESSAGES_PER_MINUTE, now):
            if customer.warned_recently(now):
                return SILENT_REPLY
            customer.warned_at = now
            logging.warning("[MessageLimits] chatbot_id=%s: a customer passed %s messages a minute",
                            chatbot_id, CUSTOMER_MESSAGES_PER_MINUTE)
            return SLOW_DOWN_REPLY
        client = _clients.setdefault(company_id, _Window())
        if client.full(CLIENT_MESSAGES_PER_MINUTE, now):
            if not client.warned_recently(now):
                client.warned_at = now
                logging.warning("[MessageLimits] company_id=%s passed %s messages a minute",
                                company_id, CLIENT_MESSAGES_PER_MINUTE)
            return BUSY_REPLY
        client.times.append(now)
        if customer_key is not None:
            _customers.setdefault(customer_key, _Window()).times.append(now)
    return None


def check(message, *, company_id, chatbot_id, customer_id=None, now=None):
    """The fixed reply for a message that must not reach the AI, or None when it may go on.

    customer_id=None skips the per-customer limit (an owner's test chat). A message over the length
    cap still counts toward both rate limits, so a flood of long messages is limited too.
    """
    if _rate_limits_enabled():
        customer_key = (chatbot_id, str(customer_id)) if customer_id is not None else None
        verdict = _rate_verdict(company_id, chatbot_id, customer_key, time.monotonic() if now is None else now)
        if verdict is not None:
            return verdict
    if len(message or "") > MAX_MESSAGE_LENGTH:
        logging.warning("[MessageLimits] chatbot_id=%s: a message passed %s characters", chatbot_id, MAX_MESSAGE_LENGTH)
        return TOO_LONG_REPLY
    return None
