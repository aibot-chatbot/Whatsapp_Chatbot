"""ai_credit_topup_order_repository.py -- Repository for AI-credit top-up order rows.

This module provides read and write access to the ``ai_credit_topup_orders``
table.  All operations use the service-role Supabase client.

No Python code in this file should call ``add_ai_credit_topup`` RPC, modify
credit balances, or manage payment gateway sessions.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from app.database.db import supabase

logger = logging.getLogger(__name__)

TABLE = "ai_credit_topup_orders"


def claim_chip_topup_checkout(order_reference, claim_token, environment, brand_id):
    """Claim once for CHIP. Never steal an expired ambiguous provider request."""
    response = (
        supabase.table(TABLE).update({
            "checkout_claim_token": claim_token, "checkout_claimed_at": _now_iso(),
            "gateway_environment": environment, "gateway_brand_id": brand_id,
            "updated_at": _now_iso(),
        })
        .eq("order_reference", order_reference).eq("payment_gateway", "chip")
        .eq("status", "pending").is_("checkout_claim_token", "null")
        .is_("gateway_order_id", "null").execute()
    )
    return _single_row(response, "claim_chip_topup_checkout")


def close_chip_topup_order(order_reference, status, reason):
    """Close a verified unpaid/test purchase without modifying a paid order."""
    if status not in {"failed", "expired", "cancelled"}:
        raise ValueError("Invalid terminal top-up status")
    response = (
        supabase.table(TABLE).update({"status": status, "failure_reason": reason,
                                      "updated_at": _now_iso()})
        .eq("order_reference", order_reference).eq("payment_gateway", "chip")
        .eq("status", "pending").execute()
    )
    return _single_row(response, "close_chip_topup_order")


def mark_chip_topup_order_for_review(order_reference, gateway_order_id):
    """Record operator review without changing payment or credit history."""
    response = (
        supabase.table(TABLE).update({
            "failure_reason": "chip_status_review", "updated_at": _now_iso(),
        })
        .eq("order_reference", order_reference).eq("payment_gateway", "chip")
        .eq("gateway_order_id", gateway_order_id).execute()
    )
    updated = _single_row(response, "mark_chip_topup_order_for_review")
    if not isinstance(updated, dict) or (
        updated.get("order_reference") != order_reference
        or updated.get("gateway_order_id") != gateway_order_id
        or updated.get("payment_gateway") != "chip"
        or updated.get("failure_reason") != "chip_status_review"
    ):
        raise RuntimeError("CHIP top-up review could not be recorded safely")
    return updated


def get_pending_chip_topup_orders(environment, brand_id, limit=100):
    response = (supabase.table(TABLE).select("*").eq("payment_gateway", "chip")
                .eq("gateway_environment", environment).eq("gateway_brand_id", brand_id)
                .in_("status", ["pending", "paid"]).order("updated_at")
                .limit(limit).execute())
    return response.data or []


def touch_chip_topup_reconciliation(order_reference):
    (supabase.table(TABLE).update({"updated_at": _now_iso()})
     .eq("order_reference", order_reference).eq("payment_gateway", "chip")
     .in_("status", ["pending", "paid"]).execute())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _single_row(response: Any, label: str) -> dict | None:
    """Return the first row or None. Raise RuntimeError for unexpected shape."""
    data = response.data if hasattr(response, "data") else response
    if data is None:
        return None
    if isinstance(data, list):
        return data[0] if data else None
    raise RuntimeError(
        f"Unexpected response shape from {TABLE}.{label}: {type(data).__name__}"
    )


# ---------------------------------------------------------------------------
# Read functions
# ---------------------------------------------------------------------------


def get_topup_order_by_reference(order_reference: str) -> dict | None:
    """Fetch a single top-up order by its unique order reference."""
    if not order_reference:
        return None

    response = (
        supabase
        .table(TABLE)
        .select("*")
        .eq("order_reference", order_reference)
        .limit(1)
        .execute()
    )
    return _single_row(response, "get_topup_order_by_reference")


def get_topup_order_by_idempotency_key(idempotency_key: str) -> dict | None:
    """Fetch a single top-up order by its idempotency key."""
    if not idempotency_key:
        return None

    response = (
        supabase
        .table(TABLE)
        .select("*")
        .eq("idempotency_key", idempotency_key)
        .limit(1)
        .execute()
    )
    return _single_row(response, "get_topup_order_by_idempotency_key")


def get_topup_order_by_gateway_order_id(
    payment_gateway: str,
    gateway_order_id: str,
) -> dict | None:
    """Fetch a single top-up order by its gateway and gateway order ID."""
    if not payment_gateway or not gateway_order_id:
        return None

    response = (
        supabase
        .table(TABLE)
        .select("*")
        .eq("payment_gateway", payment_gateway)
        .eq("gateway_order_id", gateway_order_id)
        .limit(1)
        .execute()
    )
    return _single_row(response, "get_topup_order_by_gateway_order_id")


# ---------------------------------------------------------------------------
def get_topup_order_by_reference_and_company(
    order_reference: str,
    company_id: int,
) -> dict | None:
    """Fetch a single top-up order by its reference and company ID.

    Returns the order row only when both the reference and the company
    match, enforcing company-level isolation.
    """
    if not order_reference or not company_id:
        return None

    response = (
        supabase
        .table(TABLE)
        .select('*')
        .eq('order_reference', order_reference)
        .eq('company_id', company_id)
        .limit(1)
        .execute()
    )
    return _single_row(response, 'get_topup_order_by_reference_and_company')

# Write functions
# ---------------------------------------------------------------------------


def create_topup_order(
    order_reference: str,
    company_id: int,
    subscription_id: int,
    created_by_user_id: int,
    amount_micro_myr: int,
    currency: str,
    payment_gateway: str,
    idempotency_key: str,
    expires_at: str | None = None,
) -> dict:
    """Insert a new pending top-up order row.

    Args:
        order_reference: Unique order reference string.
        company_id: Company making the top-up.
        subscription_id: Current subscription ID.
        created_by_user_id: Authenticated user who initiated the order.
        amount_micro_myr: Amount in micro-MYR (positive integer).
        currency: Currency code (must be "MYR").
        payment_gateway: Payment gateway name ("chip" for new checkouts).
        idempotency_key: Unique key for duplicate protection.
        expires_at: Optional ISO-8601 timestamp for order expiry.

    Returns:
        The newly created order row dictionary.
    """
    payload = {
        "order_reference": order_reference,
        "company_id": company_id,
        "subscription_id": subscription_id,
        "created_by_user_id": created_by_user_id,
        "amount_micro_myr": amount_micro_myr,
        "currency": currency,
        "payment_gateway": payment_gateway,
        "idempotency_key": idempotency_key,
        "status": "pending",
        "expires_at": expires_at,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }

    response = (
        supabase
        .table(TABLE)
        .insert(payload)
        .execute()
    )

    rows = response.data or []
    if not rows:
        raise RuntimeError(
            f"create_topup_order returned no data for order_reference={order_reference!r}"
        )
    return rows[0]


def update_topup_order_gateway_details(
    order_reference: str,
    gateway_order_id: str,
    checkout_url: str | None = None,
    expires_at: str | None = None,
) -> dict:
    """Update gateway-specific fields on a pending order.

    Does not change the order status.

    Args:
        order_reference: The unique order reference.
        gateway_order_id: Gateway-side order/checkout ID.
        checkout_url: Optional checkout URL to redirect the user.
        expires_at: Optional updated expiry timestamp.

    Returns:
        The updated order row dictionary.

    Raises:
        RuntimeError: If the order is not found.
    """
    payload: dict[str, Any] = {
        "gateway_order_id": gateway_order_id,
        "updated_at": _now_iso(),
    }
    if checkout_url is not None:
        payload["checkout_url"] = checkout_url
    if expires_at is not None:
        payload["expires_at"] = expires_at

    response = (
        supabase
        .table(TABLE)
        .update(payload)
        .eq("order_reference", order_reference)
        .eq("status", "pending")
        .execute()
    )

    rows = response.data or []
    if not rows:
        existing = get_topup_order_by_reference(order_reference)
        if existing:
            raise RuntimeError(
                f"Cannot update gateway details for order {order_reference!r}: "
                f"current status is {existing.get('status')!r}, expected 'pending'"
            )
        raise RuntimeError(
            f"update_topup_order_gateway_details: order {order_reference!r} not found"
        )
    return rows[0]


def mark_topup_order_paid(
    order_reference: str,
    gateway_payment_id: str,
    payment_reference: str,
    paid_at: str,
) -> dict:
    """Transition a pending order to paid status.

    Args:
        order_reference: The unique order reference.
        gateway_payment_id: Gateway-side payment ID.
        payment_reference: External payment reference (e.g. gateway TXN ID).
        paid_at: ISO-8601 timestamp of when the payment was confirmed.

    Returns:
        The updated order row dictionary.

    Raises:
        RuntimeError: If the order is not found or not in a transitionable state.
    """
    payload = {
        "status": "paid",
        "gateway_payment_id": gateway_payment_id,
        "payment_reference": payment_reference,
        "paid_at": paid_at,
        "updated_at": _now_iso(),
    }

    response = (
        supabase
        .table(TABLE)
        .update(payload)
        .eq("order_reference", order_reference)
        .eq("status", "pending")
        .execute()
    )

    rows = response.data or []
    if not rows:
        existing = get_topup_order_by_reference(order_reference)
        if existing:
            current = existing.get("status")
            # Idempotent: already paid with identical details
            if current == "paid":
                if (existing.get("gateway_payment_id") == gateway_payment_id
                        and existing.get("payment_reference") == payment_reference):
                    return existing
            raise RuntimeError(
                f"Cannot mark order {order_reference!r} paid: "
                f"current status is {current!r}"
            )
        raise RuntimeError(
            f"mark_topup_order_paid: order {order_reference!r} not found"
        )
    return rows[0]


def mark_topup_order_credited(
    order_reference: str,
    credit_transaction_id: int,
    credited_at: str,
) -> dict:
    """Transition a paid order to credited status.

    Args:
        order_reference: The unique order reference.
        credit_transaction_id: The ``ai_credit_transactions`` row ID.
        credited_at: ISO-8601 timestamp of when credit was granted.

    Returns:
        The updated order row dictionary.

    Raises:
        RuntimeError: If the order is not found or not in a transitionable state.
    """
    payload = {
        "status": "credited",
        "credit_transaction_id": credit_transaction_id,
        "credited_at": credited_at,
        "updated_at": _now_iso(),
    }

    response = (
        supabase
        .table(TABLE)
        .update(payload)
        .eq("order_reference", order_reference)
        .eq("status", "paid")
        .execute()
    )

    rows = response.data or []
    if not rows:
        existing = get_topup_order_by_reference(order_reference)
        if existing:
            current = existing.get("status")
            # Idempotent: already credited with the same transaction
            if current == "credited":
                if existing.get("credit_transaction_id") == credit_transaction_id:
                    return existing
            raise RuntimeError(
                f"Cannot mark order {order_reference!r} credited: "
                f"current status is {current!r}"
            )
        raise RuntimeError(
            f"mark_topup_order_credited: order {order_reference!r} not found"
        )
    return rows[0]


def mark_topup_order_failed(
    order_reference: str,
    failure_reason: str | None = None,
) -> dict:
    """Transition a pending order to failed status.

    Args:
        order_reference: The unique order reference.
        failure_reason: Optional description of why the order failed.

    Returns:
        The updated order row dictionary.

    Raises:
        RuntimeError: If the order is not found or not in a transitionable state.
    """
    payload: dict[str, Any] = {
        "status": "failed",
        "failed_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    if failure_reason is not None:
        payload["failure_reason"] = failure_reason

    response = (
        supabase
        .table(TABLE)
        .update(payload)
        .eq("order_reference", order_reference)
        .eq("status", "pending")
        .execute()
    )

    rows = response.data or []
    if not rows:
        existing = get_topup_order_by_reference(order_reference)
        if existing:
            current = existing.get("status")
            raise RuntimeError(
                f"Cannot mark order {order_reference!r} failed: "
                f"current status is {current!r}"
            )
        raise RuntimeError(
            f"mark_topup_order_failed: order {order_reference!r} not found"
        )
    return rows[0]


def mark_topup_order_expired(order_reference: str) -> dict:
    """Transition a pending order to expired status.

    Args:
        order_reference: The unique order reference.

    Returns:
        The updated order row dictionary.

    Raises:
        RuntimeError: If the order is not found or not in a transitionable state.
    """
    payload = {
        "status": "expired",
        "failed_at": _now_iso(),
        "updated_at": _now_iso(),
    }

    response = (
        supabase
        .table(TABLE)
        .update(payload)
        .eq("order_reference", order_reference)
        .eq("status", "pending")
        .execute()
    )

    rows = response.data or []
    if not rows:
        existing = get_topup_order_by_reference(order_reference)
        if existing:
            current = existing.get("status")
            raise RuntimeError(
                f"Cannot mark order {order_reference!r} expired: "
                f"current status is {current!r}"
            )
        raise RuntimeError(
            f"mark_topup_order_expired: order {order_reference!r} not found"
        )
    return rows[0]


def mark_topup_order_cancelled(order_reference: str) -> dict:
    """Transition a pending order to cancelled status.

    Args:
        order_reference: The unique order reference.

    Returns:
        The updated order row dictionary.

    Raises:
        RuntimeError: If the order is not found or not in a transitionable state.
    """
    payload = {
        "status": "cancelled",
        "updated_at": _now_iso(),
    }

    response = (
        supabase
        .table(TABLE)
        .update(payload)
        .eq("order_reference", order_reference)
        .eq("status", "pending")
        .execute()
    )

    rows = response.data or []
    if not rows:
        existing = get_topup_order_by_reference(order_reference)
        if existing:
            current = existing.get("status")
            raise RuntimeError(
                f"Cannot mark order {order_reference!r} cancelled: "
                f"current status is {current!r}"
            )
        raise RuntimeError(
            f"mark_topup_order_cancelled: order {order_reference!r} not found"
        )
    return rows[0]
# ---------------------------------------------------------------------------
# Atomic checkout-claim RPC wrappers
# ---------------------------------------------------------------------------


def claim_topup_checkout(
    order_reference: str,
    claim_token: str,
    claim_timeout_seconds: int = 300,
) -> dict:
    """Atomically claim a pending top-up order for checkout processing.

    Calls the ``claim_ai_credit_topup_checkout`` RPC, which tries to
    transition a ``pending`` order into a ``claimed`` state.  If another
    process has already claimed the order, the RPC returns no rows and
    this function raises ``RuntimeError``.

    Args:
        order_reference: The order to claim.
        claim_token: Unique token that identifies this checkout attempt.
        claim_timeout_seconds: Seconds before the claim expires
            (default 300).

    Returns:
        The claimed order row dictionary.

    Raises:
        ValueError: If inputs are invalid.
        RuntimeError: If the RPC returns no data (order not found or
            already claimed by another process).
    """
    if not order_reference or not isinstance(order_reference, str) or not order_reference.strip():
        raise ValueError("order_reference must be a non-empty string")
    if not claim_token or not isinstance(claim_token, str) or not claim_token.strip():
        raise ValueError("claim_token must be a non-empty string")
    if not isinstance(claim_timeout_seconds, int) or claim_timeout_seconds < 1:
        raise ValueError(
            f"claim_timeout_seconds must be a positive integer, "
            f"got {claim_timeout_seconds!r}"
        )

    result = supabase.rpc(
        "claim_ai_credit_topup_checkout",
        {
            "p_order_reference": order_reference.strip(),
            "p_claim_token": claim_token.strip(),
            "p_claim_timeout_seconds": claim_timeout_seconds,
        },
    ).execute()

    data = result.data
    if not data or not isinstance(data, list) or len(data) == 0:
        raise RuntimeError(
            f"claim_topup_checkout failed for order_reference={order_reference!r}: "
            "order not found, already claimed, or RPC returned no data"
        )

    row = data[0]
    if not isinstance(row, dict):
        raise RuntimeError(
            f"claim_topup_checkout returned unexpected type for "
            f"order_reference={order_reference!r}: {type(row).__name__}"
        )

    return row


def complete_topup_checkout(
    order_reference: str,
    claim_token: str,
    gateway_order_id: str,
    checkout_url: str,
    expires_at: str | None = None,
) -> dict:
    """Complete a claimed top-up checkout with payment gateway details.

    Calls the ``complete_ai_credit_topup_checkout`` RPC, which
    checks a pending order's claim token and stores the
    gateway bill ID and checkout URL.

    Args:
        order_reference: The claimed order.
        claim_token: The token used when claiming the order.
        gateway_order_id: payment bill ID.
        checkout_url: payment checkout URL.
        expires_at: Optional ISO-8601 expiry timestamp.

    Returns:
        The updated order row dictionary.

    Raises:
        ValueError: If inputs are invalid.
        RuntimeError: If the RPC returns no data (claim token mismatch
            or order in an unexpected state).
    """
    if not order_reference or not isinstance(order_reference, str) or not order_reference.strip():
        raise ValueError("order_reference must be a non-empty string")
    if not claim_token or not isinstance(claim_token, str) or not claim_token.strip():
        raise ValueError("claim_token must be a non-empty string")
    if not gateway_order_id or not isinstance(gateway_order_id, str) or not gateway_order_id.strip():
        raise ValueError("gateway_order_id must be a non-empty string")
    if not checkout_url or not isinstance(checkout_url, str) or not checkout_url.strip():
        raise ValueError("checkout_url must be a non-empty string")

    result = supabase.rpc(
        "complete_ai_credit_topup_checkout",
        {
            "p_order_reference": order_reference.strip(),
            "p_claim_token": claim_token.strip(),
            "p_gateway_order_id": gateway_order_id.strip(),
            "p_checkout_url": checkout_url.strip(),
            "p_expires_at": expires_at,
        },
    ).execute()

    data = result.data
    if not data or not isinstance(data, list) or len(data) == 0:
        raise RuntimeError(
            f"complete_topup_checkout failed for order_reference={order_reference!r}: "
            "claim token mismatch, order not found, or RPC returned no data"
        )

    row = data[0]
    if not isinstance(row, dict):
        raise RuntimeError(
            f"complete_topup_checkout returned unexpected type for "
            f"order_reference={order_reference!r}: {type(row).__name__}"
        )

    return row


def fail_topup_checkout(
    order_reference: str,
    claim_token: str,
    failure_reason: str | None = None,
) -> dict:
    """Fail a claimed top-up checkout.

    Calls the ``fail_ai_credit_topup_checkout`` RPC, which transitions
    a claimed pending order to ``failed`` and stores the failure reason.

    Args:
        order_reference: The claimed order.
        claim_token: The token used when claiming the order.
        failure_reason: Optional description of why it failed.

    Returns:
        The updated order row dictionary.

    Raises:
        ValueError: If inputs are invalid.
        RuntimeError: If the RPC returns no data (claim token mismatch
            or order in an unexpected state).
    """
    if not order_reference or not isinstance(order_reference, str) or not order_reference.strip():
        raise ValueError("order_reference must be a non-empty string")
    if not claim_token or not isinstance(claim_token, str) or not claim_token.strip():
        raise ValueError("claim_token must be a non-empty string")

    result = supabase.rpc(
        "fail_ai_credit_topup_checkout",
        {
            "p_order_reference": order_reference.strip(),
            "p_claim_token": claim_token.strip(),
            "p_failure_reason": failure_reason,
        },
    ).execute()

    data = result.data
    if not data or not isinstance(data, list) or len(data) == 0:
        raise RuntimeError(
            f"fail_topup_checkout failed for order_reference={order_reference!r}: "
            "claim token mismatch, order not found, or RPC returned no data"
        )

    row = data[0]
    if not isinstance(row, dict):
        raise RuntimeError(
            f"fail_topup_checkout returned unexpected type for "
            f"order_reference={order_reference!r}: {type(row).__name__}"
        )

    return row
