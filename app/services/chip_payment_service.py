"""Bind authoritative CHIP purchases to subscription orders and fulfilment."""

from app.database.company_subscription_order_repository import (
    get_subscription_order_by_gateway_id,
    mark_pending_subscription_order_paid,
    transition_pending_subscription_order_terminal,
    update_subscription_order_activation_state,
)
from app.observability import capture_payment_failure
from app.services.chip_service import ChipConfig, normalize_purchase
from app.services.subscription_payment_callback_service import process_subscription_payment_callback


def validate_chip_purchase_order(order: dict, purchase: dict, config: ChipConfig) -> None:
    """Require immutable identity, exact integer money, and the selected mode."""
    expected_amount = order.get("amount_sen")
    actual_amount = purchase.get("amount_sen")
    if (
        order.get("payment_gateway") != "chip"
        or purchase.get("payment_gateway") != "chip"
        or order.get("gateway_order_id") != purchase.get("gateway_order_id")
        or order.get("order_reference") != purchase.get("order_reference")
        or order.get("gateway_environment") != config.environment
        or type(purchase.get("is_test")) is not bool
        or purchase["is_test"] != config.is_test
        or order.get("gateway_brand_id") != config.brand_id
        or purchase.get("brand_id") != order.get("gateway_brand_id")
        or order.get("currency") != "MYR"
        or purchase.get("currency") != "MYR"
        or type(expected_amount) is not int
        or type(actual_amount) is not int
        or expected_amount <= 0
        or actual_amount != expected_amount
    ):
        raise ValueError("CHIP purchase does not match the stored subscription order")
    if (
        order.get("payment_reference")
        and order["payment_reference"] != purchase.get("payment_reference")
    ):
        raise ValueError("CHIP payment reference does not match the stored payment")


def process_chip_purchase(purchase: dict, config: ChipConfig | None = None, *, review_required=False) -> dict:
    """Process a re-fetched purchase after signature or server API verification."""
    config = config or ChipConfig.from_env()
    config.validate_for_api()
    normalized = normalize_purchase(purchase)
    order = get_subscription_order_by_gateway_id("chip", normalized["gateway_order_id"])
    try:
        if not order:
            raise ValueError("No CHIP subscription order matches this purchase")
        validate_chip_purchase_order(order, normalized, config)
    except ValueError as exc:
        capture_payment_failure("fulfillment", reason="mismatch", mode=config.environment, exc=exc)
        raise

    order_reference = normalized["order_reference"]
    status = normalized["gateway_status"]
    if normalized["paid"] and not review_required:
        if config.is_test:
            if order.get("activation_error_code") == "chip_test_paid" and order.get("status") == "cancelled":
                return {"status": "test_paid", "order_reference": order_reference, "idempotent": True}
            if order.get("status") != "pending":
                raise ValueError("CHIP test purchase cannot change an already processed order")
            updated = transition_pending_subscription_order_terminal(
                order_reference=order_reference,
                target_status="cancelled",
                released_activation_sequence_key=f"released:chip:test-paid:order:{order_reference}:{order.get('activation_sequence_key')}",
                error_code="chip_test_paid",
            )
            if updated.get("status") != "cancelled" or updated.get("activation_error_code") != "chip_test_paid":
                raise RuntimeError("CHIP test payment could not be recorded safely")
            return {"status": "test_paid", "order_reference": order_reference, "idempotent": False}
        try:
            # Claim payment before the shared callback re-fetches the order, so
            # a stale pending snapshot cannot reset an already credited order.
            claimed = mark_pending_subscription_order_paid(
                order_reference=order_reference,
                payment_reference=normalized["payment_reference"],
                paid_at=normalized.get("paid_at"),
            )
            if (
                not isinstance(claimed, dict)
                or claimed.get("status") not in {"paid", "credited"}
                or claimed.get("payment_reference") != normalized["payment_reference"]
            ):
                raise RuntimeError("CHIP payment could not be claimed safely")
            validate_chip_purchase_order(claimed, normalized, config)
        except Exception as exc:
            capture_payment_failure("fulfillment", reason="persistence", mode=config.environment, exc=exc)
            raise
        try:
            return process_subscription_payment_callback(normalized)
        except Exception as exc:
            capture_payment_failure("fulfillment", reason="fulfillment", mode=config.environment, exc=exc)
            raise

    if status in {"cancelled", "expired"} and not review_required:
        updated = transition_pending_subscription_order_terminal(
            order_reference=order_reference,
            target_status=status,
            released_activation_sequence_key=f"released:chip:{status}:order:{order_reference}:{order.get('activation_sequence_key')}",
            error_code=f"chip_{status}",
        )
        return {
            "status": updated.get("status"),
            "order_reference": order_reference,
            "idempotent": updated.get("status") in {"paid", "credited"},
        }
    if status in {"created", "sent", "viewed", "pending_execute", "pending_charge"} and not review_required:
        return {"status": "pending", "order_reference": order_reference, "idempotent": True}

    # reconciliation_required keeps this order in the 15-minute reconcile scan, so
    # the same unchanged purchase reaches this branch on every tick. Report the
    # transition into review, not each re-scan of an order already sitting in it -
    # the flag above, not a repeated alert, is what holds it for the operator.
    already_in_review = order.get("activation_error_code") == "chip_status_review"
    update_subscription_order_activation_state(
        order_reference=order_reference,
        activation_error_code="chip_status_review",
        activation_error_message="CHIP purchase status requires operator review.",
        reconciliation_required=True,
    )
    if not already_in_review:
        capture_payment_failure("fulfillment", reason="invalid_response", mode=config.environment)
    return {"status": "manual_review_required", "order_reference": order_reference, "idempotent": False}
