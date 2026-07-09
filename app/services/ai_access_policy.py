"""Central AI-access and provider-routing policy.

This module is the single authority for determining whether a company
may use AI generation, which API route to use, and which access
restrictions apply.  All AI entry points must call resolve_ai_access()
before making a provider request.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.database.company_subscription_repository import (
    get_company_subscription as _get_company_subscription,
)
from app.database.subscription_plan_repository import get_plan_by_id

logger = logging.getLogger(__name__)

PLAN_CODE_FREE = "free"
PLAN_CODE_ESSENTIAL = "essential"
PLAN_CODE_ADVANCED = "advanced"
PLAN_CODE_PRO = "pro"

STATUS_TRIALING = "trialing"
STATUS_ACTIVE = "active"
STATUS_PAST_DUE = "past_due"
STATUS_EXPIRED = "expired"
STATUS_CANCELLED = "cancelled"

ROUTE_DIRECT_DEEPSEEK = "direct_deepseek"
ROUTE_OPENROUTER = "openrouter"
ROUTE_DENIED = "denied"

STATE_ACTIVE_TRIAL = "active_trial"
STATE_EXPIRED_TRIAL = "expired_trial"
STATE_FREE_NO_TRIAL = "free_no_trial"
STATE_ESSENTIAL = "essential"
STATE_ADVANCED = "advanced"
STATE_PRO = "pro"
STATE_PAST_DUE = "past_due"
STATE_UNKNOWN = "unknown"

TRIAL_DURATION_DAYS = 7

TRIAL_PROVIDER = "deepseek"
DEFAULT_TRIAL_MODEL = "deepseek-v4-flash"
TRIAL_MODEL = "deepseek-v4-flash"

OPENROUTER_PROVIDER_FAMILIES = frozenset({
    "openai",
    "google",
    "anthropic",
    "xai",
    "qwen",
    "mistral",
})


@dataclass(frozen=True)
class AIAccessPolicy:
    allowed: bool = False
    access_state: str = STATE_UNKNOWN
    api_route: str = ROUTE_DENIED
    max_model_tier: str | None = None
    top_up_allowed: bool = False
    model_editable: bool = False
    trial_ends_at: str | None = None
    denial_reason: str | None = None


def _parse_iso_datetime(raw_value):
    if not raw_value:
        return None
    try:
        dt = datetime.fromisoformat(str(raw_value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def resolve_ai_access(company_id, *, now=None):
    if now is None:
        now = datetime.now(timezone.utc)

    if not company_id:
        return AIAccessPolicy(
            allowed=False, access_state=STATE_UNKNOWN,
            denial_reason="No company ID provided.",
        )

    try:
        subscription = _get_company_subscription(company_id)
    except Exception:
        logger.exception("resolve_ai_access: repository error for company %s", company_id)
        return AIAccessPolicy(
            allowed=False, access_state=STATE_UNKNOWN,
            denial_reason="Unable to verify subscription. Please try again.",
        )

    if not subscription:
        return AIAccessPolicy(
            allowed=False, access_state=STATE_UNKNOWN,
            denial_reason="No active subscription found.",
        )

    plan_id = subscription.get("plan_id")
    status = (subscription.get("status") or "").lower().strip()
    trial_ends_at_raw = subscription.get("trial_ends_at")

    plan = None
    plan_code = None
    try:
        plan = get_plan_by_id(plan_id)
    except Exception:
        logger.exception("resolve_ai_access: plan lookup failed for plan_id %s", plan_id)

    if plan:
        plan_code = (plan.get("code") or "").lower().strip()

    # trialing (must be Free plan)
    if status == STATUS_TRIALING and plan_code == PLAN_CODE_FREE:
        trial_end = _parse_iso_datetime(trial_ends_at_raw)
        if trial_end is not None and trial_end > now:
            return AIAccessPolicy(
                allowed=True, access_state=STATE_ACTIVE_TRIAL,
                api_route=ROUTE_DIRECT_DEEPSEEK,
                max_model_tier=None, top_up_allowed=False,
                model_editable=False,
                trial_ends_at=trial_end.isoformat(), denial_reason=None,
            )
        else:
            return AIAccessPolicy(
                allowed=False, access_state=STATE_EXPIRED_TRIAL,
                denial_reason="Your trial has expired. Please subscribe to continue.",
            )

    # active
    if status == STATUS_ACTIVE:
        # Scheduler-safe guard: if current_period_end is in the past,
        # deny access even if the lifecycle job has not yet transitioned
        # the subscription to "expired". This protects the system when
        # the scheduled expiry processor is delayed.
        period_end_raw = subscription.get("current_period_end")
        if period_end_raw:
            period_end_dt = _parse_iso_datetime(period_end_raw)
            if period_end_dt is not None and period_end_dt <= now:
                return AIAccessPolicy(
                    allowed=False, access_state=STATE_UNKNOWN,
                    denial_reason="Your subscription period has ended. Please renew to continue.",
                )

        if plan_code == PLAN_CODE_ESSENTIAL:
            return AIAccessPolicy(
                allowed=True, access_state=STATE_ESSENTIAL,
                api_route=ROUTE_OPENROUTER, max_model_tier="economy",
                top_up_allowed=True, model_editable=True,
                trial_ends_at=None, denial_reason=None,
            )
        if plan_code == PLAN_CODE_ADVANCED:
            return AIAccessPolicy(
                allowed=True, access_state=STATE_ADVANCED,
                api_route=ROUTE_OPENROUTER, max_model_tier="standard",
                top_up_allowed=True, model_editable=True,
                trial_ends_at=None, denial_reason=None,
            )
        if plan_code == PLAN_CODE_PRO:
            return AIAccessPolicy(
                allowed=True, access_state=STATE_PRO,
                api_route=ROUTE_OPENROUTER, max_model_tier="premium",
                top_up_allowed=True, model_editable=True,
                trial_ends_at=None, denial_reason=None,
            )
        if plan_code == PLAN_CODE_FREE:
            return AIAccessPolicy(
                allowed=False, access_state=STATE_FREE_NO_TRIAL,
                denial_reason="Your plan does not include AI replies. Please subscribe.",
            )
        return AIAccessPolicy(
            allowed=False, access_state=STATE_UNKNOWN,
            denial_reason="Your subscription plan is not recognised.",
        )

    if status == STATUS_PAST_DUE:
        return AIAccessPolicy(
            allowed=False, access_state=STATE_PAST_DUE,
            denial_reason="Your subscription payment is past due.",
        )

    if status == STATUS_EXPIRED:
        return AIAccessPolicy(
            allowed=False, access_state=STATE_UNKNOWN,
            denial_reason="Your subscription has expired. Please renew to continue using AI features.",
        )

    if status == STATUS_CANCELLED:
        return AIAccessPolicy(
            allowed=False, access_state=STATE_UNKNOWN,
            denial_reason="Your subscription has been cancelled.",
        )

    return AIAccessPolicy(
        allowed=False, access_state=STATE_UNKNOWN,
        denial_reason="Your subscription status is not recognised.",
    )
