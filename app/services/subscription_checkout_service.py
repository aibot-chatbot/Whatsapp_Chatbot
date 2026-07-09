"""
subscription_checkout_service.py

Creates a pending subscription payment order and generates a ToyyibPay
checkout bill.  No subscription activation or AI-credit grant happens here.
"""

import logging
import uuid
from datetime import datetime, timezone

from app.services.billing_service import get_current_subscription
from app.database.subscription_plan_repository import get_plan_by_code
from app.database.company_subscription_order_repository import (
    create_subscription_order,
    get_subscription_order_by_reference,
    update_subscription_order_status,
)
from app.services.toyyibpay_service import (
    ToyyibPayConfig,
    ToyyibPayConfigError,
    create_bill,
)

logger = logging.getLogger(__name__)

_PLAN_CODE_TO_SEN = {
    "essential": 3900,
    "advanced": 8900,
    "pro": 16900,
}

_VALID_PLAN_CODES = frozenset(_PLAN_CODE_TO_SEN.keys())


def create_subscription_checkout(
    company_id: int,
    user_id: int,
    plan_code: str,
    customer_name: str,
    customer_email: str,
    customer_phone: str | None = None,
) -> dict:
    """Validate the plan, create an order, and generate a ToyyibPay bill.

    Args:
        company_id: Authenticated company ID.
        user_id: Authenticated user ID.
        plan_code: Lowercase plan code ("essential", "advanced", "pro").
        customer_name: Display name for the bill.
        customer_email: Email for the bill.
        customer_phone: Optional phone for ToyyibPay.

    Returns:
        Dictionary with order_reference (UUID), checkout_url, amount_sen.

    Raises:
        ValueError: If plan_code is invalid, plan is inactive, or company
            has no current subscription.
        RuntimeError: If ToyyibPay bill creation fails.
    """
    # --- Validate plan code ---
    norm_code = plan_code.strip().lower()
    if norm_code not in _VALID_PLAN_CODES:
        raise ValueError(
            f"Invalid plan code: {plan_code!r}. "
            f"Must be one of: {sorted(_VALID_PLAN_CODES)}"
        )

    # --- Look up the plan in the database ---
    plan = get_plan_by_code(norm_code)
    if not plan:
        raise ValueError(f"Plan code {norm_code!r} not found in the catalogue.")
    if not plan.get("is_active", False):
        raise ValueError(f"Plan {norm_code!r} is not available for purchase.")

    plan_id = plan["id"]
    amount_sen = _PLAN_CODE_TO_SEN[norm_code]

    # --- Resolve current subscription ---
    subscription = get_current_subscription(company_id)
    if not subscription:
        raise ValueError(
            "Company has no current subscription. "
            "A default subscription must exist before checkout."
        )
    subscription_id = subscription["id"]

    # --- Create order reference and idempotency key ---
    order_reference = str(uuid.uuid4())
    idempotency_key = f"sub_checkout_{company_id}_{norm_code}_{order_reference}"

    # --- Create the pending order ---
    try:
        order = create_subscription_order(
            order_reference=order_reference,
            company_id=company_id,
            subscription_id=subscription_id,
            new_plan_id=plan_id,
            amount_sen=amount_sen,
            payment_gateway="toyyibpay",
            idempotency_key=idempotency_key,
            created_by_user_id=user_id,
        )
    except RuntimeError as exc:
        logger.error("Failed to create subscription order: %s", exc)
        raise RuntimeError("Failed to create subscription payment order.") from exc

    logger.info(
        "Subscription order %s created for company %d, plan %s, amount %d sen",
        order_reference, company_id, norm_code, amount_sen,
    )

    # --- Convert sen to micro-MYR for ToyyibPay ---
    amount_micro_myr = amount_sen * 10_000

    # --- Create the ToyyibPay bill ---
    try:
        bill = create_bill(
            order_reference=order_reference,
            amount_micro_myr=amount_micro_myr,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            description=f"Subscription - {norm_code.title()}",
        )
    except (ValueError, RuntimeError, ToyyibPayConfigError) as exc:
        # Mark the order as failed
        try:
            update_subscription_order_status(
                order_reference, "failed",
                failure_reason=str(exc)[:500],
            )
        except Exception:
            logger.exception(
                "Failed to mark subscription order %s as failed after bill error",
                order_reference,
            )
        raise RuntimeError(
            f"Payment gateway bill creation failed: {exc}"
        ) from exc

    gateway_order_id = bill.get("billcode") or bill.get("gateway_order_id", "")
    checkout_url = bill.get("checkout_url", "")

    # --- Save gateway details ---
    try:
        update_subscription_order_status(
            order_reference,
            "pending",
            gateway_order_id=gateway_order_id,
            checkout_url=checkout_url,
        )
    except Exception:
        logger.exception("Failed to save gateway details for order %s", order_reference)
        # Non-fatal: the order still exists, gateway details are retrievable

    logger.info(
        "Subscription checkout for company %d: reference=%s, gateway=%s",
        company_id, order_reference, gateway_order_id,
    )

    return {
        "order_reference": order_reference,
        "checkout_url": checkout_url,
        "amount_sen": amount_sen,
    }
