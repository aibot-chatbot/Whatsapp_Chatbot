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
from uuid import UUID

from app.database.company_subscription_order_repository import (
    get_subscription_order_by_gateway_id as _get_order_by_gateway,
    mark_pending_subscription_order_paid as _mark_pending_order_paid,
    update_subscription_order_status as _repository_update_order_status,
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
from app.services.billing_period_service import (
    calculate_current_period_end,
    validate_current_period,
)
from app.services.ai_credit_service import (
    ensure_company_ai_credit as _ensure_company_ai_credit,
)

logger = logging.getLogger(__name__)

NULL_SOURCE_PERIOD_END_ACTIVATION_SENTINEL = "null-period-end"


def _update_order_status(order_reference: str, status: str, **extra):
    """Keep existing callers while making the payment claim compare-and-set."""
    if status == "paid":
        return _mark_pending_order_paid(
            order_reference=order_reference,
            payment_reference=extra["payment_reference"],
            paid_at=extra.get("paid_at"),
        )
    return _repository_update_order_status(
        order_reference=order_reference, status=status, **extra
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_null_source_period_recovery_order(order: dict) -> bool:
    """Return True when a version-2 renewal order explicitly captured NULL."""
    company_id = order.get("company_id")
    activation_sequence_key = order.get("activation_sequence_key")
    return (
        order.get("order_schema_version") == 2
        and (order.get("activation_type") or "").strip().lower() == "renewal"
        and order.get("source_period_end") is None
        and activation_sequence_key
        == f"company:{company_id}:renewal-after:{NULL_SOURCE_PERIOD_END_ACTIVATION_SENTINEL}"
    )




def process_subscription_payment_callback(normalized_callback: dict) -> dict:
    """Process an already-verified and parsed subscription payment callback.

    This function must be called only after the callback signature
    has been verified and parsed by the gateway-specific service.

    Args:
        normalized_callback: Dictionary from the gateway-specific
            ``parse_verified_callback()``. Must contain:
            - payment_gateway (str)
            - gateway_order_id (str)
            - order_reference (str): the gateway-signed order id, cross-checked
              against the order located by gateway_order_id
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

    if payment_gateway == "chip" and order.get("gateway_environment") != "live":
        raise ValueError("CHIP test orders cannot grant subscription entitlements")

    # Match the provider-verified reference to the order found by gateway ID.
    # Check before all status branches so replays cannot name another order.
    callback_order_reference = normalized_callback.get("order_reference")
    if not callback_order_reference:
        raise ValueError("Callback is missing required field 'order_reference'")

    # Production references are uuid4 (subscription_checkout_service), so
    # canonicalise when both sides parse - that absorbs case and hyphenation
    # differences. Anything else falls back to an exact match rather than
    # imposing a format this function never promised.
    def _canonical(value):
        try:
            return str(UUID(str(value)))
        except (ValueError, AttributeError, TypeError):
            return str(value).strip()

    canonical_callback_ref = _canonical(callback_order_reference)
    canonical_stored_ref = _canonical(order_reference)

    if canonical_callback_ref != canonical_stored_ref:
        logger.error(
            "%s callback order_reference %r does not match stored order_reference "
            "%r for gateway ID %s. Rejecting.",
            payment_gateway, callback_order_reference, order_reference, gateway_order_id,
        )
        raise ValueError("Callback order reference does not match the stored order")

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
    updates = {"credited_at": credited_at or _now_iso()}
    _update_order_status(order_reference=order_reference, status="credited", **updates)
    logger.info("Subscription order %s marked as credited", order_reference)


def _flag_activation_stall(order_reference, error_code, error_message):
    """Record why activation stopped, for every exit that does not complete it.

    The activation sequence is claimed before the source-state and schema
    checks run, so a paid order that fails one of them keeps
    ``activation_status='claimed'`` - the same value an activation still in
    flight carries. Without a reason written alongside it the row is
    indistinguishable from work in progress: ``activation_error_code`` stays
    NULL and ``reconciliation_required`` stays false, so no operator view and
    no reconciliation sweep ever surfaces the customer who has paid and
    received nothing.

    ``activation_status`` is deliberately left untouched. It is the reconciler's
    cursor for which stage to retry (``claimed`` retries activation), and
    ``conflict``/``failed`` are terminal in VALID_ACTIVATION_TRANSITIONS - moving
    the order there here would cost the retry that the reconciler is entitled to
    make. This writes the reason only; it never grants credit, never marks the
    order credited, and is safe to repeat.
    """
    try:
        _update_activation_state(
            order_reference=order_reference,
            activation_error_code=error_code,
            activation_error_message=error_message,
            reconciliation_required=True,
        )
    except Exception:
        logger.warning(
            "Could not flag activation stall %r on order %s",
            error_code, order_reference,
        )


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
    logger.info("Subscription order %s is already credited: idempotent success", order_reference)
    logger.info("Subscription order %s is already credited: idempotent success", order_reference)
    try:
        from app.services.billing_notification_service import notify_payment_confirmed, notify_activation_completed
        notify_payment_confirmed(company_id=order.get("company_id"), order_reference=order_reference)
        notify_activation_completed(company_id=order.get("company_id"), order_reference=order_reference)
    except Exception:
        logger.warning("Failed to send replay notification for order %s", order_reference)
    return {"status": "already_activated", "idempotent": True, "order_reference": order_reference, "order_status": "credited", "company_id": order.get("company_id")}


def _activate_subscription_plan(order, callback_txn_id, callback_paid_at, payment_gateway="chip"):
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

    period_start = datetime.now(timezone.utc)
    now_iso = period_start.isoformat()
    billing_interval = plan.get("billing_interval")
    period_end = calculate_current_period_end(period_start, billing_interval)
    period_end_iso = period_end.isoformat()
    try:
        validate_current_period(now_iso, period_end_iso, billing_interval)
    except ValueError as exc:
        logger.error(
            "Refusing to activate subscription with invalid billing period "
            "for company %s order %s plan_id=%s: %s",
            company_id,
            order_reference,
            new_plan_id,
            exc,
        )
        raise RuntimeError(
            f"Invalid billing period calculated for order {order_reference!r}"
        ) from exc

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
            try:
                _update_activation_state(
                    order_reference=order_reference,
                    activation_status="claimed",
                    activation_claimed_at=now_iso,
                )
            except Exception:
                logger.warning("Could not set activation_status=claimed on order %s", order_reference)
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
            _flag_activation_stall(
                order_reference,
                "malformed_atomic_order",
                "Version 2 order is missing required source-state fields.",
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
        if (
            activation_type in ("renewal", "upgrade")
            and source_period_end is None
            and not _is_null_source_period_recovery_order(order)
        ):
            logger.error(
                "Version 2 order %s is missing required source_period_end "
                "without an explicit NULL-period recovery marker. "
                "Failing closed; manual reconciliation required.",
                order_reference,
            )
            _flag_activation_stall(
                order_reference,
                "malformed_atomic_order",
                "Version 2 order is missing required source_period_end.",
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
        _flag_activation_stall(
            order_reference,
            "unsupported_order_schema_version",
            f"Order schema version {_schema_ver} is not supported.",
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
                expected_period_end_is_null=_is_null_source_period_recovery_order(order),
                target_plan_id=new_plan_id,
                period_start_iso=now_iso,
                period_end_iso=period_end_iso,
            )
        except ValueError as exc:
            logger.error(
                "Source subscription state mismatch for company %d (order %s): %s",
                company_id, order_reference, exc,
            )
            # Same error code the reconciler writes when its own retry hits this
            # wall, so a stall found here and a stall found there read alike.
            _flag_activation_stall(
                order_reference,
                "source_subscription_changed",
                "Source subscription state changed since checkout. "
                "Activation requires operator review.",
            )
            raise RuntimeError(
                f"Source subscription state has changed since checkout for order "
                f"{order_reference!r}. Manual reconciliation required."
            ) from exc
    else:
        # Historical order without source-state fields: legacy fallback
        _used_legacy_path = True
        try:
            _update_activation_state(
                order_reference=order_reference,
                activation_status="claimed",
                activation_claimed_at=now_iso,
            )
        except Exception:
            logger.warning("Could not set activation_status=claimed on legacy order %s", order_reference)
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
            _flag_activation_stall(
                order_reference,
                "legacy_activation_failed",
                "Legacy subscription activation failed. Retry will complete.",
            )
            raise RuntimeError(f"Failed to activate subscription for order {order_reference!r}: {exc}")

    logger.info(
        "Subscription activated for company %d (order %s, plan %s, seq_key=%s)",
        company_id, order_reference, plan_code, activation_sequence_key,
    )
    try:
        _update_activation_state(
            order_reference=order_reference,
            activation_status="activated",
            activation_completed_at=now_iso,
        )
    except Exception:
        logger.warning("Could not set activation_status=activated on order %s", order_reference)

    # ---- Step 4: Grant included AI credit ----
    # Idempotency key is tied to activation_sequence_key so two orders
    # against the same sequence key cannot both grant credit.
    if plan_included_credit > 0:
        try:
            _update_activation_state(
                order_reference=order_reference,
                activation_status="credit_pending",
                reconciliation_required=True,
            )
        except Exception:
            logger.warning("Could not set activation_status=credit_pending on order %s", order_reference)
        try:
            _ensure_company_ai_credit(company_id)
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
            return {
                "status": "activation_credit_pending",
                "idempotent": False,
                "order_reference": order_reference,
                "order_status": "paid",
                "company_id": company_id,
                "plan_code": plan_code,
                "activation_sequence_key": activation_sequence_key,
                "legacy_activation": _used_legacy_path,
                "message": "Subscription activated but included AI credit is pending reconciliation.",
            }
    else:
        logger.info("Plan %s has no included AI credit for company %d", plan_code, company_id)

    try:
        _update_activation_state(
            order_reference=order_reference,
            activation_status="completed",
            credit_granted_at=now_iso,
            reconciliation_required=False,
        )
    except Exception:
        logger.warning("Could not set activation_status=completed on order %s", order_reference)

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
    # ---- Step 7: Generate payment and activation notifications ----
    try:
        from app.services.billing_notification_service import notify_payment_confirmed, notify_activation_completed
        notify_payment_confirmed(company_id=company_id, order_reference=order_reference)
        notify_activation_completed(company_id=company_id, order_reference=order_reference)
    except Exception as notify_err:
        logger.warning(
            "Failed to send activation notification for order %s: %s",
            order_reference, notify_err,
        )


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
