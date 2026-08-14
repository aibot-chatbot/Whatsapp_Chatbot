"""Shared subscription billing-period calculations and integrity checks."""

import logging
from datetime import datetime, timezone

from dateutil.relativedelta import relativedelta

logger = logging.getLogger(__name__)

SUPPORTED_BILLING_INTERVALS = frozenset({"monthly"})


def parse_period_datetime(raw_value):
    """Parse a billing-period timestamp into a timezone-aware datetime."""
    if not raw_value:
        return None

    if isinstance(raw_value, datetime):
        dt = raw_value
    else:
        dt = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt


def calculate_current_period_end(current_period_start, billing_interval):
    """Return the expected subscription period end for a supported interval."""
    period_start = parse_period_datetime(current_period_start)
    if period_start is None:
        raise ValueError("current_period_start is required")

    interval = (billing_interval or "").strip().lower()
    if interval == "monthly":
        return period_start + relativedelta(months=1)

    raise ValueError(f"Unsupported billing_interval: {billing_interval}")


def validate_current_period(current_period_start, current_period_end, billing_interval):
    """Validate that a period end matches the configured billing interval."""
    expected_end = calculate_current_period_end(
        current_period_start,
        billing_interval,
    )
    actual_end = parse_period_datetime(current_period_end)
    if actual_end is None:
        raise ValueError("current_period_end is required")

    if actual_end != expected_end:
        raise ValueError(
            "Subscription billing period does not match plan interval: "
            f"billing_interval={billing_interval!r}, "
            f"current_period_start={period_datetime_to_iso(current_period_start)!r}, "
            f"current_period_end={actual_end.isoformat()!r}, "
            f"expected_current_period_end={expected_end.isoformat()!r}"
        )

    return expected_end


def detect_current_period_anomaly(subscription, plan):
    """Return anomaly details when a stored subscription period is invalid."""
    if not subscription or not plan:
        return None

    billing_interval = (plan.get("billing_interval") or "").strip().lower()
    if billing_interval not in SUPPORTED_BILLING_INTERVALS:
        return None

    raw_start = subscription.get("current_period_start")
    raw_end = subscription.get("current_period_end")
    if not raw_start or not raw_end:
        return None

    try:
        expected_end = calculate_current_period_end(raw_start, billing_interval)
        actual_end = parse_period_datetime(raw_end)
    except (TypeError, ValueError):
        return {
            "reason": "unparseable_period",
            "billing_interval": billing_interval,
            "current_period_start": raw_start,
            "current_period_end": raw_end,
            "expected_current_period_end": None,
        }

    if actual_end == expected_end:
        return None

    return {
        "reason": "period_interval_mismatch",
        "billing_interval": billing_interval,
        "current_period_start": parse_period_datetime(raw_start).isoformat(),
        "current_period_end": actual_end.isoformat() if actual_end else None,
        "expected_current_period_end": expected_end.isoformat(),
    }


def log_current_period_anomaly(subscription, plan, context):
    """Emit an internal warning when stored subscription period data is invalid."""
    anomaly = detect_current_period_anomaly(subscription, plan)
    if not anomaly:
        return None

    logger.warning(
        "Subscription billing period integrity anomaly detected",
        extra={
            "context": context,
            "subscription_id": subscription.get("id"),
            "company_id": subscription.get("company_id"),
            "plan_id": subscription.get("plan_id"),
            "plan_code": plan.get("code"),
            "billing_interval": anomaly.get("billing_interval"),
            "current_period_start": anomaly.get("current_period_start"),
            "current_period_end": anomaly.get("current_period_end"),
            "expected_current_period_end": anomaly.get("expected_current_period_end"),
            "reason": anomaly.get("reason"),
        },
    )
    return anomaly


def period_datetime_to_iso(raw_value):
    """Return an ISO string for a parseable period timestamp."""
    dt = parse_period_datetime(raw_value)
    return dt.isoformat() if dt is not None else None
