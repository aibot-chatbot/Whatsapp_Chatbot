"""Bind authoritative CHIP purchases to stored AI-credit orders."""

from app.database.ai_credit_topup_order_repository import (
    get_topup_order_by_gateway_order_id, close_chip_topup_order, get_pending_chip_topup_orders,
    touch_chip_topup_reconciliation, mark_chip_topup_order_for_review,
)
from app.observability import capture_payment_failure
from app.services.ai_credit_topup_callback_service import process_topup_payment_callback
from app.services.chip_service import ChipConfig, normalize_purchase, get_purchase
from app.services.chip_payment_service import validate_chip_purchase_order


def process_chip_topup_purchase(purchase, config, *, review_required=False):
    """Hold reviewed orders on later reads; do not cancel in-flight credit work."""
    normalized = normalize_purchase(purchase)
    order = get_topup_order_by_gateway_order_id("chip", normalized["gateway_order_id"])
    if not order:
        raise ValueError("CHIP top-up order not found")
    amount = order.get("amount_micro_myr")
    if type(amount) is not int or amount <= 0 or amount % 10_000:
        raise ValueError("Stored top-up amount is invalid")
    validate_chip_purchase_order({**order, "amount_sen": amount // 10_000}, normalized, config)
    if order.get("failure_reason") == "chip_status_review":
        return {"status": "manual_review_required"}
    if review_required:
        mark_chip_topup_order_for_review(order["order_reference"], normalized["gateway_order_id"])
        return {"status": "manual_review_required"}
    status = normalized["gateway_status"]
    if normalized.get("paid"):
        if config.is_test:
            if order.get("status") == "cancelled" and order.get("failure_reason") == "chip_test_paid":
                return {"status": "test_paid", "idempotent": True}
            if order.get("status") != "pending":
                raise ValueError("Test payment cannot change a processed top-up")
            updated = close_chip_topup_order(order["order_reference"], "cancelled", "chip_test_paid")
            if not updated or updated.get("status") != "cancelled" or updated.get("failure_reason") != "chip_test_paid":
                raise RuntimeError("Test payment could not be recorded safely")
            return {"status": "test_paid", "idempotent": False}
        return process_topup_payment_callback(normalized)
    terminal = {"cancelled": "cancelled", "expired": "expired"}
    if status in terminal:
        close_chip_topup_order(order["order_reference"], terminal[status], "chip_" + status)
        return {"status": terminal[status]}
    if status in {"created", "sent", "viewed", "pending_execute", "pending_charge", "error"}:
        return {"status": "pending"}
    mark_chip_topup_order_for_review(order["order_reference"], normalized["gateway_order_id"])
    return {"status": "manual_review_required"}


def reconcile_chip_topups(limit=100):
    """Recover missed callbacks through the existing billing scheduler."""
    config = ChipConfig.from_env()
    if not config.enabled:
        return 0
    config.validate_for_api()
    failures = 0
    for order in get_pending_chip_topup_orders(config.environment, config.brand_id, limit):
        # A mode switch must never use a live key to inspect a test purchase.
        if order.get("gateway_environment") != config.environment:
            continue
        try:
            if not order.get("gateway_order_id"):
                if order.get("checkout_claim_token"):
                    capture_payment_failure("reconciliation", reason="persistence", mode=config.environment)
                    failures += 1
                continue
            purchase = get_purchase(config, order["gateway_order_id"])
            result = process_chip_topup_purchase(purchase, config)
            if result.get("status") == "manual_review_required":
                capture_payment_failure("reconciliation", reason="invalid_response", mode=config.environment)
                failures += 1
        except Exception as exc:
            capture_payment_failure("reconciliation", reason="unexpected", mode=config.environment, exc=exc)
            failures += 1
        finally:
            try:
                touch_chip_topup_reconciliation(order["order_reference"])
            except Exception as exc:
                capture_payment_failure("reconciliation", reason="persistence", mode=config.environment, exc=exc)
                failures += 1
    return failures
