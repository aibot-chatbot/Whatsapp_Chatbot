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
    claim_subscription_activation_sequence as _claim_activation_sequence,
    update_subscription_order_activation_state as _update_activation_state,
    get_subscription_order_by_reference as _get_order_by_reference,
)
from app.database.subscription_plan_repository import (
    get_plan_by_id,
)
from app.database.company_subscription_repository import (
    update_company_subscription,
    conditional_activate_subscription,
)
from app.services.billing_service import (
    get_current_subscription,
    convert_trial_ai_configuration,
)
from app.services.ai_credit_service import (
    allocate_subscription_included_credit as _add_included_credit,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()




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
    try:
        _update_activation_state(
            order_reference=order_reference,
            activation_status="not_started",
        )
    except Exception:
        logger.warning("Could not set activation_status=not_started on order %s", order_reference)
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
    source_plan_id = order.get("source_plan_id")
    source_period_start = order.get("source_period_start")
    source_period_end = order.get("source_period_end")
    source_status = order.get("source_status")
    activation_type = order.get("activation_type")
    activation_sequence_key = order.get("activation_sequence_key")
    order_schema_version = order.get("order_schema_version")

    plan = get_plan_by_id(new_plan_id)
    if not plan:
        raise RuntimeError(f"Plan ID {new_plan_id} not found for order {order_reference!r}")

    plan_code = plan.get("code", "").lower()
    plan_included_credit = plan.get("included_ai_credit_micro_myr", 0) or 0

    now_iso = datetime.now(timezone.utc).isoformat()
    from dateutil.relativedelta import relativedelta
    period_end = datetime.now(timezone.utc) + relativedelta(months=1)
    period_end_iso = period_end.isoformat()

    # ---- Step 1: Claim activation sequence atomically ----
    # Orders with an activation_sequence_key (from 009 migration onward) get
    # the full atomic claim-first protection. Legacy orders without one fall
    # back to the old subscription-first activation path.
    _used_legacy_path = False
    if activation_sequence_key:
        try:
            _claim_activation_sequence(
                order_reference=order_reference,
                activation_sequence_key=activation_sequence_key,
            )
        except RuntimeError as exc:
            # The activation sequence is already claimed.  If this exact order
            # previously claimed it (e.g. a previous attempt failed after claiming
            # but before completing), we can detect this by checking whether the
            # order already has the key set AND is in "paid" state.
            current_order_status = (order.get("status") or "").strip().lower()
            order_current_key = order.get("activation_sequence_key")
            is_own_retry = (
                order_current_key == activation_sequence_key
                and current_order_status == "paid"
            )
            if is_own_retry:
                logger.info(
                    "Activation sequence already claimed by same order %s "
                    "(key=%s). Retrying activation for already-paid order.",
                    order_reference, activation_sequence_key,
                )
                # Fall through to Step 2 (source-state verification) rather
                # than returning activation_already_claimed, so that a
                # paid-but-not-activated order can be retried.
                pass
            else:
                logger.error(
                    "Activation sequence already claimed for order %s (key=%s). "
                    "Another order may have already activated this subscription. %s",
                    order_reference, activation_sequence_key, exc,
                )
                return {
                    "status": "activation_already_claimed",
                    "idempotent": True,
                    "order_reference": order_reference,
                    "order_status": order.get("status"),
                    "company_id": company_id,
                    "plan_code": plan_code,
                    "message": (
                        "Another order has already claimed this activation sequence. "
                        "If you believe this is an error, please contact support."
                    ),
                }

    # ---- Step 2: Validate schema version ----
    # Check the order_schema_version to determine whether this is a
    # historical order (NULL, legacy path allowed) or a modern atomic
    # order (version 2 or unknown, strict enforcement).
    _schema_ver = order_schema_version if order_schema_version is not None else None

    if _schema_ver == 2:
        # Version 2: must use atomic path. Source-state fields are required.
        if source_plan_id is None or source_status is None:
            logger.error(
                "Version 2 order %s is missing required source-state fields "
                "(source_plan_id=%s, source_status=%s). "
                "Failing closed; manual reconciliation required.",
                order_reference, source_plan_id, source_status,
            )
            return {
                "status": "malformed_atomic_order",
                "idempotent": True,
                "order_reference": order_reference,
                "order_status": order.get("status"),
                "company_id": company_id,
                "plan_code": plan_code,
                "message": (
                    "This order is marked as schema version 2 but is missing "
                    "required activation fields. Manual reconciliation required."
                ),
            }
    elif _schema_ver is None:
        # Historical pre-010 order: legacy fallback allowed
        pass
    else:
        # Unknown or unsupported version: fail closed
        logger.error(
            "Unsupported order_schema_version %s for order %s. Failing closed.",
            _schema_ver, order_reference,
        )
        return {
            "status": "unsupported_order_schema_version",
            "idempotent": True,
            "order_reference": order_reference,
            "order_status": order.get("status"),
            "company_id": company_id,
            "plan_code": plan_code,
            "message": (
                f"Order schema version {_schema_ver} is not supported. "
                "Manual reconciliation required."
            ),
        }

    # ---- Step 3: Verify source subscription still matches snapshot ----
    # Use a conditional update that requires the subscription to match
    # the state recorded at checkout time.  If another order has already
    # changed the subscription, this will fail with zero rows updated.
    if source_plan_id is not None and source_status is not None:
        try:
            conditional_activate_subscription(
                subscription_id=subscription_id,
                company_id=company_id,
                expected_plan_id=source_plan_id,
                expected_status=source_status,
                expected_period_start=source_period_start,
                expected_period_end=source_period_end,
                target_plan_id=new_plan_id,
                period_start_iso=now_iso,
                period_end_iso=period_end_iso,
            )
        except ValueError as exc:
            logger.error(
                "Source subscription state mismatch for company %d (order %s): %s",
                company_id, order_reference, exc,
            )
            raise RuntimeError(
                f"Source subscription state has changed since checkout for order "
                f"{order_reference!r}. Manual reconciliation required."
            ) from exc
    else:
        # Historical order without source-state fields: legacy fallback
        _used_legacy_path = True
        subscription_updates = {
            "plan_id": new_plan_id,
            "status": "active",
            "trial_ends_at": None,
            "current_period_start": now_iso,
            "current_period_end": period_end_iso,
            "cancelled_at": None,
            "cancellation_scheduled_at": None,
            "cancellation_effective_at": None,
            "pending_plan_id": None,
            "plan_change_effective_at": None,
        }
        try:
            update_company_subscription(
                subscription_id=subscription_id, company_id=company_id,
                updates=subscription_updates,
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to activate subscription for order {order_reference!r}: {exc}")

    logger.info(
        "Subscription activated for company %d (order %s, plan %s, seq_key=%s)",
        company_id, order_reference, plan_code, activation_sequence_key,
    )

    # ---- Step 4: Grant included AI credit ----
    # Idempotency key is tied to activation_sequence_key so two orders
    # against the same sequence key cannot both grant credit.
    if plan_included_credit > 0:
        credit_idempotency_key = f"sub_credit_{activation_sequence_key}"
        try:
            _add_included_credit(
                company_id=company_id,
                amount_micro_myr=plan_included_credit,
                idempotency_key=credit_idempotency_key,
                payment_reference=callback_txn_id,
                period_start=now_iso,
                period_end=period_end_iso,
                plan_code=plan_code,
                description=(
                    f"Subscription {plan_code} included AI credit "
                    f"(sequence {activation_sequence_key})"
                ),
            )
        except Exception as exc:
            logger.error(
                "CRITICAL: Failed to grant included AI credit for company %d "
                "(order %s, plan %s): %s. Manual reconciliation required.",
                company_id, order_reference, plan_code, exc,
            )
            try:
                _update_activation_state(
                    order_reference=order_reference,
                    activation_status="credit_pending",
                    activation_error_code="credit_grant_failed",
                    activation_error_message="AI credit grant failed. Retry will complete.",
                    reconciliation_required=True,
                )
            except Exception:
                pass
    else:
        logger.info("Plan %s has no included AI credit for company %d", plan_code, company_id)

    # ---- Step 5: Convert trial chatbot configuration ----
    try:
        convert_trial_ai_configuration(company_id, plan_code)
    except Exception as exc:
        logger.warning(
            "Trial AI configuration conversion for company %d (order %s) "
            "encountered issues: %s",
            company_id, order_reference, exc,
        )

    # ---- Step 6: Mark order credited ----
    _mark_order_credited(order_reference=order_reference, credited_at=callback_paid_at)

    _outcome = "legacy_order_activated" if _used_legacy_path else "activated_and_credited"
    return {
        "status": _outcome,
        "idempotent": False,
        "order_reference": order_reference,
        "order_status": "credited",
        "company_id": company_id,
        "plan_code": plan_code,
        "activation_sequence_key": activation_sequence_key,
        "legacy_activation": _used_legacy_path,
    }
