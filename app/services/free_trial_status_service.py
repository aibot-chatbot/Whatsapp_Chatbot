"""Effective entitlement status for Free trial subscriptions."""

from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from typing import Any


PLAN_CODE_FREE = "free"


def parse_iso_datetime(raw_value: Any) -> datetime | None:
    """Parse a raw timestamp into a timezone-aware UTC datetime."""
    if not raw_value:
        return None
    if isinstance(raw_value, datetime):
        dt = raw_value
    else:
        try:
            dt = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _plan_code(plan: dict | None, subscription: dict | None = None) -> str:
    plan_code = ((plan or {}).get("code") or "").strip().lower()
    if plan_code:
        return plan_code
    nested_plan = ((subscription or {}).get("plan") or {})
    return (nested_plan.get("code") or "").strip().lower()


def resolve_effective_subscription_status(
    subscription: dict | None,
    plan: dict | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    """Return presentation/enforcement fields for subscription entitlement.

    For paid plans this preserves the stored status. For the Free plan,
    trial_ends_at is the entitlement source of truth: an expired or missing
    trial end fails closed without mutating the subscription row.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    raw_status = ((subscription or {}).get("status") or "").strip().lower()
    code = _plan_code(plan, subscription)

    fields = {
        "raw_status": raw_status,
        "effective_status": raw_status,
        "is_free_trial": code == PLAN_CODE_FREE,
        "trial_active": False,
        "trial_expired": False,
        "trial_missing": False,
        "trial_status": None,
        "trial_days_remaining": None,
    }

    if code != PLAN_CODE_FREE:
        return fields

    trial_end = parse_iso_datetime((subscription or {}).get("trial_ends_at"))
    if trial_end is None:
        fields.update({
            "effective_status": "expired",
            "trial_expired": True,
            "trial_missing": True,
            "trial_status": "missing",
        })
        return fields

    if trial_end <= now:
        fields.update({
            "effective_status": "expired",
            "trial_expired": True,
            "trial_status": "expired",
            "trial_days_remaining": 0,
        })
        return fields

    seconds_remaining = (trial_end - now).total_seconds()
    fields.update({
        "effective_status": "trialing",
        "trial_active": True,
        "trial_status": "active",
        "trial_days_remaining": max(1, int(ceil(seconds_remaining / 86400))),
    })
    return fields
