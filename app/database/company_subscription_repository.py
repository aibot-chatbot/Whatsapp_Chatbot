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
    "pending_plan_id",
    "plan_change_effective_at",
    "cancellation_scheduled_at",
    "cancellation_effective_at",
    "cancelled_at",
    "status_updated_at",
})


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_company_subscription(company_id):
    """Fetch the current active subscription for a company.

    Returns the subscription record or None if the company has no active,
    trialing, or past-due subscription.

    This is the function used by access enforcement and billing guards.
    It intentionally excludes expired and cancelled subscriptions so that
    those paths fail closed.
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


def get_latest_company_subscription(company_id):
    """Fetch the latest subscription for a company regardless of status.

    Unlike get_company_subscription(), this returns any status including
    expired and cancelled. Used by ensure_default_company_subscription()
    to detect previously paid companies and avoid granting a new Free trial.

    Returns the subscription record or None if the company has never had
    a subscription.
    """
    if not company_id:
        raise ValueError("Company ID is required")

    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("company_id", company_id)
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
        "status_updated_at": _now_iso(),
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


def update_subscription_status_if_current(
    subscription_id,
    company_id,
    expected_status,
    target_status,
    extra_updates=None,
):
    """Atomically update subscription status only if current status matches.

    This is a conditional (optimistic) update: the WHERE clause includes
    the expected current status so that concurrent lifecycle workers cannot
    apply conflicting transitions.

    Args:
        subscription_id: ID of the subscription row.
        company_id: Company ID for scoping.
        expected_status: The status the subscription must currently have.
        target_status: The new status to set.
        extra_updates: Optional dict of additional fields to update.

    Returns:
        The updated subscription record.

    Raises:
        ValueError: If the subscription does not exist or the status
            does not match expected_status (zero rows updated).
    """
    if not subscription_id:
        raise ValueError("Subscription ID is required")
    if not company_id:
        raise ValueError("Company ID is required")
    if not expected_status:
        raise ValueError("expected_status is required")
    if not target_status:
        raise ValueError("target_status is required")

    now_iso = _now_iso()

    update_fields = {
        "status": target_status,
        "status_updated_at": now_iso,
        "updated_at": now_iso,
    }

    if extra_updates:
        for k, v in extra_updates.items():
            if k in ALLOWED_UPDATE_FIELDS:
                update_fields[k] = v

    response = (
        supabase
        .table(TABLE_NAME)
        .update(update_fields)
        .eq("id", subscription_id)
        .eq("company_id", company_id)
        .eq("status", expected_status)
        .execute()
    )

    rows = response.data or []

    if not rows:
        # Check whether the subscription exists at all to distinguish
        # "not found" from "status mismatch"
        check = (
            supabase
            .table(TABLE_NAME)
            .select("id, status")
            .eq("id", subscription_id)
            .eq("company_id", company_id)
            .limit(1)
            .execute()
        )
        check_rows = check.data or []
        if not check_rows:
            raise ValueError(f"Subscription {subscription_id} not found for company {company_id}")
        actual = check_rows[0].get("status")
        raise ValueError(
            f"Subscription {subscription_id} status is '{actual}', "
            f"expected '{expected_status}'; cannot transition to '{target_status}'"
        )

    return rows[0]




def conditional_activate_subscription(
    subscription_id,
    company_id,
    expected_plan_id,
    expected_status,
    expected_period_start,
    expected_period_end,
    target_plan_id,
    period_start_iso,
    period_end_iso,
    expected_period_end_is_null=False,
):
    """Activate a subscription only if it still matches the checkout snapshot.

    This is the core atomic-activation operation.  The WHERE clause requires
    the subscription to match all of the source-state fields captured at
    checkout time.  If any field has changed (e.g. another order already
    activated this subscription), zero rows are updated.

    Args:
        subscription_id: The subscription row ID.
        company_id: Company ID for scoping.
        expected_plan_id: The plan_id the subscription must currently have.
        expected_status: The status the subscription must have.
        expected_period_start: The current_period_start the subscription
            must have (may be None for trial subscriptions).
        expected_period_end: The current_period_end the subscription
            must have (may be None for trial subscriptions).
        expected_period_end_is_null: When True, current_period_end must still
            be NULL. This is used for paid recovery orders created from an
            explicitly captured NULL source period.
        target_plan_id: The new plan_id to set.
        period_start_iso: The new current_period_start value.
        period_end_iso: The new current_period_end value.

    Returns:
        The updated subscription record.

    Raises:
        ValueError: If the subscription does not exist or the source
            state does not match (zero rows updated).
    """
    if not subscription_id:
        raise ValueError("Subscription ID is required")
    if not company_id:
        raise ValueError("Company ID is required")
    if not target_plan_id:
        raise ValueError("target_plan_id is required")

    now_iso = _now_iso()

    update_fields = {
        "plan_id": target_plan_id,
        "status": "active",
        "trial_ends_at": None,
        "current_period_start": period_start_iso,
        "current_period_end": period_end_iso,
        "cancelled_at": None,
        "cancellation_scheduled_at": None,
        "cancellation_effective_at": None,
        "pending_plan_id": None,
        "plan_change_effective_at": None,
        "status_updated_at": now_iso,
        "updated_at": now_iso,
    }

    # Build query: all source fields must match
    query = (
        supabase
        .table(TABLE_NAME)
        .update(update_fields)
        .eq("id", subscription_id)
        .eq("company_id", company_id)
        .eq("plan_id", expected_plan_id)
        .eq("status", expected_status)
    )

    if expected_period_start is not None:
        query = query.eq("current_period_start", expected_period_start)
    if expected_period_end_is_null:
        query = query.is_("current_period_end", "null")
    elif expected_period_end is not None:
        query = query.eq("current_period_end", expected_period_end)

    response = query.execute()

    rows = response.data or []

    if not rows:
        # Check whether the subscription exists at all
        check = (
            supabase
            .table(TABLE_NAME)
            .select("id, plan_id, status, current_period_start, current_period_end")
            .eq("id", subscription_id)
            .eq("company_id", company_id)
            .limit(1)
            .execute()
        )
        check_rows = check.data or []
        if not check_rows:
            raise ValueError(f"Subscription {subscription_id} not found for company {company_id}")
        actual = check_rows[0]
        raise ValueError(
            f"Subscription {subscription_id} source state mismatch: "
            f"expected plan={expected_plan_id}, status={expected_status}, "
            f"period_start={expected_period_start}, period_end={expected_period_end}; "
            f"actual plan={actual.get('plan_id')}, status={actual.get('status')}, "
            f"period_start={actual.get('current_period_start')}, "
            f"period_end={actual.get('current_period_end')}"
        )

    return rows[0]

def get_due_subscriptions(now_iso: str | None = None, batch_size: int = 100) -> list[dict]:
    """Fetch subscriptions whose billing period or trial has expired.

    Returns subscriptions with status in (trialing, active, past_due) where:
      - status IN (trialing, active) AND trial_ends_at IS NOT NULL
        AND trial_ends_at <= now
      - status IN (active, past_due) AND current_period_end IS NOT NULL
        AND current_period_end <= now

    Expired and cancelled subscriptions are never returned.

    The function executes two separate queries (one per status group) because
    the Supabase/PostgREST client cannot express OR between different column
    filters in a single chain.  Results are deduplicated by subscription id
    and sorted deterministically.

    Args:
        now_iso: ISO-8601 UTC timestamp for comparison. Defaults to current UTC time.
        batch_size: Maximum number of rows to return.

    Returns:
        List of subscription dictionaries.
    """
    if now_iso is None:
        now_iso = _now_iso()

    if not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")

    # Query 1: Free trial candidates with expired trial_ends_at. Active is
    # included for historical rows that predate trialing status.
    # (trial_ends_at IS NOT NULL AND trial_ends_at <= now)
    trialing_response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .in_("status", ["trialing", "active"])
        .is_("trial_ends_at", "not.null")
        .lte("trial_ends_at", now_iso)
        .order("id", desc=False)
        .limit(batch_size)
        .execute()
    )

    # Query 2: active/past_due subscriptions with expired period
    # (current_period_end IS NOT NULL AND current_period_end <= now)
    period_response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .in_("status", ["active", "past_due"])
        .is_("current_period_end", "not.null")
        .lte("current_period_end", now_iso)
        .order("id", desc=False)
        .limit(batch_size)
        .execute()
    )

    trialing_rows = trialing_response.data or []
    period_rows = period_response.data or []

    # Merge, deduplicate by id, and enforce batch_size
    # Sort by expiry timestamp then id for determinism
    seen_ids: set[int] = set()
    merged: list[dict] = []

    def _expiry_key(row: dict) -> tuple[str, int]:
        status = (row.get("status") or "").strip().lower()
        if status in ("trialing", "active") and row.get("trial_ends_at"):
            ts = row.get("trial_ends_at", "") or ""
        else:
            ts = row.get("current_period_end", "") or ""
        return (ts, row.get("id", 0) or 0)

    for row in sorted(trialing_rows + period_rows, key=_expiry_key):
        rid = row.get("id")
        if rid is not None and rid not in seen_ids:
            seen_ids.add(rid)
            merged.append(row)
            if len(merged) >= batch_size:
                break

    return merged
