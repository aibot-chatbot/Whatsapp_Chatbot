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
) -> dict:
    """Insert a new pending subscription order row."""
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
