"""Bind authoritative HitPay state to existing subscription fulfilment."""

from app.database.company_subscription_order_repository import (
    get_subscription_order_by_gateway_id,
    transition_pending_subscription_order_terminal,
    update_subscription_order_activation_state,
)
from app.services.hitpay_service import normalize_payment_request
from app.services.subscription_payment_callback_service import (
    process_subscription_payment_callback,
)


_TERMINAL_STATUS_MAP = {
    "failed": "failed",
    "expired": "expired",
    "canceled": "cancelled",
    "inactive": "cancelled",
}


def process_hitpay_payment_request(payment_request: dict) -> dict:
    """Process a re-fetched HitPay payment request without trusting redirects."""
    normalized = normalize_payment_request(payment_request)
    order = get_subscription_order_by_gateway_id(
        "hitpay", normalized["gateway_order_id"]
    )
    if not order:
        raise ValueError("No HitPay subscription order matches the payment request")
    if order.get("payment_gateway") != "hitpay":
        raise ValueError("HitPay payment gateway does not match the stored order")
    if str(order.get("order_reference") or "") != normalized["order_reference"]:
        raise ValueError("HitPay order reference does not match the stored order")
    if order.get("amount_sen") != normalized["amount_sen"]:
        raise ValueError("HitPay amount does not exactly match the stored order")

    status = normalized["gateway_status"]
    if status == "completed":
        return process_subscription_payment_callback(normalized)
    if status == "pending":
        return {
            "status": "pending",
            "order_reference": normalized["order_reference"],
            "idempotent": True,
        }
    if status in _TERMINAL_STATUS_MAP:
        local_status = _TERMINAL_STATUS_MAP[status]
        activation_key = str(order.get("activation_sequence_key") or "none")
        updated = transition_pending_subscription_order_terminal(
            order_reference=normalized["order_reference"],
            target_status=local_status,
            released_activation_sequence_key=(
                f"released:hitpay:{status}:order:{order.get('id') or normalized['order_reference']}:"
                f"{activation_key}"
            ),
            error_code=f"hitpay_{status}",
        )
        return {
            "status": (updated.get("status") or local_status).strip().lower(),
            "order_reference": normalized["order_reference"],
            "idempotent": (updated.get("status") or "").strip().lower()
            in {"paid", "credited"},
        }

    update_subscription_order_activation_state(
        order_reference=normalized["order_reference"],
        activation_error_code="hitpay_unknown_status",
        activation_error_message="HitPay status requires operator review.",
        reconciliation_required=True,
    )
    return {
        "status": "manual_review_required",
        "order_reference": normalized["order_reference"],
        "idempotent": False,
    }
