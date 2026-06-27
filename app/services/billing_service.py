import logging
from datetime import datetime, timezone

from dateutil.relativedelta import relativedelta

from app.database.subscription_plan_repository import (
    get_active_plans as _get_active_plans,
    get_plan_by_id,
    get_plan_by_code,
)
from app.database.company_subscription_repository import (
    get_company_subscription as _get_company_subscription,
    create_company_subscription as _create_company_subscription,
)
from app.database.billing_usage_repository import (
    count_company_chatbots,
    count_active_company_members,
    count_company_channels,
    count_company_knowledge_files,
    sum_company_knowledge_storage,
    sum_company_ai_usage_tokens,
)


# Recognised AI model access tiers for subscription plans.
# These are ordered from least to most capable. Plans with a given tier
# may access models classified at or below that tier.
# Model-tier enforcement is not yet implemented.
MODEL_ACCESS_TIERS = frozenset({
    "economy",
    "standard",
    "premium",
})


def list_active_plans():
    """Return formatted list of active subscription plans."""
    plans = _get_active_plans()

    result = []
    for plan in plans:
        result.append({
            "id": plan.get("id"),
            "name": plan.get("name"),
            "code": plan.get("code"),
            "description": plan.get("description"),
            "price": str(plan.get("price", "0")),
            "currency": plan.get("currency"),
            "billing_interval": plan.get("billing_interval"),
            "chatbot_limit": plan.get("chatbot_limit"),
            "team_member_limit": plan.get("team_member_limit"),
            "knowledge_file_limit": plan.get("knowledge_file_limit"),
            "knowledge_storage_limit_bytes": plan.get("knowledge_storage_limit_bytes"),
            "channel_limit": plan.get("channel_limit"),
            "feature_flags": plan.get("feature_flags"),
            "included_ai_credit_micro_myr": plan.get("included_ai_credit_micro_myr", 0),
            "model_access_tier": plan.get("model_access_tier", "economy"),
        })

    return result


def get_current_subscription(company_id):
    """Return the current subscription for a company, including plan details.

    Returns None when the company has no active, trialing, or past-due subscription.
    The company_id must already be authenticated and scoped (e.g. from g.company_id).
    External payment fields are intentionally excluded from the response.
    Subscription information is never placed inside the JWT.
    """
    if not company_id:
        raise ValueError("Company ID is required")

    subscription = _get_company_subscription(company_id)

    if not subscription:
        return None

    plan = get_plan_by_id(subscription.get("plan_id"))

    result = {
        "id": subscription.get("id"),
        "company_id": subscription.get("company_id"),
        "plan_id": subscription.get("plan_id"),
        "status": subscription.get("status"),
        "starts_at": subscription.get("starts_at"),
        "current_period_start": subscription.get("current_period_start"),
        "current_period_end": subscription.get("current_period_end"),
        "trial_ends_at": subscription.get("trial_ends_at"),
        "cancelled_at": subscription.get("cancelled_at"),
        "ends_at": subscription.get("ends_at"),
        "payment_gateway": subscription.get("payment_gateway"),
        "created_at": subscription.get("created_at"),
        "updated_at": subscription.get("updated_at"),
    }

    if plan:
        result["plan"] = {
            "id": plan.get("id"),
            "name": plan.get("name"),
            "code": plan.get("code"),
            "description": plan.get("description"),
            "price": str(plan.get("price", "0")),
            "currency": plan.get("currency"),
            "billing_interval": plan.get("billing_interval"),
            "chatbot_limit": plan.get("chatbot_limit"),
            "team_member_limit": plan.get("team_member_limit"),
            "knowledge_file_limit": plan.get("knowledge_file_limit"),
            "knowledge_storage_limit_bytes": plan.get("knowledge_storage_limit_bytes"),
            "channel_limit": plan.get("channel_limit"),
            "feature_flags": plan.get("feature_flags"),
            "included_ai_credit_micro_myr": plan.get("included_ai_credit_micro_myr", 0),
            "model_access_tier": plan.get("model_access_tier", "economy"),
        }

    return result


def _parse_utc_datetime(raw_value):
    """Parse a raw value (string or datetime) into a timezone-aware UTC datetime.

    Returns None if the value is empty or cannot be parsed.
    """
    if not raw_value:
        return None

    if isinstance(raw_value, datetime):
        dt = raw_value
    else:
        dt = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt


def _resolve_billing_period(subscription, plan):
    """Determine the billing period start and end from a subscription record.

    Uses the plan's billing_interval to calculate the end when
    current_period_end is not stored.

    Returns (period_start, period_end, end_source) where:
      - period_start is always current_period_start (or now as fallback)
      - period_end is current_period_end when stored, or calculated
        using calendar-aware math from the start date
      - end_source is 'stored' or 'calculated'

    All values are timezone-aware UTC datetimes.
    Raises ValueError for unsupported billing_intervals.
    """
    billing_interval = (plan or {}).get("billing_interval", "monthly")

    raw_start = subscription.get("current_period_start")
    raw_end = subscription.get("current_period_end")

    period_start = _parse_utc_datetime(raw_start)

    if period_start is None:
        period_start = datetime.now(timezone.utc)

    if raw_end:
        period_end = _parse_utc_datetime(raw_end)

        if period_end is not None:
            return period_start, period_end, "stored"

    # current_period_end is missing � calculate from start using the plan interval
    if billing_interval == "monthly":
        period_end = period_start + relativedelta(months=1)
    elif billing_interval == "yearly":
        period_end = period_start + relativedelta(years=1)
    else:
        raise ValueError(
            f"Unsupported billing_interval: {billing_interval}"
        )

    return period_start, period_end, "calculated"


def _limit_value(plan, field):
    """Return the limit value, preserving None as unlimited."""
    return plan.get(field) if plan else None


def get_company_usage(company_id):
    """Return current usage statistics for a company against its plan limits.

    Returns None when the company has no current subscription.

    The returned structure includes:
      - period: billing period with start, end, and end_source
      - plan: basic plan info
      - usage: per-metric used/limit pairs (limit is None for unlimited)
    """
    if not company_id:
        raise ValueError("Company ID is required")

    subscription = _get_company_subscription(company_id)

    if not subscription:
        return None

    plan = get_plan_by_id(subscription.get("plan_id"))

    if not plan:
        return None

    period_start, period_end, end_source = _resolve_billing_period(
        subscription, plan
    )

    # Calculate all usage metrics
    chatbot_used = count_company_chatbots(company_id)
    member_used = count_active_company_members(company_id)
    channel_used = count_company_channels(company_id)
    file_used = count_company_knowledge_files(company_id)
    storage_used = sum_company_knowledge_storage(company_id)
    ai_tokens_used = sum_company_ai_usage_tokens(
        company_id, period_start, period_end
    )

    return {
        "period": {
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
            "end_source": end_source,
        },
        "plan": {
            "id": plan.get("id"),
            "name": plan.get("name"),
            "code": plan.get("code"),
            "billing_interval": plan.get("billing_interval"),
        },
        "usage": {
            "chatbots": {
                "used": chatbot_used,
                "limit": _limit_value(plan, "chatbot_limit"),
            },
            "team_members": {
                "used": member_used,
                "limit": _limit_value(plan, "team_member_limit"),
            },
            "knowledge_files": {
                "used": file_used,
                "limit": _limit_value(plan, "knowledge_file_limit"),
            },
            "knowledge_storage_bytes": {
                "used": storage_used,
                "limit": _limit_value(plan, "knowledge_storage_limit_bytes"),
            },
            "ai_tokens": {
                "input_tokens": ai_tokens_used["prompt_tokens"],
                "output_tokens": ai_tokens_used["completion_tokens"],
                "total_tokens": ai_tokens_used["total_tokens"],
            },
            "channels": {
                "used": channel_used,
                "limit": _limit_value(plan, "channel_limit"),
            },
        },
    }


def ensure_default_company_subscription(company_id):
    """Assign the Free subscription plan to a company if none exists.

    This is intended to be called during company registration, after the
    company and its first admin user have been created successfully.

    Behaviour:
        1. Validates that company_id exists.
        2. Checks whether the company already has a current subscription
           (trialing, active, or past-due).
        3. If a current subscription exists, returns it without changes.
        4. Looks up the Free plan by code "free".
        5. Raises a controlled error if the Free plan is missing.
        6. Creates an active Free subscription when none exists:
           - status = "active"
           - starts_at = now (UTC)
           - current_period_start = now (UTC)
           - current_period_end = one calendar month from now (UTC)
        7. External payment fields are not set.
        8. Re-reads and returns the current subscription after creation.

    Returns:
        dict: The current subscription record including plan details.

    Raises:
        ValueError: If company_id is missing.
        RuntimeError: If no Free plan is configured in the database.
    """
    if not company_id:
        raise ValueError("Company ID is required")

    # 1. Check whether the company already has a current subscription
    existing = _get_company_subscription(company_id)
    if existing:
        # Enriched response matching get_current_subscription format
        return get_current_subscription(company_id)

    # 2. Look up the Free plan
    free_plan = get_plan_by_code("free")

    if not free_plan:
        raise RuntimeError(
            "Free subscription plan is not configured. "
            "Please run the seed SQL to create subscription plans."
        )

    plan_id = free_plan["id"]
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    period_end = now + relativedelta(months=1)
    period_end_iso = period_end.isoformat()

    subscription_data = {
        "company_id": company_id,
        "plan_id": plan_id,
        "status": "active",
        "starts_at": now_iso,
        "current_period_start": now_iso,
        "current_period_end": period_end_iso,
    }

    try:
        created = _create_company_subscription(subscription_data)
    except Exception as exc:
        # The database has a unique partial index on company_id where
        # status IN ('trialing', 'active', 'past_due'). If creation
        # failed because another concurrent request created a current
        # subscription between our check and insert, re-read and return
        # the existing current subscription.
        retried = _get_company_subscription(company_id)
        if retried:
            return get_current_subscription(company_id)
        # Re-raise the original error � it was not a duplicate violation
        raise

    # Re-read and return the enriched subscription
    return get_current_subscription(company_id)
