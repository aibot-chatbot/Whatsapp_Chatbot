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
    current_plan = subscription.get("plan") or {}
    current_code = (current_plan.get("code") or "").lower()
    current_status = (subscription.get("status") or "").lower().strip()

    # --- Purchase protections ---
    _plan_rank = {"free": 0, "essential": 1, "advanced": 2, "pro": 3}
    target_rank = _plan_rank.get(norm_code, -1)
    current_rank = _plan_rank.get(current_code, -1)
    _paid_plan_codes = {"essential", "advanced", "pro"}

    if norm_code in _paid_plan_codes:
        if current_status == "trialing":
            pass
        elif current_status in ("expired", "past_due"):
            if norm_code == current_code:
                pass
            elif target_rank > current_rank:
                pass
            else:
                raise ValueError(
                    f"Plan \"" + norm_code + "\" is lower than your current plan. "
                    "Lower plans must be scheduled through the downgrade process."
                )
        elif current_status == "active":
            if norm_code == current_code:
                raise ValueError(
                    f"You are already subscribed to the " + current_code.title() + " plan. "
                    "If you need to change your plan, please use the Change Plan option."
                )
            elif target_rank < current_rank:
                raise ValueError(
                    f"Plan \"" + norm_code + "\" is lower than your current " + current_code.title() + " plan. "
                    "Lower plans must be scheduled through the downgrade process."
                )

    # --- Create order reference and idempotency key ---
    order_reference = str(uuid.uuid4())
    idempotency_key = f"sub_checkout_{company_id}_{norm_code}_{order_reference}"

    # --- Capture subscription snapshot for atomic activation ---
    source_plan_id = subscription.get("plan_id")
    source_period_start = subscription.get("current_period_start")
    source_period_end = subscription.get("current_period_end")
    source_status = current_status

    # Determine activation type for this order
    if source_status == "trialing":
        activation_type = "initial_purchase"
    elif source_status in ("expired", "past_due", "cancelled"):
        activation_type = "renewal"
    elif source_status == "active":
        activation_type = "upgrade"
    else:
        activation_type = "initial_purchase"

    # Generate deterministic activation_sequence_key at checkout time
    _trial_end = subscription.get("trial_ends_at") or "no-trial"
    if activation_type == "initial_purchase":
        activation_sequence_key = f"company:{company_id}:initial-from:{subscription_id}:trial:{_trial_end}"
    elif activation_type == "renewal":
        activation_sequence_key = f"company:{company_id}:renewal-after:{source_period_end}"
    elif activation_type == "upgrade":
        activation_sequence_key = f"company:{company_id}:upgrade-from:{source_plan_id}:period:{source_period_start}"
    else:
        activation_sequence_key = f"company:{company_id}:other:{order_reference}"

    # --- Validate activation fields for schema version 2 ---
    # All newly created orders must have the required atomicity fields
    # appropriate for their activation type. The validation is specific
    # to each activation_type so that only genuinely required fields
    # are enforced.
    _missing = []
    if not activation_type:
        _missing.append("activation_type")
    if not activation_sequence_key:
        _missing.append("activation_sequence_key")
    if not source_status:
        _missing.append("source_status")
    if activation_type == "initial_purchase":
        if not subscription_id:
            _missing.append("subscription_id")
    elif activation_type == "renewal":
        if not source_plan_id:
            _missing.append("source_plan_id")
        if not source_period_end:
            _missing.append("source_period_end")
    elif activation_type == "upgrade":
        if not source_plan_id:
            _missing.append("source_plan_id")
        if not source_period_start:
            _missing.append("source_period_start")
        if not source_period_end:
            _missing.append("source_period_end")
    if _missing:
        raise ValueError(
            f"Subscription order is missing required activation fields: "
            f"activation_type={activation_type!r}, "
            f"missing={_missing}. "
            f"Order cannot be created without complete atomicity data."
        )

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
            source_plan_id=source_plan_id,
            source_period_start=source_period_start,
            source_period_end=source_period_end,
            source_status=source_status,
            activation_type=activation_type,
            activation_sequence_key=activation_sequence_key,
            order_schema_version=2,
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
