"""Create one CHIP purchase per AI-credit top-up attempt; never grant credit."""

import uuid

from app.observability import capture_payment_failure
from app.database.ai_credit_topup_order_repository import claim_chip_topup_checkout
from app.services.ai_credit_topup_order_service import (
    create_pending_topup_order as _create_pending_order,
    complete_checkout_creation as _complete_checkout,
    fail_checkout_creation as _fail_checkout,
)
from app.services.chip_service import (
    ChipConfig, ChipConfigError, ChipRequestRejectedError,
    create_purchase, validate_checkout_url,
)


class CheckoutRestartRequired(ValueError):
    """The previous attempt is definitively closed and may be replaced."""


def create_chip_topup_checkout(
    company_id, subscription_id, created_by_user_id, amount_micro_myr,
    customer_email, customer_name, idempotency_key, customer_phone=None,
    description=None, expires_at=None,
):
    """Keep ambiguous creates claimed permanently until operator reconciliation."""
    for value in (company_id, subscription_id, created_by_user_id, amount_micro_myr):
        if type(value) is not int or value <= 0:
            raise ValueError("IDs and amount must be positive integers.")
    if amount_micro_myr < 1_010_000 or amount_micro_myr % 10_000:
        raise ValueError("Amount must be at least RM1.01 and a whole number of sen.")
    if not isinstance(customer_email, str) or "@" not in customer_email:
        raise ValueError("A valid customer email is required.")
    if not isinstance(customer_name, str) or not customer_name.strip():
        raise ValueError("A customer name is required.")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError("An idempotency key is required.")
    config = ChipConfig.from_env()
    config.validate_for_checkout()
    order = _create_pending_order(
        company_id=company_id, subscription_id=subscription_id,
        created_by_user_id=created_by_user_id, amount_micro_myr=amount_micro_myr,
        payment_gateway="chip", idempotency_key=idempotency_key, expires_at=expires_at,
    )
    reference = order["order_reference"]
    if order.get("status") != "pending":
        raise CheckoutRestartRequired("This checkout attempt is closed. Start a new top-up.")
    if order.get("gateway_environment") and (
        order["gateway_environment"] != config.environment
        or order.get("gateway_brand_id") != config.brand_id
    ):
        raise ValueError("This checkout belongs to a different CHIP environment.")
    if order.get("gateway_order_id") and order.get("checkout_url"):
        return _checkout_result(order, config)
    claim_token = str(uuid.uuid4())
    claimed = claim_chip_topup_checkout(reference, claim_token, config.environment, config.brand_id)
    if not claimed:
        raise RuntimeError("Checkout is pending verification. Do not start another payment.")
    try:
        purchase = create_purchase(
            config, order_reference=reference, amount_sen=amount_micro_myr // 10_000,
            description=description or "AI Credit Top-Up", customer_email=customer_email,
            customer_name=customer_name, customer_phone=customer_phone,
        )
    except (ChipConfigError, ChipRequestRejectedError, ValueError):
        _fail_checkout(reference, claim_token, "CHIP purchase creation rejected")
        capture_payment_failure("checkout", reason="provider_rejected", mode=config.environment)
        raise CheckoutRestartRequired("CHIP rejected this checkout. Start a new attempt.") from None
    except Exception as exc:
        capture_payment_failure("checkout", reason="provider_unavailable", mode=config.environment, exc=exc)
        raise RuntimeError("Payment creation is pending verification. Do not pay again.") from None
    try:
        updated = _complete_checkout(
            order_reference=reference, claim_token=claim_token,
            gateway_order_id=purchase["gateway_order_id"], checkout_url=purchase["checkout_url"],
            expires_at=expires_at,
        )
    except Exception as exc:
        capture_payment_failure("checkout", reason="persistence", mode=config.environment, exc=exc)
        raise RuntimeError("Checkout needs reconciliation. Do not pay again.") from None
    return _checkout_result({**order, **updated, **purchase}, config)


def _checkout_result(order, config):
    return {
        "status": "pending", "order_reference": order["order_reference"],
        "amount_micro_myr": order["amount_micro_myr"], "currency": "MYR",
        "payment_gateway": "chip", "gateway_order_id": order["gateway_order_id"],
        "checkout_url": validate_checkout_url(order["checkout_url"]),
        "expires_at": order.get("expires_at"), "is_test": config.is_test,
    }
