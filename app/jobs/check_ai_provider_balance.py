"""Watch the credit left on the shared AI provider key.

Every tenant on a pooled plan spends the SAME OpenRouter key. Their per-company
MYR wallets can all be full while this one USD balance is empty, and when it
empties every bot on the platform stops answering at the same moment, with no
signal anywhere in the product -- the tenant sees a failed reply, and the first
anyone knows is a support message.

This job is the missing signal. It reads the balance OpenRouter itself reports
and escalates by how close to empty it is, so the operator hears about it days
before customers do.

Why log levels rather than a billing notification: ``billing_notification_service``
is per-company (every notification carries a ``company_id``), and this is a
platform-level fact that belongs to no tenant. Picking a company to attach it to
would be a lie. An ``ERROR`` log is already promoted to a Sentry event by the
LoggingIntegration in ``app/observability.py``, which is where operator alerts
for this deployment live.

Thresholds are in USD because that is the unit OpenRouter reports; converting to
MYR here would need the FX rate and would only obscure what the operator has to
top up.

With the management key, the warning goes by how many days the balance lasts at
the recent rate of spending, so it stays useful at any size. The fixed urgent line
stays as a floor. Without that key, or when spending cannot be read, the fixed
lines are used. The owner gets an email as well as the log.
"""

import argparse
import logging
import os
import time
from datetime import datetime, timezone

from app.services import openrouter_key_service

logger = logging.getLogger(__name__)

#: Below this, the operator should plan a top-up. Warning only.
DEFAULT_WARN_USD = 20.0

#: Below this, a top-up is urgent -- reported at ERROR so it reaches Sentry.
DEFAULT_CRITICAL_USD = 5.0

#: Warn when the balance covers this many days at the recent rate of spending.
RUNWAY_WARN_DAYS = 7
#: Urgent when it covers this many.
RUNWAY_CRITICAL_DAYS = 2
#: The job runs every 15 minutes; the owner hears about each level once a day.
EMAIL_REPEAT_SECONDS = 24 * 60 * 60

# shortcut: per-process memory, correct while Fly runs one gunicorn worker; move to the DB if that changes.
_emailed_at = {}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s is not a number (%r); using %s", name, raw, default)
        return default
    # A negative threshold can never fire, which would silently disable the
    # alert this job exists to raise.
    return value if value >= 0 else default


def _now():
    return datetime.now(timezone.utc)


def _spend_per_day_usd():
    """Recent spending across every key, or None when it cannot be read.

    usage_weekly restarts every Monday and usage_monthly on the 1st, so the higher of the two
    daily rates is used and one reset cannot hide real spending. On a Monday the 1st both restart
    together, so the rate reads low for a few hours and the fixed urgent line is the only cover.
    Disabled keys are left out, because their past spending will not repeat. An empty listing is
    unreadable rather than zero: reading it as zero would remove the warning line altogether.
    """
    if not os.getenv("OPENROUTER_MANAGEMENT_API_KEY", "").strip():
        return None
    try:
        keys = [
            key for key in openrouter_key_service.list_openrouter_keys()
            if not key.get("disabled") and key.get("usage_weekly") is not None and key.get("usage_monthly") is not None
        ]
        if not keys:
            return None
        now = _now()
        week = sum(float(key.get("usage_weekly") or 0) for key in keys) / now.isoweekday()
        month = sum(float(key.get("usage_monthly") or 0) for key in keys) / now.day
        return max(week, month)
    except Exception as error:
        logger.warning("Recent AI spending could not be read (%s).", type(error).__name__)
        return None


def _email_owner(level, remaining_usd, spend_per_day):
    from app.services.email_service import send_ai_balance_alert_email

    now = time.monotonic()
    last = _emailed_at.get(level)
    if last is not None and now - last < EMAIL_REPEAT_SECONDS:
        return
    # Remembered only once sent, so a failed email is tried again on the next run.
    if send_ai_balance_alert_email(remaining_usd=remaining_usd, spend_per_day_usd=spend_per_day):
        _emailed_at[level] = now


def check_balance() -> int:
    """Read the provider balance and report it. Returns a process exit code.

    0 = balance read and healthy, or genuinely uncapped.
    1 = balance unknown, or below a configured threshold.
    """
    from app.services.openrouter_service import get_key_status

    warn_at = _env_float("AI_PROVIDER_BALANCE_WARN_USD", DEFAULT_WARN_USD)
    critical_at = _env_float("AI_PROVIDER_BALANCE_CRITICAL_USD", DEFAULT_CRITICAL_USD)

    status = get_key_status()

    if status is None:
        # Unknown is not empty. get_key_status has already logged why at
        # warning level; escalating here would turn every network blip into a
        # page and train the operator to ignore this alert.
        logger.warning("AI provider balance could not be read this cycle.")
        return 1

    remaining = status.get("limit_remaining")

    if remaining is None:
        # An uncapped key reports limit_remaining=None. That is NOT zero, and
        # treating it as zero would alert forever on a perfectly healthy
        # account. Pay-as-you-go keys look like this.
        logger.info(
            "AI provider key is uncapped (no credit limit); usage to date %s.",
            status.get("usage"),
        )
        return 0

    try:
        remaining_usd = float(remaining)
    except (TypeError, ValueError):
        logger.warning("AI provider balance was not numeric (%r).", remaining)
        return 1

    spend_per_day = _spend_per_day_usd()
    if spend_per_day is not None:
        warn_at = spend_per_day * RUNWAY_WARN_DAYS
        critical_at = max(critical_at, spend_per_day * RUNWAY_CRITICAL_DAYS)

    if remaining_usd <= critical_at:
        logger.error(
            "AI provider credit CRITICAL: %.2f USD left (threshold %.2f). "
            "Every pooled tenant stops answering when this reaches zero.",
            remaining_usd,
            critical_at,
        )
        _email_owner("critical", remaining_usd, spend_per_day)
        return 1

    if remaining_usd <= warn_at:
        logger.warning(
            "AI provider credit low: %.2f USD left (threshold %.2f).",
            remaining_usd,
            warn_at,
        )
        # Without a spending figure this is only the fixed line, which can be a false alarm.
        if spend_per_day is not None:
            _email_owner("low", remaining_usd, spend_per_day)
        return 1

    logger.info("AI provider credit healthy: %.2f USD left.", remaining_usd)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Report the credit left on the shared AI provider key.",
    )
    parser.parse_args(argv if argv is not None else [])
    return check_balance()


if __name__ == "__main__":
    raise SystemExit(main())
