"""subscription_reconciliation_service.py

Recover paid-but-not-completed subscription orders.

This service retries only the incomplete stage of a subscription order,
reusing the existing activation_sequence_key and credit idempotency key.
It never generates a new activation key, never resets billing dates
if activation already completed, and never grants duplicate credit.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from app.observability import capture_payment_failure
from app.database.company_subscription_order_repository import (
    increment_reconciliation_attempt as _increment_attempt,
    get_subscription_order_by_reference as _get_order,
    update_subscription_order_activation_state as _update_state,
    update_subscription_order_fields as _update_fields,
)
from app.database.subscription_plan_repository import (
    get_plan_by_id,
)
from app.database.company_subscription_repository import (
    update_company_subscription,
    conditional_activate_subscription,
    get_company_subscription,
)
from app.services.ai_credit_service import (
    ensure_company_ai_credit as _ensure_company_ai_credit,
)
from app.services.billing_period_service import (
    calculate_current_period_end,
    validate_current_period,
)

logger = logging.getLogger(__name__)

NULL_SOURCE_PERIOD_END_ACTIVATION_SENTINEL = "null-period-end"


RECONCILIATION_OUTCOMES = frozenset({
    "reconciled_and_completed",
    "credit_retry_completed",
    "already_completed",
    "activation_already_claimed",
    "source_subscription_changed",
    "unpaid_order_not_reconcilable",
    "malformed_order",
    "manual_review_required",
    "chip_pending",
    "chip_terminal",
    "chip_test_paid",
})


def _is_null_source_period_recovery_order(order: dict) -> bool:
    company_id = order.get("company_id")
    activation_sequence_key = order.get("activation_sequence_key")
    return (
        order.get("order_schema_version") == 2
        and (order.get("activation_type") or "").strip().lower() == "renewal"
        and order.get("source_period_end") is None
        and activation_sequence_key
        == f"company:{company_id}:renewal-after:{NULL_SOURCE_PERIOD_END_ACTIVATION_SENTINEL}"
    )


def _reconcile_pending_chip_order(order: dict) -> dict:
    """Recover CHIP purchases by their persisted identity, never by a guess."""
    from app.services.chip_payment_service import process_chip_purchase, validate_chip_purchase_order
    from app.services.chip_service import ChipConfig, get_purchase, normalize_purchase

    config = ChipConfig.from_env()
    config.validate_for_api()
    order_reference = str(order.get("order_reference") or "").strip()
    gateway_order_id = str(order.get("gateway_order_id") or "").strip()
    _update_fields(
        order_reference,
        last_reconciliation_at=datetime.now(timezone.utc).isoformat(),
    )
    if not gateway_order_id:
        _update_state(
            order_reference,
            activation_error_code="chip_purchase_id_missing",
            activation_error_message="CHIP purchase creation requires operator verification before retry.",
            reconciliation_required=True,
        )
        return {
            "outcome": "manual_review_required",
            "order_status": "pending",
            "message": "CHIP purchase identity is missing; contact support before retrying.",
        }
    if order.get("gateway_environment") != config.environment or order.get("gateway_brand_id") != config.brand_id:
        raise ValueError("CHIP order mode or brand does not match the current configuration")
    purchase = get_purchase(config, gateway_order_id)
    validate_chip_purchase_order(order, normalize_purchase(purchase), config)
    result = process_chip_purchase(purchase, config=config)
    result_status = result.get("status")
    if result_status == "test_paid":
        return {
            "outcome": "chip_test_paid",
            "order_status": "cancelled",
            "message": "CHIP test payment verified; no subscription or credit was granted.",
        }
    if result_status in {"activated", "activated_and_credited", "already_activated", "legacy_order_activated", "subscription_activated"}:
        return {
            "outcome": "reconciled_and_completed",
            "order_status": "credited",
            "message": "CHIP payment was reconciled and fulfilled.",
        }
    if result_status == "pending":
        return {"outcome": "chip_pending", "order_status": "pending", "message": "CHIP payment remains pending."}
    if result_status in {"failed", "expired", "cancelled"}:
        return {"outcome": "chip_terminal", "order_status": result_status, "message": "CHIP purchase reached a terminal unpaid state."}
    return {"outcome": "manual_review_required", "order_status": order.get("status"), "message": "CHIP reconciliation requires operator review."}


def reconcile_subscription_order(
    order_reference: str,
    company_id: int | None = None,
    force: bool = False,
) -> dict:
    """Reconcile a paid-but-not-completed subscription order.

    Retries only the incomplete stage of the order lifecycle,
    reusing the existing activation_sequence_key and credit
    idempotency key.  Never generates a new activation key or
    resets billing dates if activation already completed.
    """
    if not order_reference:
        raise ValueError("order_reference is required")

    order = _get_order(order_reference)
    if order is None:
        return {"outcome": "manual_review_required", "order_status": None, "message": "Order not found."}

    if company_id is not None:
        if order.get("company_id") != company_id:
            return {"outcome": "manual_review_required", "order_status": order.get("status"), "message": "Company does not own this order."}

    status = (order.get("status") or "").strip().lower()
    act_status = (order.get("activation_status") or "").strip().lower()
    new_plan_id = order.get("new_plan_id")
    company_id_val = order.get("company_id")
    subscription_id = order.get("subscription_id")
    activation_seq_key = order.get("activation_sequence_key")
    order_schema_ver = order.get("order_schema_version")

    if status == "pending" and order.get("payment_gateway") == "chip":
        try:
            return _reconcile_pending_chip_order(order)
        except Exception as exc:
            capture_payment_failure("reconciliation", reason="provider_unavailable", mode=order.get("gateway_environment", "unknown"), exc=exc)
            try:
                _update_state(
                    order_reference,
                    activation_error_code="chip_reconciliation_failed",
                    activation_error_message="CHIP reconciliation requires retry.",
                    reconciliation_required=True,
                )
            except Exception as persistence_error:
                capture_payment_failure("reconciliation", reason="persistence", mode=order.get("gateway_environment", "unknown"), exc=persistence_error)
            return {
                "outcome": "manual_review_required",
                "order_status": status,
                "message": "CHIP reconciliation is temporarily unavailable.",
            }

    if order.get("payment_gateway") == "chip" and status not in {"paid", "credited"}:
        if status == "cancelled" and order.get("activation_error_code") == "chip_test_paid":
            return {"outcome": "chip_test_paid", "order_status": status, "message": "CHIP test payment already verified; no entitlements were granted."}
        return {"outcome": "unpaid_order_not_reconcilable", "order_status": status, "message": "CHIP payment has not been confirmed."}

    if order.get("payment_gateway") == "chip" and status in {"paid", "credited"}:
        from app.services.chip_service import ChipConfig, get_purchase, normalize_purchase
        from app.services.chip_payment_service import validate_chip_purchase_order
        try:
            config = ChipConfig.from_env()
            config.validate_for_api()
            if config.is_test or order.get("gateway_environment") != "live":
                raise ValueError("Test CHIP orders cannot receive subscription entitlements")
            purchase = normalize_purchase(get_purchase(config, order.get("gateway_order_id")))
            validate_chip_purchase_order(order, purchase, config)
            if not purchase["paid"]:
                raise ValueError("CHIP payment is not confirmed")
        except Exception as exc:
            capture_payment_failure("reconciliation", reason="mismatch", mode=order.get("gateway_environment", "unknown"), exc=exc)
            return {"outcome": "manual_review_required", "order_status": status, "message": "CHIP payment verification is required before fulfilment."}

    # Credited payments cannot restart activation, including legacy rows with
    # no activation metadata. Only an explicit credit stage may be recovered.
    if status == "credited":
        if act_status in {"", "completed"}:
            return {"outcome": "already_completed", "order_status": "credited", "message": "Order is already completed."}
        if act_status not in {"activated", "credit_pending"}:
            return {"outcome": "manual_review_required", "order_status": "credited", "message": "Credited order activation metadata requires support review."}

    # Activation flags cannot substitute for a durable payment confirmation.
    if status not in {"paid", "credited"}:
        return {"outcome": "unpaid_order_not_reconcilable", "order_status": status, "message": "Order payment has not been confirmed."}

    # Malformed version 2 order
    if order_schema_ver == 2:
        source_plan_id = order.get("source_plan_id")
        source_status = order.get("source_status")
        if source_plan_id is None or source_status is None:
            return {"outcome": "malformed_order", "order_status": status, "message": "Version 2 order is missing required source-state fields."}
        source_period_end = order.get("source_period_end")
        activation_type = (order.get("activation_type") or "").strip().lower()
        if (
            activation_type in ("renewal", "upgrade")
            and source_period_end is None
            and not _is_null_source_period_recovery_order(order)
        ):
            return {"outcome": "malformed_order", "order_status": status, "message": "Version 2 order is missing required source-state fields."}

    # Increment attempt counter
    try:
        _increment_attempt(order_reference)
    except Exception as exc:
        logger.warning("Atomic increment failed for %s: %s", order_reference, exc)

    now_iso = datetime.now(timezone.utc).isoformat()

    # Determine stage to retry
    if act_status in ("not_started", "claimed", "failed", ""):
        return _retry_activation(order, now_iso)

    if act_status == "activated" or act_status == "credit_pending":
        return _retry_credit(order, now_iso)

    if act_status == "conflict":
        return {"outcome": "activation_already_claimed", "order_status": status, "message": "Activation sequence already claimed by another order."}

    return {"outcome": "manual_review_required", "order_status": status, "message": f"Unknown activation_status: {act_status}. Manual review required."}


def _retry_activation(order: dict, now_iso: str) -> dict:
    """Retry subscription activation for an order that was paid but not activated."""
    order_reference = order.get("order_reference")
    company_id = order.get("company_id")
    subscription_id = order.get("subscription_id")
    new_plan_id = order.get("new_plan_id")
    activation_seq_key = order.get("activation_sequence_key")
    source_plan_id = order.get("source_plan_id")
    source_status = order.get("source_status")
    source_period_start = order.get("source_period_start")
    source_period_end = order.get("source_period_end")
    status = order.get("status", "")

    if not new_plan_id:
        return {"outcome": "manual_review_required", "order_status": status, "message": "Missing new_plan_id."}

    plan = get_plan_by_id(new_plan_id)
    if not plan:
        return {"outcome": "manual_review_required", "order_status": status, "message": f"Plan {new_plan_id} not found."}

    plan_code = plan.get("code", "").lower()
    plan_included_credit = plan.get("included_ai_credit_micro_myr", 0) or 0

    period_start = datetime.fromisoformat(now_iso)
    billing_interval = plan.get("billing_interval")
    period_end = calculate_current_period_end(period_start, billing_interval)
    period_end_iso = period_end.isoformat()
    try:
        validate_current_period(now_iso, period_end_iso, billing_interval)
    except ValueError as exc:
        logger.error(
            "Refusing reconciliation activation with invalid billing period "
            "for company %s order %s plan_id=%s: %s",
            company_id,
            order_reference,
            new_plan_id,
            exc,
        )
        return {
            "outcome": "manual_review_required",
            "order_status": status,
            "message": "Invalid billing period calculated during reconciliation.",
        }

    # Try to claim the activation sequence if not already claimed
    from app.database.company_subscription_order_repository import claim_subscription_activation_sequence as _claim
    if activation_seq_key:
        try:
            _claim(order_reference, activation_seq_key)
        except RuntimeError as exc:
            logger.warning("Activation retry claim failed for %s: %s", order_reference, exc)
            return {"outcome": "activation_already_claimed", "order_status": status, "message": "Could not claim activation sequence."}
        try:
            _update_state(order_reference, activation_status="claimed", activation_claimed_at=now_iso)
        except Exception:
            pass

    # Attempt activation via conditional update
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
            logger.error("Source state changed for %s: %s", order_reference, exc)
            try:
                _update_state(order_reference, activation_status="conflict", activation_error_code="source_subscription_changed")
            except Exception:
                pass
            return {"outcome": "source_subscription_changed", "order_status": status, "message": "Source subscription state changed since checkout."}
    else:
        # Legacy fallback - direct update
        updates = {
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
            update_company_subscription(subscription_id=subscription_id, company_id=company_id, updates=updates)
        except Exception as exc:
            logger.error("Legacy activation failed for %s: %s", order_reference, exc)
            return {"outcome": "manual_review_required", "order_status": status, "message": f"Legacy activation failed: {exc}"}

    # Mark activation completed
    try:
        _update_state(order_reference, activation_status="activated", activation_completed_at=now_iso)
    except Exception:
        pass

    logger.info("Activation retry succeeded for order %s", order_reference)

    # Now retry credit grant
    return _retry_credit(order, now_iso, plan_included_credit=plan_included_credit, plan_code=plan_code)


def _retry_credit(
    order: dict,
    now_iso: str,
    plan_included_credit: int | None = None,
    plan_code: str | None = None,
) -> dict:
    """Retry AI credit grant for an order that was activated but not credited."""
    order_reference = order.get("order_reference")
    company_id = order.get("company_id")
    new_plan_id = order.get("new_plan_id")
    activation_seq_key = order.get("activation_sequence_key")
    status = order.get("status", "")

    if plan_code is None or plan_included_credit is None:
        plan = get_plan_by_id(new_plan_id) if new_plan_id else None
        if not plan:
            return {"outcome": "manual_review_required", "order_status": status, "message": "Plan not found for credit retry."}
        plan_code = plan.get("code", "").lower()
        plan_included_credit = plan.get("included_ai_credit_micro_myr", 0) or 0

    if plan_included_credit > 0:
        if not activation_seq_key:
            return {"outcome": "manual_review_required", "order_status": status, "message": "Missing activation_sequence_key for credit idempotency."}
        try:
            result = _ensure_company_ai_credit(company_id)
            logger.info(
                "Credit retry for %s: period_changed=%s included_granted=%s",
                order_reference,
                result.get("period_changed"),
                result.get("included_credit_granted_micro_myr"),
            )
        except Exception as exc:
            logger.error("Credit retry failed for %s: %s", order_reference, exc)
            try:
                _update_state(order_reference, activation_status="credit_pending", activation_error_code="credit_grant_failed", reconciliation_required=True)
            except Exception:
                pass
            return {"outcome": "manual_review_required", "order_status": status, "message": f"Credit retry failed: {exc}"}

    # Mark order as completed
    try:
        _update_state(order_reference, activation_status="completed", credit_granted_at=now_iso, reconciliation_required=False)
    except Exception:
        pass

    # Mark order credited
    from app.database.company_subscription_order_repository import update_subscription_order_status as _mark_credited
    try:
        _mark_credited(order_reference=order_reference, status="credited", credited_at=now_iso)
    except Exception as exc:
        logger.warning("Failed to mark order %s as credited: %s", order_reference, exc)
        return {"outcome": "credit_retry_completed", "order_status": "credit_pending", "message": "Credit granted but order status update failed."}

    # Generate completion notification
    try:
        from app.services.billing_notification_service import notify_reconciliation_completed
        notify_reconciliation_completed(company_id=company_id, order_reference=order_reference)
    except Exception as notify_err:
        logger.warning("Failed to send reconciliation notification for %s: %s", order_reference, notify_err)

    logger.info("Reconciliation completed for order %s", order_reference)
    return {"outcome": "credit_retry_completed", "order_status": "credited", "message": "Reconciliation completed successfully."}
