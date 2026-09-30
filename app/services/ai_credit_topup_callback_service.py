"""ai_credit_topup_callback_service.py -- Internal generic callback processing for top-up orders.

This module processes an already-verified callback from any supported payment
gateway to:
1. Look up the matching top-up order
2. Validate the payment matches the order
3. Mark the order as paid or skip if already paid
4. Grant AI credit via the RPC
5. Mark the order as credited

It does NOT verify gateway signatures, parse raw form data, or
receive a Flask request object.
"""

import logging
from typing import Any

from app.database.ai_credit_topup_order_repository import (
    get_topup_order_by_gateway_order_id as _get_order_by_gateway,
)
from app.services.ai_credit_topup_order_service import (
    mark_order_paid as _mark_order_paid,
    mark_order_credited as _mark_order_credited,
)
from app.services.ai_credit_service import (
    add_company_ai_credit_topup as _add_topup_credit,
)

logger = logging.getLogger(__name__)

_MICRO_MYR_PER_SEN = 10_000


def process_topup_payment_callback(normalized_callback: dict) -> dict:
    """Process an already-verified and parsed payment callback.

    This function must be called only after the callback signature
    has been verified and parsed by the gateway-specific service.

    Args:
        normalized_callback: Dictionary from the gateway-specific
            ``parse_verified_callback()``. Must contain:
            - payment_gateway (str)
            - gateway_order_id (str)
            - paid (bool)
            - payment_reference (str)
            - amount_sen (int)

    Returns:
        Dictionary containing:
        - status (str): ``"credited"`` or ``"already_credited"``
        - idempotent (bool): Whether this was an idempotent replay
        - order_reference (str or None)
        - order_status (str or None)
        - credit_transaction_id (int or None)
        - company_id (int or None)
        - amount_micro_myr (int or None)

    Raises:
        ValueError: If the callback data is invalid or the order
            does not match the payment.
        RuntimeError: If the order transition or credit grant fails.
    """
    # ------------------------------------------------------------------
    # 1. Validate callback fields
    # ------------------------------------------------------------------
    payment_gateway = normalized_callback.get("payment_gateway")
    if not payment_gateway or not isinstance(payment_gateway, str):
        raise ValueError("Callback is missing required field 'payment_gateway'")

    gateway_order_id = normalized_callback.get("gateway_order_id")
    if not gateway_order_id:
        raise ValueError(
            "Callback is missing required field 'gateway_order_id'"
        )

    paid = normalized_callback.get("paid")
    if not isinstance(paid, bool):
        raise ValueError(
            f"Callback 'paid' must be a boolean, "
            f"got {type(paid).__name__}"
        )

    payment_reference = normalized_callback.get("payment_reference")
    if not payment_reference:
        raise ValueError(
            "Callback is missing required field 'payment_reference'"
        )

    # ------------------------------------------------------------------
    # 2. Resolve the callback amount in micro-MYR
    # ------------------------------------------------------------------
    callback_amount_micro_myr = _resolve_callback_amount(normalized_callback)

    # ------------------------------------------------------------------
    # 3. Look up the top-up order
    # ------------------------------------------------------------------
    order = _get_order_by_gateway(
        payment_gateway=payment_gateway,
        gateway_order_id=gateway_order_id,
    )

    if order is None:
        raise ValueError(
            f"No {payment_gateway} top-up order found for gateway ID "
            f"{gateway_order_id!r}"
        )
    order_reference = order.get("order_reference")
    company_id = order.get("company_id")
    order_amount_micro_myr = order.get("amount_micro_myr")
    order_status = order.get("status", "")
    stored_gateway_order_id = order.get("gateway_order_id")
    stored_payment_reference = order.get("payment_reference")
    stored_gateway_payment_id = order.get("gateway_payment_id")

    if not order_reference or not company_id or not order_amount_micro_myr:
        raise RuntimeError(
            f"Top-up order for {payment_gateway} ID {gateway_order_id!r} is missing "
            f"required fields (order_reference, company_id or amount_micro_myr)"
        )

    # ------------------------------------------------------------------
    # 4. Reject unpaid callbacks
    # ------------------------------------------------------------------
    if paid is not True:
        logger.warning(
            "%s callback for %s (order %s) has paid=%r; "
            "skipping credit grant",
            payment_gateway, gateway_order_id, order_reference, paid,
        )
        raise ValueError(
            f"Callback for {payment_gateway} ID {gateway_order_id!r} indicates "
            f"payment was not successful (paid={paid!r})"
        )

    # ------------------------------------------------------------------
    # 5. Validate amount matches the order
    # ------------------------------------------------------------------
    if payment_gateway == "chip" and (
        callback_amount_micro_myr is None or callback_amount_micro_myr != order_amount_micro_myr
        or order.get("gateway_environment") != "live"
    ):
        raise ValueError("CHIP live payment amount or environment does not match the order")
    # Gateway fees may cause callback total to exceed the order amount.
    # Log the callback total for auditing but do not reject the transaction.
    if callback_amount_micro_myr is not None and callback_amount_micro_myr != order_amount_micro_myr:
        logger.info(
            "Callback total %d micro-MYR differs from order amount %d micro-MYR for %s"
            " ID %s (order %s). The difference may be a gateway fee.",
            callback_amount_micro_myr, order_amount_micro_myr,
            payment_gateway, gateway_order_id, order_reference,
        )

    stored_gateway = order.get("payment_gateway", "")
    if stored_gateway != payment_gateway:
        raise ValueError(
            f"Order {order_reference!r} has payment_gateway "
            f"{stored_gateway!r} but callback is for {payment_gateway!r}"
        )

    # ------------------------------------------------------------------
    # 6. Verify callback order_id matches stored order_reference
    # ------------------------------------------------------------------
    # Match the provider-verified reference to the stored order, independently
    # of its provider ID, before any credit or status change.
    callback_order_reference = normalized_callback.get("order_reference")
    if not callback_order_reference:
        raise ValueError(
            "Callback is missing required field 'order_reference'"
        )

    stored_order_reference = order.get("order_reference")
    if not stored_order_reference:
        raise RuntimeError(
            f"Order {gateway_order_id!r} is missing order_reference"
        )

    # Normalize both to canonical UUID for comparison
    try:
        from uuid import UUID as _UUID
        canonical_callback_ref = str(_UUID(str(callback_order_reference)))
        canonical_stored_ref = str(_UUID(str(stored_order_reference)))
    except (ValueError, AttributeError) as exc:
        raise ValueError(
            f"Order reference comparison failed: {exc}"
        )

    if canonical_callback_ref != canonical_stored_ref:
        logger.error(
            "%s callback order_reference %r does not match stored "
            "order_reference %r for gateway ID %s. Rejecting.",
            payment_gateway, callback_order_reference,
            stored_order_reference, gateway_order_id,
        )
        raise ValueError(
            f"Callback order reference does not match the stored order"
        )

    # ------------------------------------------------------------------
    # 7. Handle status-based routing
    # ------------------------------------------------------------------
    callback_bill_id = gateway_order_id
    callback_txn_id = payment_reference
    callback_paid_at = normalized_callback.get("paid_at") or None

    if order_status == "pending":
        return _handle_pending_order(
            order=order,
            callback_bill_id=callback_bill_id,
            callback_txn_id=callback_txn_id,
            callback_paid_at=callback_paid_at,
        )

    elif order_status == "paid":
        return _handle_paid_order(
            order=order,
            callback_bill_id=callback_bill_id,
            callback_txn_id=callback_txn_id,
            callback_paid_at=callback_paid_at,
        )

    elif order_status == "credited":
        return _validate_credited_replay(
            order=order,
            callback_bill_id=callback_bill_id,
            callback_txn_id=callback_txn_id,
            callback_amount_micro_myr=callback_amount_micro_myr,
        )

    elif order_status == "claimed":
        raise ValueError(
            f"Order {order_reference!r} has status 'claimed' which is a "
            f"checkout-in-progress state. A callback cannot be processed "
            f"until the checkout is completed or failed."
        )

    elif order_status in ("failed", "expired", "cancelled"):
        raise ValueError(
            f"Order {order_reference!r} has status '{order_status}' and "
            f"cannot receive payment"
        )

    else:
        raise RuntimeError(
            f"Order {order_reference!r} has unknown status {order_status!r}"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_callback_amount(normalized_callback: dict) -> int:
    """Extract the callback amount in micro-MYR.

    For gateways that send cent/sen, the value is multiplied by
    ``_MICRO_MYR_PER_SEN`` (10,000).

    Raises:
        ValueError: If amount is absent, zero, boolean, or invalid.
    """
    amount_sen = normalized_callback.get("amount_sen")
    paid_amount_sen = normalized_callback.get("paid_amount_sen")

    # Prefer paid_amount_sen when it is present and valid
    if paid_amount_sen is not None and paid_amount_sen not in (0, "", "0"):
        if isinstance(paid_amount_sen, bool):
            raise ValueError("paid_amount_sen must be an integer, got bool")
        paid_int = int(paid_amount_sen)
        if paid_int <= 0:
            raise ValueError(
                f"paid_amount_sen must be a positive integer, got {paid_int}"
            )
        return paid_int * _MICRO_MYR_PER_SEN

    # Fall back to amount_sen when paid_amount_sen is genuinely absent
    if amount_sen is not None and amount_sen not in (0, "", "0"):
        if isinstance(amount_sen, bool):
            raise ValueError("amount_sen must be an integer, got bool")
        amount_int = int(amount_sen)
        if amount_int <= 0:
            raise ValueError(
                f"amount_sen must be a positive integer, got {amount_int}"
            )
        return amount_int * _MICRO_MYR_PER_SEN

    raise ValueError(
        "Callback has no valid payment amount (amount_sen or paid_amount_sen)"
    )


def _handle_pending_order(
    order: dict,
    callback_bill_id: str,
    callback_txn_id: str,
    callback_paid_at: str | None,
) -> dict:
    """Handle a callback for a pending order: mark paid, apply credit,
    mark credited."""
    order_reference = order.get("order_reference")
    company_id = order.get("company_id")
    order_amount = order.get("amount_micro_myr")
    payment_gateway = order.get("payment_gateway", "unknown")

    logger.info(
        "Order %s is pending; marking paid and granting credit",
        order_reference,
    )

    # A durable paid claim is required before credit. Storage/conflict errors
    # must remain retryable and cannot authorize fulfillment.
    _mark_order_paid(
        order_reference=order_reference,
        gateway_payment_id=callback_bill_id,
        payment_reference=callback_txn_id,
        paid_at=callback_paid_at,
    )

    return _apply_credit_and_mark_credited(
        order_reference=order_reference,
        company_id=company_id,
        amount_micro_myr=order_amount,
        callback_txn_id=callback_txn_id,
        callback_paid_at=callback_paid_at,
        payment_gateway=payment_gateway,
    )


def _handle_paid_order(
    order: dict,
    callback_bill_id: str,
    callback_txn_id: str,
    callback_paid_at: str | None,
) -> dict:
    """Handle a callback for an order already marked as paid."""
    order_reference = order.get("order_reference")
    company_id = order.get("company_id")
    order_amount = order.get("amount_micro_myr")
    payment_gateway = order.get("payment_gateway", "unknown")

    logger.info(
        "Order %s is already paid; applying credit and marking credited",
        order_reference,
    )

    return _apply_credit_and_mark_credited(
        order_reference=order_reference,
        company_id=company_id,
        amount_micro_myr=order_amount,
        callback_txn_id=callback_txn_id,
        callback_paid_at=callback_paid_at,
        payment_gateway=payment_gateway,
    )


def _validate_credited_replay(
    order: dict,
    callback_bill_id: str,
    callback_txn_id: str,
    callback_amount_micro_myr: int,
) -> dict:
    """Validate and return idempotent success for an already credited order."""
    order_reference = order.get("order_reference")
    stored_gateway_order_id = order.get("gateway_order_id")
    stored_payment_reference = order.get("payment_reference")
    stored_gateway_payment_id = order.get("gateway_payment_id")
    order_amount = order.get("amount_micro_myr")

    if str(stored_gateway_order_id) != str(callback_bill_id):
        raise ValueError(
            f"Credited order {order_reference!r} has gateway_order_id "
            f"{stored_gateway_order_id!r} but callback gateway ID is "
            f"{callback_bill_id!r}"
        )

    stored_payment_ref = stored_payment_reference or stored_gateway_payment_id
    if stored_payment_ref is not None and str(stored_payment_ref) != str(callback_txn_id):
        raise ValueError(
            f"Credited order {order_reference!r} has payment_reference "
            f"{stored_payment_ref!r} but callback transaction_id is "
            f"{callback_txn_id!r}"
        )

    if order_amount is not None and callback_amount_micro_myr is not None:
        if order_amount != callback_amount_micro_myr:
            logger.info(
                "Credited order %s callback total %d differs from order amount %d; "
                "may include gateway fee",
                order_reference, callback_amount_micro_myr, order_amount,
            )

    logger.info(
        "Order %s is already credited; returning idempotent success",
        order_reference,
    )

    return {
        "status": "already_credited",
        "idempotent": True,
        "order_reference": order_reference,
        "order_status": "credited",
        "credit_transaction_id": order.get("credit_transaction_id"),
        "company_id": order.get("company_id"),
        "amount_micro_myr": order_amount,
    }

def _send_topup_receipt(company_id: int, order_reference: str) -> None:
    """Confirm the top-up in-app and email the receipt.

    Best effort and idempotent on the notification event_key: the credit is
    already applied, so nothing here may raise, and a replay sends nothing twice.
    """
    try:
        from app.services.billing_notification_service import notify_topup_confirmed

        notify_topup_confirmed(company_id=company_id, order_reference=order_reference)
    except Exception as exc:
        logger.warning(
            "Top-up confirmation failed for order %s: %s", order_reference, type(exc).__name__
        )


def _apply_credit_and_mark_credited(
    order_reference: str,
    company_id: int,
    amount_micro_myr: int,
    callback_txn_id: str,
    callback_paid_at: str | None,
    payment_gateway: str = "unknown",
) -> dict:
    """Apply AI credit and mark the order credited."""
    credit_result = _add_topup_credit(
        company_id=company_id,
        amount_micro_myr=amount_micro_myr,
        idempotency_key=order_reference,
        payment_reference=callback_txn_id,
        description=f"{payment_gateway.title()} top-up for order {order_reference}",
    )

    credit_status = credit_result.get("status")
    credit_transaction_id = credit_result.get("transaction_id")

    if not credit_transaction_id:
        raise RuntimeError(
            f"add_company_ai_credit_topup returned no transaction_id "
            f"for order {order_reference!r} (status={credit_status!r})"
        )

    try:
        _mark_order_credited(
            order_reference=order_reference,
            credit_transaction_id=credit_transaction_id,
            credited_at=callback_paid_at,
        )
    except (ValueError, RuntimeError) as exc:
        logger.error(
            "CRITICAL: Credit applied (txn %s) for order %s but marking "
            "credited failed: %s. Manual reconciliation required.",
            credit_transaction_id, order_reference, exc,
        )
        raise RuntimeError(
            f"Reconciliation required for order {order_reference!r}: "
            f"credit transaction {credit_transaction_id} was created but "
            f"the order could not be marked credited. Please contact support."
        )

    _send_topup_receipt(company_id, order_reference)

    is_replay = credit_status == "already_applied"

    return {
        "status": "credited" if not is_replay else "already_credited",
        "idempotent": is_replay,
        "order_reference": order_reference,
        "order_status": "credited",
        "credit_transaction_id": credit_transaction_id,
        "company_id": company_id,
        "amount_micro_myr": amount_micro_myr,
    }


