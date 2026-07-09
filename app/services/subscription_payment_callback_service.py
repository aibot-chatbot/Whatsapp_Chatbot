"""subscription_payment_callback_service.py - Internal callback processing for subscription payment orders.

This module processes an already-verified callback from any supported payment
gateway to:
1. Look up the matching subscription order
2. Validate the payment matches the order
3. Mark the order as paid
4. Activate the company subscription
5. Grant included AI credit
6. Convert trial chatbot configurations
7. Mark the order as credited

It does NOT verify gateway signatures, parse raw form data, or
receive a Flask request object.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from app.database.company_subscription_order_repository import (
    get_subscription_order_by_gateway_id as _get_order_by_gateway,
    update_subscription_order_status as _update_order_status,
)
from app.database.subscription_plan_repository import (
    get_plan_by_id,
)
from app.database.company_subscription_repository import (
    update_company_subscription,
)
from app.services.billing_service import (
    get_current_subscription,
    convert_trial_ai_configuration,
)
from app.services.ai_credit_service import (
    add_company_ai_credit_topup as _add_topup,
)

logger = logging.getLogger(__name__)


def process_subscription_payment_callback(normalized_callback: dict) -> dict:
    """Process an already-verified and parsed subscription payment callback.

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
        - status (str): ``"activated"`` or ``"already_activated"``
        - idempotent (bool): Whether this was an idempotent replay
        - order_reference (str or None)
        - order_status (str or None)
        - company_id (int or None)

    Raises:
        ValueError: If the callback data is invalid or the order
            does not match the payment.
        RuntimeError: If the order transition or activation fails.
    """
    payment_gateway = normalized_callback.get("payment_gateway")
    if not payment_gateway or not isinstance(payment_gateway, str):
        raise ValueError("Callback is missing required field 'payment_gateway'")

    gateway_order_id = normalized_callback.get("gateway_order_id")
    if not gateway_order_id:
        raise ValueError("Callback is missing required field 'gateway_order_id'")

    paid = normalized_callback.get("paid")
    if not isinstance(paid, bool):
        raise ValueError(f"Callback 'paid' must be a boolean, got {type(paid).__name__}")

    payment_reference = normalized_callback.get("payment_reference")
    if not payment_reference:
        raise ValueError("Callback is missing required field 'payment_reference'")

    callback_amount_sen = normalized_callback.get("amount_sen", 0)

    order = _get_order_by_gateway(
        payment_gateway=payment_gateway,
        gateway_order_id=gateway_order_id,
    )
    if order is None:
        raise ValueError(
            f"No {payment_gateway} subscription order found for gateway ID {gateway_order_id!r}"
        )

    order_reference = order.get("order_reference")
    company_id = order.get("company_id")
    order_amount_sen = order.get("amount_sen")
    order_status = order.get("status", "")
    new_plan_id = order.get("new_plan_id")
    subscription_id = order.get("subscription_id")

    if not order_reference or not company_id or not order_amount_sen or not new_plan_id:
        raise RuntimeError(
            f"Subscription order for {payment_gateway} ID {gateway_order_id!r} is missing required fields"
        )

    if paid is not True:
        logger.warning(
            "%s callback for %s (order %s) has paid=%r; skipping subscription activation",
            payment_gateway, gateway_order_id, order_reference, paid,
        )
        return {"status": "not_paid", "idempotent": False, "order_reference": order_reference, "order_status": order_status, "company_id": company_id}

    _validate_amount_match(order_amount_sen, callback_amount_sen, order_reference)

    if order_status in ("failed", "expired", "cancelled"):
        raise ValueError(
            f"Subscription order {order_reference!r} has status '{order_status}'; cannot activate"
        )

    if order_status == "credited":
        return _handle_credited_replay(
            order=order, callback_gateway_id=gateway_order_id,
            callback_txn_id=payment_reference,
        )

    if order_status in ("pending", "paid"):
        if order_status == "pending":
            _mark_order_paid(
                order_reference=order_reference,
                payment_reference=payment_reference,
                paid_at=normalized_callback.get("paid_at"),
            )
        return _activate_subscription_plan(
            order=order, callback_txn_id=payment_reference,
            callback_paid_at=normalized_callback.get("paid_at"),
            payment_gateway=payment_gateway,
        )

    raise RuntimeError(
        f"Subscription order {order_reference!r} has unrecognised status '{order_status}'"
    )


def _validate_amount_match(order_amount_sen, callback_amount_sen, order_reference):
    if order_amount_sen and callback_amount_sen:
        if callback_amount_sen < order_amount_sen:
            raise ValueError(
                f"Callback amount ({callback_amount_sen} sen) is less than order amount ({order_amount_sen} sen) for order {order_reference!r}"
            )


def _mark_order_paid(order_reference, payment_reference, paid_at=None):
    updates = {"payment_reference": payment_reference}
    if paid_at:
        updates["paid_at"] = paid_at
    _update_order_status(order_reference=order_reference, status="paid", **updates)
    logger.info("Subscription order %s marked as paid", order_reference)


def _mark_order_credited(order_reference, credited_at=None):
    updates = {}
    if credited_at:
        updates["credited_at"] = credited_at
    _update_order_status(order_reference=order_reference, status="credited", **updates)
    logger.info("Subscription order %s marked as credited", order_reference)


def _handle_credited_replay(order, callback_gateway_id, callback_txn_id):
    order_reference = order.get("order_reference")
    stored_gateway_order_id = order.get("gateway_order_id")
    stored_payment_reference = order.get("payment_reference")

    if str(stored_gateway_order_id) != str(callback_gateway_id):
        raise ValueError(
            f"Credited subscription order {order_reference!r} has gateway_order_id {stored_gateway_order_id!r} but callback gateway ID is {callback_gateway_id!r}"
        )
    if stored_payment_reference and str(stored_payment_reference) != str(callback_txn_id):
        raise ValueError(
            f"Credited subscription order {order_reference!r} has payment_reference {stored_payment_reference!r} but callback transaction_id is {callback_txn_id!r}"
        )
    logger.info("Subscription order %s is already credited; returning idempotent success", order_reference)
    return {"status": "already_activated", "idempotent": True, "order_reference": order_reference, "order_status": "credited", "company_id": order.get("company_id")}


def _activate_subscription_plan(order, callback_txn_id, callback_paid_at, payment_gateway="toyyibpay"):
    order_reference = order.get("order_reference")
    company_id = order.get("company_id")
    new_plan_id = order.get("new_plan_id")
    subscription_id = order.get("subscription_id")

    plan = get_plan_by_id(new_plan_id)
    if not plan:
        raise RuntimeError(f"Plan ID {new_plan_id} not found for order {order_reference!r}")

    plan_code = plan.get("code", "").lower()
    plan_included_credit = plan.get("included_ai_credit_micro_myr", 0) or 0

    now_iso = datetime.now(timezone.utc).isoformat()
    from dateutil.relativedelta import relativedelta
    period_end = datetime.now(timezone.utc) + relativedelta(months=1)

    subscription_updates = {
        "plan_id": new_plan_id,
        "status": "active",
        "trial_ends_at": None,
        "current_period_start": now_iso,
        "current_period_end": period_end.isoformat(),
    }

    try:
        update_company_subscription(
            subscription_id=subscription_id, company_id=company_id,
            updates=subscription_updates,
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to activate subscription for order {order_reference!r}: {exc}")

    logger.info("Subscription activated for company %d (order %s, plan %s)", company_id, order_reference, plan_code)

    if plan_included_credit > 0:
        credit_idempotency_key = f"sub_credit_{order_reference}"
        try:
            _add_topup(
                company_id=company_id, amount_micro_myr=plan_included_credit,
                idempotency_key=credit_idempotency_key,
                payment_reference=callback_txn_id,
                description=f"Subscription {plan_code} included AI credit for order {order_reference}",
            )
        except Exception as exc:
            logger.error(
                "CRITICAL: Failed to grant included AI credit for company %d (order %s, plan %s): %s. Manual reconciliation required.",
                company_id, order_reference, plan_code, exc,
            )
    else:
        logger.info("Plan %s has no included AI credit for company %d", plan_code, company_id)

    try:
        convert_trial_ai_configuration(company_id, plan_code)
    except Exception as exc:
        logger.warning("Trial AI configuration conversion for company %d (order %s) encountered issues: %s", company_id, order_reference, exc)

    _mark_order_credited(order_reference=order_reference, credited_at=callback_paid_at)

    return {"status": "activated", "idempotent": False, "order_reference": order_reference, "order_status": "credited", "company_id": company_id, "plan_code": plan_code}