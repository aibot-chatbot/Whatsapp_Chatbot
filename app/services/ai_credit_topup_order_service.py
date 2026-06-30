"""ai_credit_topup_order_service.py -- Service layer for AI-credit top-up order management.

This module sits between routes and the top-up order repository.  It enforces
business rules, input validation, and status-transition logic.

No browser-controlled endpoint is added by this module.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from app.database.ai_credit_topup_order_repository import (
    get_topup_order_by_reference as _repo_get_by_reference,
    get_topup_order_by_idempotency_key as _repo_get_by_idempotency_key,
    create_topup_order as _repo_create,
    update_topup_order_gateway_details as _repo_update_gateway,
    mark_topup_order_paid as _repo_mark_paid,
    mark_topup_order_credited as _repo_mark_credited,
    mark_topup_order_failed as _repo_mark_failed,
    mark_topup_order_expired as _repo_mark_expired,
    mark_topup_order_cancelled as _repo_mark_cancelled,
)

logger = logging.getLogger(__name__)

_ACCEPTED_PENDING_STATUSES = frozenset({"pending"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_order_reference(ref: str, label: str = "order_reference"):
    if not ref or not isinstance(ref, str) or not ref.strip():
        raise ValueError(f"{label} must be a non-empty string")


def _validate_positive_int(value: Any, label: str):
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer, got {value!r}")


def _validate_non_empty_str(value: Any, label: str):
    if not value or not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


# ---------------------------------------------------------------------------
# Create pending order
# ---------------------------------------------------------------------------


def create_pending_topup_order(
    company_id: int,
    subscription_id: int,
    created_by_user_id: int,
    amount_micro_myr: int,
    payment_gateway: str,
    idempotency_key: str,
    expires_at: str | None = None,
) -> dict:
    """Create a new pending top-up order.

    Validates all inputs, checks for an existing order with the same
    idempotency key, and either returns the existing matching order or
    creates a new one.

    Idempotency behaviour:
        - Same idempotency key with matching company, amount and gateway
          ? returns the existing order (no error).
        - Same idempotency key with conflicting values
          ? raises ValueError.

    Args:
        company_id: Company making the top-up.
        subscription_id: Current subscription ID.
        created_by_user_id: Authenticated user ID.
        amount_micro_myr: Amount in micro-MYR (positive integer).
        payment_gateway: Payment gateway name.
        idempotency_key: Unique key for duplicate protection.
        expires_at: Optional ISO-8601 expiry timestamp.

    Returns:
        The order row dictionary (newly created or existing matching).

    Raises:
        ValueError: If any input is invalid or idempotency conflict exists.
        RuntimeError: If the repository operation fails.
    """
    _validate_positive_int(company_id, "company_id")
    _validate_positive_int(subscription_id, "subscription_id")
    _validate_positive_int(created_by_user_id, "created_by_user_id")
    _validate_positive_int(amount_micro_myr, "amount_micro_myr")
    _validate_non_empty_str(payment_gateway, "payment_gateway")
    _validate_non_empty_str(idempotency_key, "idempotency_key")

    # Check existing idempotency key
    existing = _repo_get_by_idempotency_key(idempotency_key.strip())
    if existing is not None:
        if (existing.get("company_id") == company_id
                and existing.get("amount_micro_myr") == amount_micro_myr
                and existing.get("payment_gateway") == payment_gateway):
            return existing
        raise ValueError(
            f"Idempotency key {idempotency_key!r} already exists with "
            f"conflicting company, amount or gateway"
        )

    # Generate a unique order reference
    order_reference = _generate_order_reference(company_id)

    created = _repo_create(
        order_reference=order_reference,
        company_id=company_id,
        subscription_id=subscription_id,
        created_by_user_id=created_by_user_id,
        amount_micro_myr=amount_micro_myr,
        currency="MYR",
        payment_gateway=payment_gateway.strip(),
        idempotency_key=idempotency_key.strip(),
        expires_at=expires_at,
    )

    return created


# ---------------------------------------------------------------------------
# Gateway details
# ---------------------------------------------------------------------------


def update_gateway_details(
    order_reference: str,
    gateway_order_id: str,
    checkout_url: str | None = None,
    expires_at: str | None = None,
) -> dict:
    """Attach gateway-side order details to a pending order.

    Args:
        order_reference: The unique order reference.
        gateway_order_id: Gateway-side order/checkout ID.
        checkout_url: Optional checkout URL.
        expires_at: Optional updated expiry timestamp.

    Returns:
        The updated order row dictionary.
    """
    _validate_order_reference(order_reference)
    _validate_non_empty_str(gateway_order_id, "gateway_order_id")

    return _repo_update_gateway(
        order_reference=order_reference.strip(),
        gateway_order_id=gateway_order_id.strip(),
        checkout_url=checkout_url,
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------------
# Mark paid
# ---------------------------------------------------------------------------


def mark_order_paid(
    order_reference: str,
    gateway_payment_id: str,
    payment_reference: str,
    paid_at: str | None = None,
) -> dict:
    """Transition a pending order to paid status.

    Idempotent: calling with the same gateway_payment_id and
    payment_reference on an already-paid order returns the existing
    order without error.

    Args:
        order_reference: The unique order reference.
        gateway_payment_id: Gateway-side payment ID.
        payment_reference: External payment reference.
        paid_at: ISO-8601 timestamp (defaults to now if omitted).

    Returns:
        The updated order row dictionary.

    Raises:
        ValueError: If inputs are invalid.
        RuntimeError: If the status transition is not allowed.
    """
    _validate_order_reference(order_reference)
    _validate_non_empty_str(gateway_payment_id, "gateway_payment_id")
    _validate_non_empty_str(payment_reference, "payment_reference")

    timestamp = paid_at if paid_at else _now_iso()

    return _repo_mark_paid(
        order_reference=order_reference.strip(),
        gateway_payment_id=gateway_payment_id.strip(),
        payment_reference=payment_reference.strip(),
        paid_at=timestamp,
    )


# ---------------------------------------------------------------------------
# Mark credited
# ---------------------------------------------------------------------------


def mark_order_credited(
    order_reference: str,
    credit_transaction_id: int,
    credited_at: str | None = None,
) -> dict:
    """Transition a paid order to credited status.

    Idempotent: calling with the same credit_transaction_id on an
    already-credited order returns the existing order without error.

    Args:
        order_reference: The unique order reference.
        credit_transaction_id: The ``ai_credit_transactions`` row ID.
        credited_at: ISO-8601 timestamp (defaults to now if omitted).

    Returns:
        The updated order row dictionary.

    Raises:
        ValueError: If inputs are invalid.
        RuntimeError: If the status transition is not allowed.
    """
    _validate_order_reference(order_reference)
    _validate_positive_int(credit_transaction_id, "credit_transaction_id")

    timestamp = credited_at if credited_at else _now_iso()

    return _repo_mark_credited(
        order_reference=order_reference.strip(),
        credit_transaction_id=credit_transaction_id,
        credited_at=timestamp,
    )


# ---------------------------------------------------------------------------
# Failure states
# ---------------------------------------------------------------------------


def mark_order_failed(
    order_reference: str,
    failure_reason: str | None = None,
) -> dict:
    """Transition a pending order to failed status.

    Args:
        order_reference: The unique order reference.
        failure_reason: Optional description of the failure.

    Returns:
        The updated order row dictionary.
    """
    _validate_order_reference(order_reference)
    return _repo_mark_failed(
        order_reference=order_reference.strip(),
        failure_reason=failure_reason,
    )


def mark_order_expired(order_reference: str) -> dict:
    """Transition a pending order to expired status.

    Args:
        order_reference: The unique order reference.

    Returns:
        The updated order row dictionary.
    """
    _validate_order_reference(order_reference)
    return _repo_mark_expired(order_reference=order_reference.strip())


def mark_order_cancelled(order_reference: str) -> dict:
    """Transition a pending order to cancelled status.

    Args:
        order_reference: The unique order reference.

    Returns:
        The updated order row dictionary.
    """
    _validate_order_reference(order_reference)
    return _repo_mark_cancelled(order_reference=order_reference.strip())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _generate_order_reference(company_id: int) -> str:
    """Generate a unique order reference string.

    Format: ``TOPUP-{company_id}-{timestamp_nonce}``

    This is a simple unique reference generator.  A production system
    should use a dedicated service for guaranteed uniqueness.
    """
    nonce = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"TOPUP-{company_id}-{nonce}"
# ---------------------------------------------------------------------------
# Checkout-claim service wrappers
# ---------------------------------------------------------------------------

# These are imported lazily just before use so that the module can be
# compiled even when the repository does not yet define them.


def _repo_claim_checkout() -> Any:
    from app.database.ai_credit_topup_order_repository import (
        claim_topup_checkout as _r,
    )
    return _r


def _repo_complete_checkout() -> Any:
    from app.database.ai_credit_topup_order_repository import (
        complete_topup_checkout as _r,
    )
    return _r


def _repo_fail_checkout() -> Any:
    from app.database.ai_credit_topup_order_repository import (
        fail_topup_checkout as _r,
    )
    return _r


def _validate_positive_int_strict(value: Any, label: str) -> None:
    """Validate a positive integer, rejecting bool values.

    Python's ``bool`` is a subclass of ``int``, so ``isinstance(True, int)``
    is ``True``.  This helper explicitly rejects booleans.
    """
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer, got boolean {value!r}")
    _validate_positive_int(value, label)


def _validate_strict_timeout(timeout: Any) -> None:
    """Validate a checkout claim timeout."""
    _validate_positive_int_strict(timeout, "claim_timeout_seconds")
    if timeout < 30 or timeout > 3600:
        raise ValueError(
            f"claim_timeout_seconds must be between 30 and 3600, got {timeout}"
        )


def claim_checkout_creation(
    order_reference: str,
    claim_token: str,
    claim_timeout_seconds: int = 300,
) -> dict:
    """Atomically claim a pending top-up order for checkout processing.

    This is the service-layer wrapper around
    :func:`claim_topup_checkout() <app.database.ai_credit_topup_order_repository.claim_topup_checkout>`.

    Args:
        order_reference: The order to claim.
        claim_token: Unique token identifying this checkout attempt.
        claim_timeout_seconds: Seconds before the claim expires
            (between 30 and 3600, default 300).

    Returns:
        Normalized dictionary:
        - ``claimed`` (bool)
        - ``reason`` (str)
        - ``order_id`` (int or None)
        - ``order_reference`` (str or None)
        - ``status`` (str or None)
        - ``gateway_order_id`` (str or None)
        - ``checkout_url`` (str or None)
        - ``active_claim_token`` (str or None)
        - ``claimed_at`` (str or None)

    Raises:
        ValueError: If any input is invalid.
    """
    _validate_non_empty_str(order_reference, "order_reference")
    _validate_non_empty_str(claim_token, "claim_token")
    _validate_strict_timeout(claim_timeout_seconds)

    row = _repo_claim_checkout()(
        order_reference=order_reference.strip(),
        claim_token=claim_token.strip(),
        claim_timeout_seconds=claim_timeout_seconds,
    )

    if not isinstance(row, dict):
        raise RuntimeError(
            f"claim_checkout_creation: repository returned a non-dictionary "
            f"result for order_reference={order_reference!r}"
        )

    claimed_value = row.get("claimed")
    if not isinstance(claimed_value, bool):
        raise RuntimeError(
            f"claim_checkout_creation: repository returned malformed result: "
            f"'claimed' must be a boolean, got {type(claimed_value).__name__}"
        )

    reason = row.get("reason")
    if not reason or not isinstance(reason, str) or not reason.strip():
        raise RuntimeError(
            f"claim_checkout_creation: repository returned malformed result: "
            f"'reason' must be a non-empty string for "
            f"order_reference={order_reference!r}"
        )

    return {
        "claimed": claimed_value,
        "reason": reason.strip(),
        "order_id": row.get("order_id"),
        "order_reference": row.get("returned_order_reference"),
        "status": row.get("order_status"),
        "gateway_order_id": row.get("returned_gateway_order_id"),
        "checkout_url": row.get("returned_checkout_url"),
        "active_claim_token": row.get("active_claim_token"),
        "claimed_at": row.get("claimed_at"),
    }


def complete_checkout_creation(
    order_reference: str,
    claim_token: str,
    gateway_order_id: str,
    checkout_url: str,
    expires_at: str | None = None,
) -> dict:
    """Complete a claimed checkout by storing Billplz gateway details.

    This is the service-layer wrapper around
    :func:`complete_topup_checkout() <app.database.ai_credit_topup_order_repository.complete_topup_checkout>`.

    Args:
        order_reference: The claimed order.
        claim_token: The token used when claiming.
        gateway_order_id: Billplz bill ID.
        checkout_url: Billplz checkout URL.
        expires_at: Optional ISO-8601 expiry timestamp.

    Returns:
        The completed order row dictionary.

    Raises:
        ValueError: If any input is invalid.
        RuntimeError: If the repository operation fails.
    """
    _validate_non_empty_str(order_reference, "order_reference")
    _validate_non_empty_str(claim_token, "claim_token")
    _validate_non_empty_str(gateway_order_id, "gateway_order_id")
    _validate_non_empty_str(checkout_url, "checkout_url")

    return _repo_complete_checkout()(
        order_reference=order_reference.strip(),
        claim_token=claim_token.strip(),
        gateway_order_id=gateway_order_id.strip(),
        checkout_url=checkout_url.strip(),
        expires_at=expires_at,
    )


def fail_checkout_creation(
    order_reference: str,
    claim_token: str,
    failure_reason: str | None = None,
) -> dict:
    """Fail a claimed checkout.

    This is the service-layer wrapper around
    :func:`fail_topup_checkout() <app.database.ai_credit_topup_order_repository.fail_topup_checkout>`.

    Args:
        order_reference: The claimed order.
        claim_token: The token used when claiming.
        failure_reason: Optional description of why it failed
            (limited to 500 characters; empty becomes None).

    Returns:
        The failed order row dictionary.

    Raises:
        ValueError: If order reference or claim token is invalid.
        RuntimeError: If the repository operation fails.
    """
    _validate_non_empty_str(order_reference, "order_reference")
    _validate_non_empty_str(claim_token, "claim_token")

    reason = _normalize_failure_reason(failure_reason)

    return _repo_fail_checkout()(
        order_reference=order_reference.strip(),
        claim_token=claim_token.strip(),
        failure_reason=reason,
    )


# ---------------------------------------------------------------------------
# Failure-reason helpers
# ---------------------------------------------------------------------------


def _normalize_failure_reason(reason: str | None) -> str | None:
    """Normalise an optional failure reason string.

    * ``None``, empty or whitespace-only ? ``None``.
    * Longer than 500 characters ? truncated to 500.
    * Otherwise ? stripped.
    """
    if reason is None:
        return None
    if not isinstance(reason, str):
        return str(reason)[:500] if reason else None
    cleaned = reason.strip()
    if not cleaned:
        return None
    return cleaned[:500]

