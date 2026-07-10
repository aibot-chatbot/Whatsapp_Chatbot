"""
company_subscription_order_repository.py

Supabase data-access layer for the ``company_subscription_orders`` table.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from app.database.db import supabase

logger = logging.getLogger(__name__)

TABLE = "company_subscription_orders"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _single_row(response: Any, label: str) -> dict | None:
    """Return the first row or None."""
    data = response.data if hasattr(response, "data") else response
    if data is None:
        return None
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        return data
    raise RuntimeError(f"{label}: unexpected response shape: {type(data).__name__}")


def create_subscription_order(
    order_reference: str,
    company_id: int,
    subscription_id: int,
    new_plan_id: int,
    amount_sen: int,
    payment_gateway: str,
    idempotency_key: str,
    created_by_user_id: int,
    expires_at: str | None = None,
    source_plan_id: int | None = None,
    source_period_start: str | None = None,
    source_period_end: str | None = None,
    source_status: str | None = None,
    activation_type: str | None = None,
    activation_sequence_key: str | None = None,
    order_schema_version: int | None = 2,
) -> dict:
    """Insert a new pending subscription order row.

    New orders must include activation_type, activation_sequence_key,
    source_status, and required source-state fields, with
    order_schema_version=2 (the default)."""
    now = _now_iso()
    payload: dict[str, Any] = {
        "order_reference": order_reference,
        "company_id": company_id,
        "subscription_id": subscription_id,
        "new_plan_id": new_plan_id,
        "amount_sen": amount_sen,
        "payment_gateway": payment_gateway,
        "idempotency_key": idempotency_key,
        "created_by_user_id": created_by_user_id,
        "status": "pending",
        "expires_at": expires_at,
        "source_plan_id": source_plan_id,
        "source_period_start": source_period_start,
        "source_period_end": source_period_end,
        "source_status": source_status,
        "activation_type": activation_type,
        "activation_sequence_key": activation_sequence_key,
        "order_schema_version": order_schema_version,
        "created_at": now,
        "updated_at": now,
    }
    response = supabase.table(TABLE).insert(payload).execute()
    rows = response.data or []
    if not rows:
        raise RuntimeError(
            f"create_subscription_order: insert returned no rows "
            f"(order_reference={order_reference})"
        )
    return rows[0]


def list_subscription_orders_for_company(
    company_id: int,
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
) -> list[dict]:
    """List subscription orders for a company, newest first.

    Args:
        company_id: The owning company.
        limit: Maximum number of rows to return (default 20, max 100).
        offset: Pagination offset.
        status: Optional safe status filter.

    Returns:
        A list of order dictionaries ordered by created_at DESC, then id DESC.
    """
    if not company_id:
        return []

    if limit < 1:
        limit = 20
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0

    query = (
        supabase
        .table(TABLE)
        .select("*")
        .eq("company_id", company_id)
        .order("created_at", desc=True)
        .order("id", desc=True)
    )

    if status:
        query = query.eq("status", status)

    response = query.range(offset, offset + limit - 1).execute()
    return response.data or []


def get_subscription_order_by_reference(order_reference: str) -> dict | None:
    """Fetch a single order by its unique order reference."""
    if not order_reference:
        return None
    response = supabase.table(TABLE).select("*").eq("order_reference", order_reference).limit(1).execute()
    return _single_row(response, "get_subscription_order_by_reference")


def get_subscription_order_by_gateway_id(
    payment_gateway: str, gateway_order_id: str
) -> dict | None:
    """Fetch a single order by its gateway and gateway order ID."""
    if not payment_gateway or not gateway_order_id:
        return None
    response = supabase.table(TABLE).select("*").eq("payment_gateway", payment_gateway).eq("gateway_order_id", gateway_order_id).limit(1).execute()
    return _single_row(response, "get_subscription_order_by_gateway_id")



def get_subscription_order_by_reference_and_company(
    order_reference: str,
    company_id: int,
) -> dict | None:
    """Fetch a single subscription order by its reference and company ID.

    Returns the order row only when both the reference and the company
    match, enforcing company-level isolation.
    """
    if not order_reference or not company_id:
        return None

    response = (
        supabase
        .table(TABLE)
        .select("*")
        .eq("order_reference", order_reference)
        .eq("company_id", company_id)
        .limit(1)
        .execute()
    )
    return _single_row(response, "get_subscription_order_by_reference_and_company")


def claim_subscription_billing_period(
    order_reference: str,
    billing_period_key: str,
) -> dict:
    """Atomically claim a billing period for a subscription order.

    Sets the billing_period_key on the order. The unique partial index on
    billing_period_key (WHERE billing_period_key IS NOT NULL) ensures that
    two different orders cannot claim the same billing period.

    Args:
        order_reference: The unique order reference to update.
        billing_period_key: The deterministic billing-period key to claim.

    Returns:
        The updated order dictionary.

    Raises:
        RuntimeError: If the billing period is already claimed by another
            order (duplicate key violation) or the order is not found.
    """
    if not order_reference:
        raise ValueError("order_reference is required")
    if not billing_period_key:
        raise ValueError("billing_period_key is required")

    now = _now_iso()
    updates = {
        "billing_period_key": billing_period_key,
        "updated_at": now,
    }

    response = (
        supabase
        .table(TABLE)
        .update(updates)
        .eq("order_reference", order_reference)
        .execute()
    )

    rows = response.data or []

    if not rows:
        # Update returned no rows - the order may not exist or the
        # billing_period_key may conflict with another order
        raise RuntimeError(
            f"Failed to claim billing period for order {order_reference!r}. "
            f"The billing period may already be claimed or the order does not exist."
        )

    return rows[0]

def claim_subscription_activation_sequence(
    order_reference: str,
    activation_sequence_key: str,
) -> dict:
    """Atomically claim an activation sequence for a subscription order.

    Sets the activation_sequence_key on the order. The unique partial index on
    activation_sequence_key (WHERE activation_sequence_key IS NOT NULL) ensures
    that two different orders cannot claim the same activation sequence.

    This is the core atomicity primitive: the key is computed at checkout time,
    so two orders created against the same source subscription state will have
    the same key, and only the first callback to claim it will proceed.

    Args:
        order_reference: The unique order reference to update.
        activation_sequence_key: The deterministic activation key to claim.

    Returns:
        The updated order dictionary.

    Raises:
        RuntimeError: If the activation sequence is already claimed by another
            order or the order is not found.
    """
    if not order_reference:
        raise ValueError("order_reference is required")
    if not activation_sequence_key:
        raise ValueError("activation_sequence_key is required")

    now = _now_iso()
    updates = {
        "activation_sequence_key": activation_sequence_key,
        "updated_at": now,
    }

    response = (
        supabase
        .table(TABLE)
        .update(updates)
        .eq("order_reference", order_reference)
        .execute()
    )

    rows = response.data or []

    if not rows:
        # Update returned no rows - the order may not exist or the
        # activation_sequence_key may conflict with another order
        raise RuntimeError(
            f"Failed to claim activation sequence for order {order_reference!r}. "
            f"The sequence may already be claimed or the order does not exist."
        )

    return rows[0]

def update_subscription_order_status(
    order_reference: str, status: str, **extra: Any
) -> dict:
    """Update the status (and optional extra fields) of an order."""
    if not order_reference:
        raise ValueError("order_reference is required")
    updates: dict[str, Any] = {"status": status, "updated_at": _now_iso()}
    updates.update(extra)
    response = supabase.table(TABLE).update(updates).eq("order_reference", order_reference).execute()
    rows = response.data or []
    if not rows:
        raise RuntimeError(
            f"update_subscription_order_status: update returned no rows "
            f"(order_reference={order_reference})"
        )
    return rows[0]

# Reconciliation support
RECONCILABLE_ACTIVATION_STATUSES = frozenset({
    "claimed", "activated", "credit_pending", "failed", "conflict",
})



def update_subscription_order_activation_state(
    order_reference: str,
    activation_status: str | None = None,
    activation_error_code: str | None = None,
    activation_error_message: str | None = None,
    activation_claimed_at: str | None = None,
    activation_completed_at: str | None = None,
    credit_granted_at: str | None = None,
    reconciliation_required: bool | None = None,
) -> dict:
    """Update activation-state and reconciliation fields on an order."""
    if not order_reference:
        raise ValueError("order_reference is required")
    now = _now_iso()
    updates: dict[str, Any] = {"updated_at": now}
    if activation_status is not None:
        updates["activation_status"] = activation_status
    if activation_error_code is not None:
        updates["activation_error_code"] = activation_error_code
    if activation_error_message is not None:
        updates["activation_error_message"] = activation_error_message
    if activation_claimed_at is not None:
        updates["activation_claimed_at"] = activation_claimed_at
    if activation_completed_at is not None:
        updates["activation_completed_at"] = activation_completed_at
    if credit_granted_at is not None:
        updates["credit_granted_at"] = credit_granted_at
    if reconciliation_required is not None:
        updates["reconciliation_required"] = reconciliation_required
    if len(updates) == 1:
        raise ValueError("At least one activation-state field must be provided")
    response = (
        supabase
        .table(TABLE)
        .update(updates)
        .eq("order_reference", order_reference)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise RuntimeError(f"state update returned no rows (order_reference={order_reference})")
    return rows[0]



def get_reconcilable_subscription_orders(limit: int = 100) -> list[dict]:
    """Fetch subscription orders that need reconciliation.

    Returns paid or partially-activated orders that have not yet
    reached a completed state.  The result is ordered by updated_at
    ascending so the oldest pending orders are processed first.
    """
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")

    paid_response = (
        supabase
        .table(TABLE)
        .select("*")
        .eq("status", "paid")
        .order("updated_at", desc=False)
        .limit(limit)
        .execute()
    )

    activation_response = (
        supabase
        .table(TABLE)
        .select("*")
        .in_("activation_status", list(RECONCILABLE_ACTIVATION_STATUSES))
        .order("updated_at", desc=False)
        .limit(limit)
        .execute()
    )

    flagged_response = (
        supabase
        .table(TABLE)
        .select("*")
        .eq("reconciliation_required", True)
        .order("updated_at", desc=False)
        .limit(limit)
        .execute()
    )

    paid_rows = paid_response.data or []
    activation_rows = activation_response.data or []
    flagged_rows = flagged_response.data or []

    seen_references: set[str] = set()
    merged: list[dict] = []
    exclude_statuses = frozenset({"pending", "failed", "expired"})

    for order in sorted(
        paid_rows + activation_rows + flagged_rows,
        key=lambda o: (o.get("updated_at") or "", o.get("order_reference") or ""),
    ):
        ref = order.get("order_reference")
        if not ref or ref in seen_references:
            continue

        status = (order.get("status") or "").strip().lower()
        act_status = (order.get("activation_status") or "").strip().lower()

        if status == "credited" and act_status == "completed":
            seen_references.add(ref)
            continue

        if status in exclude_statuses:
            if act_status not in RECONCILABLE_ACTIVATION_STATUSES:
                if not order.get("reconciliation_required"):
                    seen_references.add(ref)
                    continue

        seen_references.add(ref)
        merged.append(order)
        if len(merged) >= limit:
            break

    return merged


def update_subscription_order_fields(
    order_reference: str,
    reconcilation_increment: bool = False,
    **fields: Any,
) -> dict:
    """Update arbitrary allowed fields on a subscription order.

    Args:
        order_reference: The unique order reference to update.
        reconcilation_increment: If True, increments
            reconciliation_attempt_count by 1.
        **fields: Arbitrary column-value pairs to update.

    Returns:
        The updated order dictionary.
    """
    if not order_reference:
        raise ValueError("order_reference is required")

    now = _now_iso()
    updates: dict[str, Any] = {"updated_at": now}

    if reconcilation_increment:
        current = get_subscription_order_by_reference(order_reference)
        if current:
            cur_count = current.get("reconciliation_attempt_count", 0) or 0
            updates["reconciliation_attempt_count"] = cur_count + 1
            updates["last_reconciliation_at"] = now

    updates.update(fields)

    response = (
        supabase
        .table(TABLE)
        .update(updates)
        .eq("order_reference", order_reference)
        .execute()
    )

    rows = response.data or []
    if not rows:
        raise RuntimeError(f"update_subscription_order_fields: update returned no rows (order_reference={order_reference})")



VALID_ACTIVATION_TRANSITIONS: dict[str, set[str | None]] = {
    None: {"not_started"},
    "not_started": {"claimed", "conflict", "failed"},
    "claimed": {"activated", "conflict", "failed"},
    "activated": {"credit_pending", "failed"},
    "credit_pending": {"completed", "failed"},
    "completed": set(),  # terminal - no further transitions
    "conflict": set(),    # terminal - needs manual review
    "failed": set(),      # terminal - needs manual review
}


def validate_activation_transition(
    current_status: str | None,
    new_status: str | None,
    order_reference: str = "unknown",
) -> None:
    """Validate an activation status transition.

    Args:
        current_status: The current activation_status value (or None).
        new_status: The proposed new activation_status value.
        order_reference: For error messages.

    Raises:
        ValueError: If the transition is not allowed.
    """
    if new_status is None:
        return  # clearing status is always allowed

    current_key = current_status if current_status else None
    allowed = VALID_ACTIVATION_TRANSITIONS.get(current_key, set())

    if new_status not in allowed:
        raise ValueError(
            f"Invalid activation status transition for order "
            f"{order_reference!r}: {current_status!r} -> {new_status!r}. "
            f"Allowed transitions from {current_status!r}: {sorted(allowed)}"
        )

def increment_reconciliation_attempt(
    order_reference: str,
    last_error: str | None = None,
) -> dict:
    """Atomically increment reconciliation_attempt_count for an order.

    Uses the database RPC function to avoid read-then-write race conditions.
    The increment and last_reconciliation_at update happen in one atomic step.

    Args:
        order_reference: The unique order reference to update.
        last_error: Optional error text from the most recent attempt.

    Returns:
        The updated order dictionary.

    Raises:
        RuntimeError: If the RPC call fails.
    """
    if not order_reference:
        raise ValueError("order_reference is required")

    try:
        response = supabase.rpc(
            "increment_subscription_reconciliation_attempt",
            {
                "p_order_reference": order_reference,
                "p_last_error": last_error,
            },
        ).execute()
    except Exception as exc:
        raise RuntimeError(
            f"increment_reconciliation_attempt RPC failed for "
            f"order {order_reference!r}: {exc}"
        ) from exc

    rows = response.data or []
    if not rows:
        raise RuntimeError(
            f"increment_reconciliation_attempt: RPC returned no rows "
            f"(order_reference={order_reference})"
        )
    return rows[0]
