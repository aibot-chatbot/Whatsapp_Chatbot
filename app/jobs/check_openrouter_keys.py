"""Watch the OpenRouter keys that groups of Clients share.

Records each key's usage, keeps each cap in step with the credit of the Clients on the key, tells
the owner when a key is disabled or near its cap, and retires keys whose last Client has left.
Does nothing until OPENROUTER_CLIENT_KEYS_ENABLED is on.
"""
import argparse
import logging
import time
from datetime import datetime, timezone

from app.database import openrouter_key_repository
from app.services import openrouter_key_service
from app.services.email_service import send_openrouter_key_alert_email

logger = logging.getLogger(__name__)

#: Warn when this share of a key's monthly cap is left.
NEAR_CAP_SHARE = 0.2
#: A key stays near its cap until the month resets, so the warning repeats daily, not every run.
ALERT_REPEAT_SECONDS = 24 * 60 * 60

# shortcut: per-process memory, correct while Fly runs one gunicorn worker; move to the DB if that changes.
_alerted_at = {}


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


def _now():
    return datetime.now(timezone.utc)


def _is_start_of_month():
    now = _now()
    return now.day == 1 and now.hour == 0


def _month_start():
    return _now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def _adjust_cap(key, usage):
    """Keep the cap in step with the credit on this key. Returns True when it went up.

    It can only fall in the first hour of the month, when little is spent, and it is never set at
    or below what is already spent: that would stop the key at once.
    """
    try:
        credit = openrouter_key_repository.month_credit_micro_myr(key["id"], _month_start())
        target = openrouter_key_service.target_cap_usd(credit)
        limit = usage.get("limit")
        spent = float(usage.get("usage_monthly") or 0)
        if target <= spent:
            return False
        if limit is None or target > float(limit):
            openrouter_key_service.set_key_cap(key, target)
            # The key has room again, so its next near-cap warning must not wait for the daily repeat.
            _alerted_at.pop((key["id"], "near_cap"), None)
            logger.info("OpenRouter key %s: cap raised to %s.", key["label"], target)
            return True
        if target < float(limit) and _is_start_of_month():
            openrouter_key_service.set_key_cap(key, target)
            logger.info("OpenRouter key %s: cap lowered to %s.", key["label"], target)
    except Exception as error:
        logger.error("Could not adjust the cap on OpenRouter key %s (%s)", key["label"], type(error).__name__)
    return False


def _disable_reasons():
    """Why each disabled key was disabled, or None when that cannot be read (data/082 not applied).
    None moves nobody, and the disabled-key alert still goes out.
    """
    try:
        return openrouter_key_repository.list_disable_reasons()
    except Exception as error:
        logger.warning("Could not read why OpenRouter keys were disabled (%s); moving nobody.",
                       type(error).__name__)
        return None


def _record_disabled_by_openrouter(key):
    try:
        openrouter_key_repository.mark_disabled(key["id"], "openrouter")
    except Exception as error:
        # data/082 not applied yet: record the status alone, as before.
        logger.warning("Could not record why OpenRouter key %s is disabled (%s)", key["label"], type(error).__name__)
        openrouter_key_repository.mark_disabled(key["id"])


def _finish_disable(key, culprit_company_id, usage):
    """A key we disabled because of one Client: move every other Client off, then stop it on
    OpenRouter. Stopping it last means nobody else loses AI replies. Returns 1 when the owner must act.
    """
    try:
        moved = openrouter_key_service.move_clients_off(key, culprit_company_id)
        if usage is not None and not usage.get("disabled"):
            openrouter_key_service.disable_on_openrouter(key)
    except Exception as error:
        logger.error("Could not finish disabling OpenRouter key %s (%s)", key["label"], type(error).__name__)
        _alert(key, "move_failed", "was disabled because of one Client, but moving the other Clients off it "
                                   f"or stopping it on OpenRouter failed ({type(error).__name__}). "
                                   "The next check tries again.")
        return 1
    if moved:
        logger.info("OpenRouter key %s: moved %s Clients off; company_id=%s stays on it.",
                    key["label"], moved, culprit_company_id)
    return 0


def _check_key(key, usage, reasons):
    """Returns 1 when the owner needs to act on this key, otherwise 0."""
    why = (reasons or {}).get(key["id"]) or {}
    if why.get("disabled_reason") == "ours":
        return _finish_disable(key, why.get("culprit_company_id"), usage)

    clients = key["clients"]
    if usage is None or usage.get("disabled"):
        logger.error("OpenRouter key %s is disabled or missing; %s Clients get no AI replies.",
                     key["label"], clients)
        # Recorded first, so no new Client joins this key even if the email fails. Nobody is moved:
        # only a key we disabled because of a known Client moves the others.
        if key["status"] == "active":
            _record_disabled_by_openrouter(key)
        _alert(key, "disabled", f"is disabled or missing on OpenRouter. {clients} Clients on it "
                                "get no AI replies, and new Clients will not join it.")
        return 1

    # A key we disabled never gets here (handled above), so this is safe even when reasons are
    # unreadable: without data/082 no such decision can be recorded.
    if key["status"] != "active":
        logger.warning("OpenRouter key %s is enabled again.", key["label"])
        openrouter_key_repository.mark_active(key["id"])
    logger.info("OpenRouter key %s: clients=%s usage_monthly=%s limit=%s limit_remaining=%s",
                key["label"], clients, usage.get("usage_monthly"), usage.get("limit"), usage.get("limit_remaining"))
    # Near-cap figures read before a raise are out of date, so a raise settles this run.
    if _adjust_cap(key, usage) or not _is_near_cap(usage):
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
    usage_by_hash = {usage.get("hash"): usage for usage in openrouter_key_service.list_openrouter_keys()}
    if not any(key["key_hash"] in usage_by_hash for key in keys):
        # A wrong management key or a changed response, not every key gone at once.
        logger.error("OpenRouter listed none of our %s keys; nothing was changed.", len(keys))
        return 1
    openrouter_key_service.close_to_new_clients(
        key["id"] for key in keys if _is_near_cap(usage_by_hash.get(key["key_hash"]) or {})
    )
    reasons = _disable_reasons()
    return max(_check_key(key, usage_by_hash.get(key["key_hash"]), reasons) for key in keys)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check the OpenRouter keys that groups of Clients share.")
    parser.parse_args(argv if argv is not None else [])
    return check_keys()


if __name__ == "__main__":
    raise SystemExit(main())
