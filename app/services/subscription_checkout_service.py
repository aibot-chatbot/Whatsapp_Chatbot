"""Create pending subscription orders and hosted gateway checkouts."""

import logging
import os
import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.billing_service import get_current_subscription
from app.database.subscription_plan_repository import get_plan_by_code
from app.database.company_subscription_order_repository import (
    create_subscription_order,
    get_subscription_order_by_reference,
    get_subscription_order_by_activation_sequence_key,
    expire_pending_subscription_order_for_checkout_retry,
    fail_pending_subscription_order_without_gateway_and_release_key,
    update_subscription_order_activation_state,
    update_subscription_order_status,
)
from app.services.hitpay_service import (
    HitPayAmbiguousError,
    HitPayConfig,
    HitPayConfigError,
    HitPayRequestRejectedError,
    create_payment_request,
)
from app.services.toyyibpay_service import (
    ToyyibPayConfig,
    ToyyibPayConfigError,
    ToyyibPayBillRejectedError,
    create_bill,
)

logger = logging.getLogger(__name__)

_PAYMENT_GATEWAYS = frozenset({"hitpay", "toyyibpay"})

_PLAN_CODE_TO_SEN = {
    "essential": 3900,
    "advanced": 8900,
    "pro": 16900,
}

_VALID_PLAN_CODES = frozenset(_PLAN_CODE_TO_SEN.keys())

_TERMINAL_ORDER_STATUSES = frozenset({"failed", "expired", "cancelled", "credited"})

_DEFAULT_CHECKOUT_EXPIRY_DAYS = 1
_MAX_TOYYIBPAY_EXPIRY_DAYS = 100
_TOYYIBPAY_EXPIRY_TIMEZONE_KEY = "Asia/Kuala_Lumpur"
_TOYYIBPAY_EXPIRY_TIMEZONE = None


def _clean(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _has_usable_checkout(order: dict) -> bool:
    checkout_url = _clean(order.get("checkout_url"))
    gateway_order_id = _clean(order.get("gateway_order_id"))
    payment_gateway = _clean(order.get("payment_gateway")).lower() or "toyyibpay"
    prefixes = {
        "hitpay": (
            "https://securecheckout.sandbox.hit-pay.com/",
            "https://securecheckout.hit-pay.com/",
        ),
        "toyyibpay": (
            "https://toyyibpay.com/",
            "https://dev.toyyibpay.com/",
        ),
    }
    return (
        bool(gateway_order_id)
        and payment_gateway in prefixes
        and checkout_url.startswith(prefixes[payment_gateway])
    )


def get_subscription_payment_gateway(company_id: int | None = None) -> str:
    """Resolve the server-controlled gateway, with an optional HitPay canary list."""
    raw_canaries = os.getenv("HITPAY_CANARY_COMPANY_IDS", "").strip()
    if raw_canaries and company_id is not None:
        try:
            canaries = {int(value.strip()) for value in raw_canaries.split(",") if value.strip()}
        except ValueError as exc:
            raise RuntimeError("HITPAY_CANARY_COMPANY_IDS must contain integer IDs") from exc
        if company_id in canaries:
            return "hitpay"

    gateway = os.getenv("SUBSCRIPTION_PAYMENT_GATEWAY", "toyyibpay").strip().lower()
    if gateway not in _PAYMENT_GATEWAYS:
        raise RuntimeError(
            "SUBSCRIPTION_PAYMENT_GATEWAY must be 'toyyibpay' or 'hitpay'"
        )
    return gateway


def _is_incomplete_pending_checkout(order: dict) -> bool:
    status = (order.get("status") or "").strip().lower()
    return status == "pending" and not _has_usable_checkout(order)


def _checkout_expiry_days() -> int:
    legacy_hours = os.getenv("SUBSCRIPTION_CHECKOUT_EXPIRY_HOURS", "").strip()
    if legacy_hours:
        raise RuntimeError(
            "SUBSCRIPTION_CHECKOUT_EXPIRY_HOURS is unsupported; "
            "use SUBSCRIPTION_CHECKOUT_EXPIRY_DAYS."
        )

    raw = os.getenv("SUBSCRIPTION_CHECKOUT_EXPIRY_DAYS", "").strip()
    if not raw:
        return _DEFAULT_CHECKOUT_EXPIRY_DAYS
    try:
        days = int(raw)
    except ValueError as exc:
        raise RuntimeError("SUBSCRIPTION_CHECKOUT_EXPIRY_DAYS must be an integer") from exc
    if days < 1 or days > _MAX_TOYYIBPAY_EXPIRY_DAYS:
        raise RuntimeError(
            "SUBSCRIPTION_CHECKOUT_EXPIRY_DAYS must be between 1 and 100"
        )
    return days


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _toyyibpay_expiry_timezone() -> ZoneInfo:
    global _TOYYIBPAY_EXPIRY_TIMEZONE
    if _TOYYIBPAY_EXPIRY_TIMEZONE is None:
        try:
            _TOYYIBPAY_EXPIRY_TIMEZONE = ZoneInfo(_TOYYIBPAY_EXPIRY_TIMEZONE_KEY)
        except ZoneInfoNotFoundError as exc:
            raise RuntimeError(
                "IANA timezone data is required for subscription checkout expiry. "
                "Install the runtime dependency 'tzdata'."
            ) from exc
    return _TOYYIBPAY_EXPIRY_TIMEZONE


def _build_checkout_expires_at(now: datetime | None = None) -> str:
    base = now or _now_utc()
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    else:
        base = base.astimezone(timezone.utc)

    expiry_days = _checkout_expiry_days()
    local_timezone = _toyyibpay_expiry_timezone()
    local_base = base.astimezone(local_timezone)
    final_date = local_base.date() + timedelta(days=expiry_days)
    final_local = datetime.combine(
        final_date,
        time(23, 59, 59),
        tzinfo=local_timezone,
    )
    return final_local.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_pending_checkout_expired(order: dict, now: datetime | None = None) -> bool:
    if (order.get("status") or "").strip().lower() != "pending":
        return False
    expires_at = _parse_datetime(order.get("expires_at"))
    if expires_at is None:
        return False
    check_time = now or _now_utc()
    if check_time.tzinfo is None:
        check_time = check_time.replace(tzinfo=timezone.utc)
    else:
        check_time = check_time.astimezone(timezone.utc)
    return expires_at <= check_time


def _is_pending_checkout_reusable(order: dict) -> bool:
    return (
        _has_usable_checkout(order)
        and _parse_datetime(order.get("expires_at")) is not None
        and not _is_pending_checkout_expired(order)
    )


def _released_activation_sequence_key(order: dict, activation_sequence_key: str) -> str:
    order_id = order.get("id") or "unknown"
    return f"released:checkout-expired:order:{order_id}:{activation_sequence_key}"


def _gateway_rejected_activation_sequence_key(order: dict, activation_sequence_key: str) -> str:
    order_id = order.get("id") or "unknown"
    return f"released:gateway-create-rejected:order:{order_id}:{activation_sequence_key}"


def _expire_existing_pending_checkout_if_needed(order: dict, activation_sequence_key: str) -> bool:
    if not _is_pending_checkout_expired(order):
        return False
    order_reference = _clean(order.get("order_reference"))
    if not order_reference or not activation_sequence_key:
        return False
    expire_pending_subscription_order_for_checkout_retry(
        order_reference=order_reference,
        activation_sequence_key=activation_sequence_key,
        expired_activation_sequence_key=_released_activation_sequence_key(
            order, activation_sequence_key
        ),
    )
    logger.info(
        "Expired subscription checkout order %s and released activation sequence",
        order_reference,
    )
    return True


def _activation_sequence_conflict_message(existing_order: dict) -> str:
    status = (existing_order.get("status") or "").strip().lower()
    activation_status = (existing_order.get("activation_status") or "").strip().lower()

    if _is_incomplete_pending_checkout(existing_order):
        if existing_order.get("expires_at"):
            return (
                "A pending subscription checkout has expired. "
                "Please try creating the checkout again."
            )
        return (
            "A pending subscription checkout was started, but its payment link is not available. "
            "Please contact support so we can safely reset this checkout."
        )
    if status == "pending":
        return (
            "A pending subscription checkout already exists for this billing period. "
            "Please complete or wait for the existing order to expire."
        )
    if status in ("paid", "created") or activation_status in (
        "not_started",
        "claimed",
        "activated",
        "credit_pending",
    ):
        return (
            "A subscription checkout for this billing period is already being processed. "
            "Please wait for it to complete before creating another checkout."
        )
    if status in _TERMINAL_ORDER_STATUSES or activation_status in ("completed", "conflict", "failed"):
        return (
            "A subscription checkout already exists for this billing period. "
            "Please contact support if you need help with this order."
        )
    return (
        "A subscription checkout already exists for this billing period. "
        "Please complete or resolve the existing order before creating another checkout."
    )


def _is_activation_sequence_unique_violation(exc: Exception) -> bool:
    text = str(exc)
    return (
        "idx_cso_activation_sequence_key" in text
        or (
            "activation_sequence_key" in text
            and "duplicate key" in text.lower()
        )
    )


def _build_existing_checkout_result(order: dict) -> dict:
    checkout_url = _clean(order.get("checkout_url"))
    order_reference = _clean(order.get("order_reference"))
    amount_sen = order.get("amount_sen")

    if not order_reference:
        raise ValueError("Existing checkout is missing its order reference.")
    if not isinstance(amount_sen, int) or isinstance(amount_sen, bool):
        raise ValueError("Existing checkout is missing its amount.")
    if not _has_usable_checkout(order):
        raise ValueError(_activation_sequence_conflict_message(order))

    return {
        "order_reference": order_reference,
        "checkout_url": checkout_url,
        "amount_sen": amount_sen,
        "expires_at": order.get("expires_at"),
        "payment_gateway": _clean(order.get("payment_gateway")).lower() or "toyyibpay",
        "existing_order": True,
    }


def prepare_subscription_checkout_order(
    company_id: int,
    user_id: int,
    plan_code: str,
    *,
    payment_gateway: str = "toyyibpay",
    allow_existing_reusable_checkout: bool = False,
) -> dict:
    """Create a pending subscription order without contacting a gateway."""
    payment_gateway = _clean(payment_gateway).lower()
    if payment_gateway not in _PAYMENT_GATEWAYS:
        raise ValueError("Unsupported subscription payment gateway")
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

    existing_sequence_order = get_subscription_order_by_activation_sequence_key(
        activation_sequence_key
    )
    if existing_sequence_order:
        if _expire_existing_pending_checkout_if_needed(
            existing_sequence_order, activation_sequence_key
        ):
            existing_sequence_order = None

    if existing_sequence_order:
        existing_status = (existing_sequence_order.get("status") or "").strip().lower()
        if (
            allow_existing_reusable_checkout
            and
            existing_status == "pending"
            and existing_sequence_order.get("new_plan_id") == plan_id
            and _is_pending_checkout_reusable(existing_sequence_order)
        ):
            return _build_existing_checkout_result(existing_sequence_order)
        raise ValueError(_activation_sequence_conflict_message(existing_sequence_order))

    if norm_code in _paid_plan_codes:
        from app.database.company_subscription_order_repository import list_subscription_orders_for_company
        pending_orders = list_subscription_orders_for_company(company_id=company_id, status="pending")
        for po in pending_orders:
            po_key = _clean(po.get("activation_sequence_key"))
            if po_key and _expire_existing_pending_checkout_if_needed(po, po_key):
                continue
            if po.get("new_plan_id") == plan_id:
                raise ValueError(
                    "A pending order already exists for this plan. " +
                    "Please complete or wait for the existing order to expire."
                )

    expires_at = _build_checkout_expires_at()

    # --- Create the pending order ---
    try:
        order = create_subscription_order(
            order_reference=order_reference,
            company_id=company_id,
            subscription_id=subscription_id,
            new_plan_id=plan_id,
            amount_sen=amount_sen,
            payment_gateway=payment_gateway,
            idempotency_key=idempotency_key,
            created_by_user_id=user_id,
            expires_at=expires_at,
            source_plan_id=source_plan_id,
            source_period_start=source_period_start,
            source_period_end=source_period_end,
            source_status=source_status,
            activation_type=activation_type,
            activation_sequence_key=activation_sequence_key,
            order_schema_version=2,
        )
    except Exception as exc:
        if _is_activation_sequence_unique_violation(exc):
            raise ValueError(_activation_sequence_conflict_message({})) from exc
        logger.error("Failed to create subscription order: %s", exc)
        raise RuntimeError("Failed to create subscription payment order.") from exc

    logger.info(
        "Subscription order %s created for company %d, plan %s, amount %d sen",
        order_reference, company_id, norm_code, amount_sen,
    )

    return {
        "order": order,
        "order_reference": order_reference,
        "amount_sen": amount_sen,
        "expires_at": expires_at,
        "plan_code": norm_code,
        "plan_id": plan_id,
        "subscription_id": subscription_id,
        "activation_type": activation_type,
        "activation_sequence_key": activation_sequence_key,
        "payment_gateway": payment_gateway,
    }


def create_subscription_checkout(
    company_id: int,
    user_id: int,
    plan_code: str,
    customer_name: str,
    customer_email: str,
    customer_phone: str | None = None,
    *,
    payment_gateway: str | None = None,
) -> dict:
    """Validate the plan, create an order, and generate a hosted checkout.

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
        RuntimeError: If gateway checkout creation fails.
    """
    payment_gateway = payment_gateway or get_subscription_payment_gateway(company_id)
    prepared = prepare_subscription_checkout_order(
        company_id=company_id,
        user_id=user_id,
        plan_code=plan_code,
        payment_gateway=payment_gateway,
        allow_existing_reusable_checkout=True,
    )
    if prepared.get("existing_order"):
        return prepared

    order = prepared["order"]
    order_reference = prepared["order_reference"]
    amount_sen = prepared["amount_sen"]
    expires_at = prepared["expires_at"]
    norm_code = prepared["plan_code"]
    activation_sequence_key = prepared["activation_sequence_key"]

    try:
        if payment_gateway == "hitpay":
            bill = create_payment_request(
                config=HitPayConfig.from_env(),
                order_reference=order_reference,
                amount_sen=amount_sen,
                customer_name=customer_name,
                customer_email=customer_email,
                customer_phone=customer_phone,
                description=f"Subscription - {norm_code.title()}",
                expires_after=f"{_checkout_expiry_days()} day(s)",
            )
        else:
            bill = create_bill(
                order_reference=order_reference,
                amount_micro_myr=amount_sen * 10_000,
                customer_name=customer_name,
                customer_email=customer_email,
                customer_phone=customer_phone,
                description=f"Subscription - {norm_code.title()}",
                bill_expiry_days=_checkout_expiry_days(),
            )
    except (
        ValueError,
        HitPayConfigError,
        HitPayRequestRejectedError,
        ToyyibPayConfigError,
        ToyyibPayBillRejectedError,
    ) as exc:
        # Definite no-bill failures can release the source activation key.
        try:
            fail_pending_subscription_order_without_gateway_and_release_key(
                order_reference=order_reference,
                activation_sequence_key=activation_sequence_key,
                released_activation_sequence_key=_gateway_rejected_activation_sequence_key(
                    order, activation_sequence_key
                ),
            )
        except Exception:
            logger.exception(
                "Failed to release subscription order %s after definite no-bill error",
                order_reference,
            )
        logger.exception("Payment gateway bill creation was rejected for order %s", order_reference)
        raise RuntimeError(
            "Payment gateway bill creation failed. Please try again later."
        ) from exc
    except HitPayAmbiguousError as exc:
        try:
            update_subscription_order_activation_state(
                order_reference=order_reference,
                activation_error_code="gateway_create_ambiguous",
                activation_error_message="HitPay checkout creation requires reconciliation.",
                reconciliation_required=True,
            )
        except Exception:
            logger.exception(
                "Failed to mark HitPay order %s for reconciliation", order_reference
            )
        logger.exception(
            "HitPay checkout creation outcome is ambiguous for order %s", order_reference
        )
        raise RuntimeError(
            "Payment gateway checkout outcome is pending verification. "
            "Please do not retry yet."
        ) from exc
    except RuntimeError as exc:
        # Ambiguous gateway outcomes keep the canonical activation key so a
        # second payable bill cannot be created before support checks ToyyibPay.
        try:
            update_subscription_order_status(
                order_reference,
                "failed",
                activation_status=None,
                reconciliation_required=False,
            )
        except Exception:
            logger.exception(
                "Failed to mark subscription order %s as failed after ambiguous bill error",
                order_reference,
            )
        logger.exception("Payment gateway bill creation outcome is ambiguous for order %s", order_reference)
        raise RuntimeError(
            "Payment gateway bill creation failed. Please try again later."
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
        raise RuntimeError(
            "Payment checkout was created but could not be recorded safely. "
            "Please contact support before retrying."
        )

    logger.info(
        "Subscription checkout for company %d: reference=%s, gateway=%s",
        company_id, order_reference, gateway_order_id,
    )

    return {
        "order_reference": order_reference,
        "checkout_url": checkout_url,
        "amount_sen": amount_sen,
        "expires_at": expires_at,
        "payment_gateway": payment_gateway,
    }
