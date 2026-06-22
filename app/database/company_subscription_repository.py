from datetime import datetime, timezone

from app.database.db import supabase


TABLE_NAME = "company_subscriptions"

# Fields that callers are allowed to update on a subscription.
ALLOWED_UPDATE_FIELDS = frozenset({
    "plan_id",
    "status",
    "starts_at",
    "current_period_start",
    "current_period_end",
    "trial_ends_at",
    "cancelled_at",
    "ends_at",
    "external_customer_id",
    "external_subscription_id",
    "payment_gateway",
})


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_company_subscription(company_id):
    """Fetch the current active subscription for a company.

    Returns the subscription record or None if the company has no active,
    trialing, or past-due subscription.
    """
    if not company_id:
        raise ValueError("Company ID is required")

    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("company_id", company_id)
        .in_("status", ["trialing", "active", "past_due"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    rows = response.data or []
    return rows[0] if rows else None


def create_company_subscription(subscription_data):
    """Insert a new subscription record for a company.

    subscription_data must include at least:
        - company_id
        - plan_id

    Returns the created record.
    """
    company_id = subscription_data.get("company_id")
    plan_id = subscription_data.get("plan_id")

    if not company_id:
        raise ValueError("company_id is required")

    if not plan_id:
        raise ValueError("plan_id is required")

    payload = {
        "company_id": company_id,
        "plan_id": plan_id,
        "status": subscription_data.get("status", "active"),
        "starts_at": subscription_data.get("starts_at", _now_iso()),
        "current_period_start": subscription_data.get("current_period_start", _now_iso()),
        "current_period_end": subscription_data.get("current_period_end"),
        "trial_ends_at": subscription_data.get("trial_ends_at"),
        "cancelled_at": subscription_data.get("cancelled_at"),
        "ends_at": subscription_data.get("ends_at"),
        "external_customer_id": subscription_data.get("external_customer_id"),
        "external_subscription_id": subscription_data.get("external_subscription_id"),
        "payment_gateway": subscription_data.get("payment_gateway"),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }

    response = supabase.table(TABLE_NAME).insert(payload).execute()
    rows = response.data or []

    if not rows:
        raise ValueError("Failed to create company subscription")

    return rows[0]


def update_company_subscription(subscription_id, company_id, updates):
    """Update an existing company subscription record.

    Requires both subscription_id and company_id so that the update is
    always scoped to the correct company. Only fields in ALLOWED_UPDATE_FIELDS
    are accepted; id, company_id, and created_at are never updated.

    Returns the updated record.
    """
    if not subscription_id:
        raise ValueError("Subscription ID is required")

    if not company_id:
        raise ValueError("Company ID is required")

    if not updates:
        raise ValueError("No updates provided")

    # Keep only permitted fields
    filtered = {k: v for k, v in updates.items() if k in ALLOWED_UPDATE_FIELDS}

    if not filtered:
        raise ValueError("No allowed fields provided for update")

    filtered["updated_at"] = _now_iso()

    response = (
        supabase
        .table(TABLE_NAME)
        .update(filtered)
        .eq("id", subscription_id)
        .eq("company_id", company_id)
        .execute()
    )

    rows = response.data or []

    if not rows:
        raise ValueError("Subscription not found or access denied")

    return rows[0]
