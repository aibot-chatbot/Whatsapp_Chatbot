"""ai_credit_topup_checkout_service.py -- Internal Billplz top-up checkout orchestration.

This module creates a pending AI-credit top-up order and a corresponding
Billplz Bill.  It is an internal service with no public Flask route.

No AI credit is granted by this module.
"""

import logging
import uuid
from typing import Any

from app.services.billplz_service import (
    create_bill as _create_billplz_bill,
)
from app.services.ai_credit_topup_order_service import (
    create_pending_topup_order as _create_pending_order,
    claim_checkout_creation as _claim_checkout,
    complete_checkout_creation as _complete_checkout,
    fail_checkout_creation as _fail_checkout,
)

logger = logging.getLogger(__name__)

_PAYMENT_GATEWAY = "billplz"

_MICRO_MYR_PER_SEN = 10_000

_VALID_NON_CREDIT_STATUSES = frozenset({
    "paid",
    "credited",
    "failed",
    "expired",
    "cancelled",
})


def _validate_positive_int(value: Any, label: str) -> None:
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer, got {value!r}")


def _validate_non_empty_str(value: Any, label: str) -> None:
    if not value or not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


def _validate_email(email: Any) -> None:
    if not email or not isinstance(email, str) or not email.strip():
        raise ValueError("customer_email must be a non-empty string")
    cleaned = email.strip()
    if "@" not in cleaned or "." not in cleaned.split("@")[-1]:
        raise ValueError(
            f"customer_email {cleaned!r} does not appear to be a valid email address"
        )


def _validate_amount_divisibility(amount_micro_myr: int) -> None:
    if amount_micro_myr % _MICRO_MYR_PER_SEN != 0:
        raise ValueError(
            f"amount_micro_myr must be divisible by {_MICRO_MYR_PER_SEN} "
            f"(1 sen), got {amount_micro_myr}"
        )


def create_billplz_topup_checkout(
    company_id: int,
    subscription_id: int,
    created_by_user_id: int,
    amount_micro_myr: int,
    customer_email: str,
    customer_name: str,
    idempotency_key: str,
    description: str | None = None,
    expires_at: str | None = None,
) -> dict:
    """Create a Billplz-powered AI-credit top-up checkout."""
    _validate_positive_int(company_id, "company_id")
    _validate_positive_int(subscription_id, "subscription_id")
    _validate_positive_int(created_by_user_id, "created_by_user_id")
    _validate_positive_int(amount_micro_myr, "amount_micro_myr")
    _validate_email(customer_email)
    _validate_non_empty_str(customer_name, "customer_name")
    _validate_non_empty_str(idempotency_key, "idempotency_key")
    _validate_amount_divisibility(amount_micro_myr)

    if description is not None and not isinstance(description, str):
        raise ValueError("description must be a string or None")

    normalized_desc = description.strip() if description else "AI Credit Top-Up"

    logger.info(
        "Creating Billplz top-up checkout for company %d, amount %d micro-MYR, "
        "idempotency_key %r",
        company_id, amount_micro_myr, idempotency_key,
    )

    order = _create_pending_order(
        company_id=company_id,
        subscription_id=subscription_id,
        created_by_user_id=created_by_user_id,
        amount_micro_myr=amount_micro_myr,
        payment_gateway=_PAYMENT_GATEWAY,
        idempotency_key=idempotency_key,
        expires_at=expires_at,
    )

    order_status = order.get("status", "")
    order_reference = order.get("order_reference", "")
    existing_gateway_order_id = order.get("gateway_order_id")
    existing_checkout_url = order.get("checkout_url")

    if not order_reference:
        raise RuntimeError(
            "create_pending_topup_order returned an order without an "
            "order_reference"
        )

    if order_status == "pending":
        if existing_gateway_order_id and existing_checkout_url:
            logger.info(
                "Returning existing checkout for order %s (idempotency key %r)",
                order_reference, idempotency_key,
            )
            return _build_checkout_result(
                order=order,
                gateway_order_id=existing_gateway_order_id,
                checkout_url=existing_checkout_url,
            )

    elif order_status == "paid":
        raise RuntimeError(
            f"Order {order_reference!r} is already paid. "
            f"Checkout cannot be created for a paid order."
        )
    elif order_status == "credited":
        raise RuntimeError(
            f"Order {order_reference!r} is already credited. "
            f"Checkout cannot be created for a credited order."
        )
    elif order_status in _VALID_NON_CREDIT_STATUSES:
        raise RuntimeError(
            f"Order {order_reference!r} has status {order_status!r}. "
            f"Cannot reuse this checkout attempt."
        )

    claim_token = str(uuid.uuid4())

    claim_result = _claim_checkout(
        order_reference=order_reference,
        claim_token=claim_token,
        claim_timeout_seconds=300,
    )

    if not isinstance(claim_result, dict):
        raise RuntimeError(
            f"Claim result must be a dictionary for order {order_reference!r}"
        )

    claimed = claim_result.get("claimed")
    reason = claim_result.get("reason", "")

    if claimed is True:
        pass

    elif reason == "checkout_exists":
        gw_id = claim_result.get("gateway_order_id")
        gw_url = claim_result.get("checkout_url")
        if not gw_id or not gw_url:
            raise RuntimeError(
                f"Claim result indicates an existing checkout for order "
                f"{order_reference!r} but gateway details are missing"
            )
        logger.info(
            "Returning existing checkout from claim for order %s",
            order_reference,
        )
        existing_order = dict(order)
        existing_order["gateway_order_id"] = gw_id
        existing_order["checkout_url"] = gw_url
        return _build_checkout_result(
            order=existing_order,
            gateway_order_id=gw_id,
            checkout_url=gw_url,
        )

    elif reason == "checkout_in_progress":
        raise RuntimeError(
            "Checkout creation is already in progress for this order."
        )

    elif reason == "invalid_status":
        status = claim_result.get("order_status", "unknown")
        raise RuntimeError(
            f"Checkout cannot be created for order status: {status}"
        )

    else:
        raise RuntimeError(
            f"Failed to claim order {order_reference!r} for checkout: "
            f"{reason}"
        )

    try:
        billplz_result = _create_billplz_bill(
            order_reference=order_reference,
            amount_micro_myr=amount_micro_myr,
            customer_email=customer_email.strip(),
            customer_name=customer_name.strip(),
            description=normalized_desc,
        )
    except (ValueError, RuntimeError):
        _fail_checkout(
            order_reference=order_reference,
            claim_token=claim_token,
            failure_reason="Billplz bill creation failed",
        )
        raise

    bill_id = billplz_result.get("bill_id")
    checkout_url_result = billplz_result.get("checkout_url")

    if not bill_id or not checkout_url_result:
        _fail_checkout(
            order_reference=order_reference,
            claim_token=claim_token,
            failure_reason="Billplz response missing bill ID or URL",
        )
        raise RuntimeError(
            f"Billplz returned a response without a bill ID or checkout URL "
            f"for order {order_reference!r}"
        )

    try:
        _complete_checkout(
            order_reference=order_reference,
            claim_token=claim_token,
            gateway_order_id=bill_id,
            checkout_url=checkout_url_result,
            expires_at=expires_at,
        )
    except (ValueError, RuntimeError) as exc:
        logger.error(
            "CRITICAL: Billplz bill %s created for order %s but completing "
            "checkout claim failed: %s. Manual reconciliation required.",
            bill_id, order_reference, exc,
        )
        raise RuntimeError(
            f"Reconciliation required for order {order_reference!r} and "
            f"Billplz bill {bill_id!r}: checkout completion failed. "
            f"Please contact support."
        )

    return _build_checkout_result(
        order=order,
        gateway_order_id=bill_id,
        checkout_url=checkout_url_result,
    )


def _build_checkout_result(
    order: dict,
    gateway_order_id: str,
    checkout_url: str,
) -> dict:
    return {
        "status": "pending",
        "order_id": order.get("id"),
        "order_reference": order.get("order_reference"),
        "company_id": order.get("company_id"),
        "amount_micro_myr": order.get("amount_micro_myr"),
        "currency": "MYR",
        "payment_gateway": _PAYMENT_GATEWAY,
        "gateway_order_id": gateway_order_id,
        "checkout_url": checkout_url,
        "expires_at": order.get("expires_at"),
    }


