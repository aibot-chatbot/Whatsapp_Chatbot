"""Watch the OpenRouter keys that groups of Clients share.

Records each key's usage, tells the owner when a key is disabled or near its monthly cap, and
retires keys whose last Client has left. Does nothing until OPENROUTER_CLIENT_KEYS_ENABLED is on.
"""
import argparse
import logging
import time

import requests

from app.database import openrouter_key_repository
from app.services import openrouter_key_service
from app.services.email_service import send_openrouter_key_alert_email

logger = logging.getLogger(__name__)

#: Warn when this share of a key's monthly cap is left.
NEAR_CAP_SHARE = 0.2
#: A key stays near its cap until the month resets, so the warning repeats daily, not every run.
ALERT_REPEAT_SECONDS = 24 * 60 * 60
#: OpenRouter returns keys 100 at a time.
PAGE_SIZE = 100

# shortcut: per-process memory, correct while Fly runs one gunicorn worker; move to the DB if that changes.
_alerted_at = {}


def _list_openrouter_keys():
    keys, offset = [], 0
    while True:
        response = requests.get(
            openrouter_key_service.OPENROUTER_KEYS_URL,
            headers=openrouter_key_service.management_headers(),
            # Disabled keys are hidden by default, and those are the ones this job exists to find.
            params={"include_disabled": "true", "offset": offset},
            timeout=openrouter_key_service.KEY_API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        page = response.json()["data"]
        keys = [*keys, *page]
        if len(page) < PAGE_SIZE:
            return keys
        offset += PAGE_SIZE


def _alert(key, kind, problem):
    marker = (key["id"], kind)
    now = time.monotonic()
    last = _alerted_at.get(marker)
    if last is not None and now - last < ALERT_REPEAT_SECONDS:
        return
    # Remembered only once sent, so a failed email is tried again on the next run.
    if send_openrouter_key_alert_email(label=key["label"], problem=problem):
        _alerted_at[marker] = now


def _is_near_cap(usage):
    try:
        return float(usage["limit_remaining"]) <= float(usage["limit"]) * NEAR_CAP_SHARE
    except (KeyError, TypeError, ValueError):
        return False


def _check_key(key, usage):
    """Returns 1 when the owner needs to act on this key, otherwise 0."""
    clients = key["clients"]
    if usage is None or usage.get("disabled"):
        logger.error("OpenRouter key %s is disabled or missing; %s Clients get no AI replies.",
                     key["label"], clients)
        # Recorded first, so no new Client joins this key even if the email fails.
        if key["status"] == "active":
            openrouter_key_repository.mark_disabled(key["id"])
        _alert(key, "disabled", f"is disabled or missing on OpenRouter. {clients} Clients on it "
                                "get no AI replies, and new Clients will not join it.")
        return 1

    if key["status"] != "active":
        logger.warning("OpenRouter key %s is enabled again.", key["label"])
        openrouter_key_repository.mark_active(key["id"])
    logger.info("OpenRouter key %s: clients=%s usage_monthly=%s limit=%s limit_remaining=%s",
                key["label"], clients, usage.get("usage_monthly"), usage.get("limit"), usage.get("limit_remaining"))
    if not _is_near_cap(usage):
        return 0
    _alert(key, "near_cap", f"is near its monthly cap: US${usage['limit_remaining']} of US${usage['limit']} "
                            f"left. {clients} Clients stop getting AI replies when it runs out.")
    return 1


def check_keys() -> int:
    """Returns a process exit code: 0 = healthy or switched off, 1 = the owner needs to act."""
    if not openrouter_key_service.is_enabled():
        return 0
    openrouter_key_service.retire_empty_keys()
    # Disabled keys that still have Clients stay on the list, so the owner is reminded daily and a
    # key turned back on recovers. Empty ones are retired and need nothing more.
    stranded = [key for key in openrouter_key_repository.list_keys("disabled") if key["clients"]]
    keys = [*openrouter_key_repository.list_keys("active"), *stranded]
    if not keys:
        return 0
    usage_by_hash = {usage.get("hash"): usage for usage in _list_openrouter_keys()}
    if not any(key["key_hash"] in usage_by_hash for key in keys):
        # A wrong management key or a changed response, not every key gone at once.
        logger.error("OpenRouter listed none of our %s keys; nothing was changed.", len(keys))
        return 1
    openrouter_key_service.close_to_new_clients(
        key["id"] for key in keys if _is_near_cap(usage_by_hash.get(key["key_hash"]) or {})
    )
    return max(_check_key(key, usage_by_hash.get(key["key_hash"])) for key in keys)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check the OpenRouter keys that groups of Clients share.")
    parser.parse_args(argv if argv is not None else [])
    return check_keys()


if __name__ == "__main__":
    raise SystemExit(main())
