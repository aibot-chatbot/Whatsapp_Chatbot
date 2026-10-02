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
"""

import argparse
import logging
import os

logger = logging.getLogger(__name__)

#: Below this, the operator should plan a top-up. Warning only.
DEFAULT_WARN_USD = 20.0

#: Below this, a top-up is urgent -- reported at ERROR so it reaches Sentry.
DEFAULT_CRITICAL_USD = 5.0


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

    if remaining_usd <= critical_at:
        logger.error(
            "AI provider credit CRITICAL: %.2f USD left (threshold %.2f). "
            "Every pooled tenant stops answering when this reaches zero.",
            remaining_usd,
            critical_at,
        )
        return 1

    if remaining_usd <= warn_at:
        logger.warning(
            "AI provider credit low: %.2f USD left (threshold %.2f).",
            remaining_usd,
            warn_at,
        )
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
