"""Create pending subscription orders and hosted gateway checkouts."""

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from app.services.billing_service import get_current_subscription
from app.services.free_trial_status_service import (
    parse_iso_datetime,
    resolve_effective_subscription_status,
)
from app.database.subscription_plan_repository import get_plan_by_code
from app.database.company_subscription_order_repository import (
    attach_pending_subscription_gateway_details,
    create_subscription_order,
    get_subscription_order_by_reference,
    get_subscription_order_by_activation_sequence_key,
    fail_pending_subscription_order_without_gateway_and_release_key,
    update_subscription_order_activation_state,
)
from app.observability import capture_payment_failure
from app.services.chip_service import (
    ChipConfig,
    ChipConfigError,
    ChipRequestRejectedError,
    create_purchase,
    validate_checkout_url,
)
from app.services.subscription_term_pricing import (
    PAID_PLAN_CODES,
    get_subscription_term_price,
    normalize_billing_term_months,
)

logger = logging.getLogger(__name__)

_PAYMENT_GATEWAYS = frozenset({"chip"})

_VALID_PLAN_CODES = PAID_PLAN_CODES

_TERMINAL_ORDER_STATUSES = frozenset({"failed", "expired", "cancelled", "credited"})

_DEFAULT_CHECKOUT_EXPIRY_DAYS = 1
_MAX_CHECKOUT_EXPIRY_DAYS = 100
NULL_SOURCE_PERIOD_END_ACTIVATION_SENTINEL = "null-period-end"


def _clean(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _has_usable_checkout(order: dict) -> bool:
    if order.get("payment_gateway") != "chip" or not _clean(order.get("gateway_order_id")):
        return False
    config = ChipConfig.from_env()
    if (
        order.get("gateway_environment") != config.environment
        or order.get("gateway_brand_id") != config.brand_id
        or order.get("currency") != "MYR"
    ):
        return False
    try:
        validate_checkout_url(order.get("checkout_url"))
    except ValueError:
        return False
    return True


def get_subscription_payment_gateway(company_id: int | None = None) -> str:
    """CHIP is the only active payment gateway; historical provider rows remain."""
    return "chip"


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
    if days < 1 or days > _MAX_CHECKOUT_EXPIRY_DAYS:
        raise RuntimeError(
            "SUBSCRIPTION_CHECKOUT_EXPIRY_DAYS must be between 1 and 100"
        )
    return days


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _build_checkout_expires_at(now: datetime | None = None) -> str:
    base = now or _now_utc()
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    else:
        base = base.astimezone(timezone.utc)

    return (base + timedelta(days=_checkout_expiry_days())).replace(microsecond=0).isoformat()


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


def _is_pending_checkout_reusable(
    order: dict,
    expected_amount_sen: int | None = None,
    expected_billing_term_months: int | None = None,
) -> bool:
    if expected_amount_sen is not None and order.get("amount_sen") != expected_amount_sen:
        return False
    if (
        expected_billing_term_months is not None
        and (order.get("billing_term_months") or 1) != expected_billing_term_months
    ):
        return False
    return (
        _has_usable_checkout(order)
        and _parse_datetime(order.get("expires_at")) is not None
        and not _is_pending_checkout_expired(order)
    )


def _gateway_rejected_activation_sequence_key(order: dict, activation_sequence_key: str) -> str:
    order_id = order.get("id") or "unknown"
    return f"released:gateway-create-rejected:order:{order_id}:{activation_sequence_key}"


def _expire_existing_pending_checkout_if_needed(order: dict, activation_sequence_key: str) -> bool:
    # A local deadline cannot prove a provider purchase is no longer payable.
    # Legacy orders and ambiguous creates retain their activation claim.
    if order.get("payment_gateway") != "chip" or not order.get("gateway_order_id"):
        return False
    if not _is_pending_checkout_expired(order):
        return False
    order_reference = _clean(order.get("order_reference"))
    if not order_reference or not activation_sequence_key:
        return False
    from app.services.subscription_reconciliation_service import reconcile_subscription_order
    reconcile_subscription_order(order_reference, company_id=order.get("company_id"))
    current = get_subscription_order_by_reference(order_reference)
    return bool(
        current
        and current.get("status") in {"failed", "expired", "cancelled"}
        and current.get("activation_sequence_key") != activation_sequence_key
        and str(current.get("activation_sequence_key") or "").startswith("released:chip:")
    )


def _activation_sequence_conflict_message(
    existing_order: dict, expected_amount_sen: int | None = None
) -> str:
    status = (existing_order.get("status") or "").strip().lower()
    activation_status = (existing_order.get("activation_status") or "").strip().lower()

    if _is_incomplete_pending_checkout(existing_order):
        return (
            "A pending subscription checkout was started, but its payment link is not available. "
            "Please contact support so we can safely reset this checkout."
        )
    if status == "pending":
        if expected_amount_sen is not None and existing_order.get("amount_sen") != expected_amount_sen:
            return (
                "A pending subscription checkout uses an outdated price. "
                "Please contact support before retrying this checkout."
            )
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
        "billing_term_months": order.get("billing_term_months") or 1,
        "monthly_equivalent_sen": order.get("monthly_equivalent_sen") or amount_sen,
        "expires_at": order.get("expires_at"),
        "payment_gateway": "chip",
        "is_test": order.get("gateway_environment") == "test",
        "existing_order": True,
    }


def prepare_subscription_checkout_order(
    company_id: int,
    user_id: int,
    plan_code: str,
    *,
    billing_term_months: int = 1,
    payment_gateway: str = "chip",
    allow_existing_reusable_checkout: bool = False,
    config: ChipConfig | None = None,
) -> dict:
    """Create a pending subscription order without contacting a gateway."""
    payment_gateway = _clean(payment_gateway).lower()
    if payment_gateway not in _PAYMENT_GATEWAYS:
        raise ValueError("Unsupported subscription payment gateway")
    # --- Validate plan code ---
    norm_code = plan_code.strip().lower() if isinstance(plan_code, str) else ""
    if norm_code not in _VALID_PLAN_CODES:
        raise ValueError(
            f"Invalid plan code: {plan_code!r}. "
            f"Must be one of: {sorted(_VALID_PLAN_CODES)}"
        )
    config = config or ChipConfig.from_env()
    config.validate_for_checkout()

    # --- Look up the plan in the database ---
    plan = get_plan_by_code(norm_code)
    if not plan:
        raise ValueError(f"Plan code {norm_code!r} not found in the catalogue.")
    if not plan.get("is_active", False):
        raise ValueError(f"Plan {norm_code!r} is not available for purchase.")

    plan_id = plan["id"]
    term_price = get_subscription_term_price(norm_code, billing_term_months)
    billing_term_months = term_price["months"]
    amount_sen = term_price["amount_sen"]
    monthly_equivalent_sen = term_price["monthly_equivalent_sen"]

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
    raw_current_status = (subscription.get("status") or "").lower().strip()
    effective_fields = resolve_effective_subscription_status(
        subscription,
        current_plan,
    )
    current_status = raw_current_status
    if current_code != "free":
        current_status = (effective_fields.get("effective_status") or raw_current_status).lower().strip()
    source_period_end_raw = subscription.get("current_period_end")
    parsed_source_period_end = parse_iso_datetime(source_period_end_raw)
    null_period_end_recovery = (
        current_code != "free"
        and raw_current_status in ("active", "past_due")
        and current_status == "expired"
        and source_period_end_raw is None
    )
    malformed_period_recovery = (
        current_code != "free"
        and raw_current_status in ("active", "past_due")
        and current_status == "expired"
        and source_period_end_raw is not None
        and parsed_source_period_end is None
    )

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
    source_period_end = source_period_end_raw
    source_status = raw_current_status

    # Determine activation type for this order
    if current_status == "trialing":
        activation_type = "initial_purchase"
    elif current_status in ("expired", "past_due", "cancelled"):
        activation_type = "renewal"
    elif current_status == "active":
        activation_type = "upgrade"
    else:
        activation_type = "initial_purchase"

    # Generate deterministic activation_sequence_key at checkout time
    _trial_end = subscription.get("trial_ends_at") or "no-trial"
    if activation_type == "initial_purchase":
        activation_sequence_key = f"company:{company_id}:initial-from:{subscription_id}:trial:{_trial_end}"
    elif activation_type == "renewal":
        renewal_source_key = (
            NULL_SOURCE_PERIOD_END_ACTIVATION_SENTINEL
            if null_period_end_recovery
            else source_period_end
        )
        activation_sequence_key = f"company:{company_id}:renewal-after:{renewal_source_key}"
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
        if malformed_period_recovery:
            _missing.append("parseable_source_period_end")
        elif not source_period_end and not null_period_end_recovery:
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
            and _is_pending_checkout_reusable(
                existing_sequence_order,
                amount_sen,
                billing_term_months,
            )
        ):
            return _build_existing_checkout_result(existing_sequence_order)
        raise ValueError(
            _activation_sequence_conflict_message(existing_sequence_order, amount_sen)
        )

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
            billing_term_months=billing_term_months,
            monthly_equivalent_sen=monthly_equivalent_sen,
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
            order_schema_version=3,
            gateway_environment=config.environment,
            gateway_brand_id=config.brand_id,
            currency="MYR",
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
        "billing_term_months": billing_term_months,
        "monthly_equivalent_sen": monthly_equivalent_sen,
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
    billing_term_months: int = 1,
    payment_gateway: str | None = None,
) -> dict:
    """Create one mode-bound CHIP purchase for the authenticated company."""
    if not isinstance(plan_code, str) or plan_code.strip().lower() not in _VALID_PLAN_CODES:
        raise ValueError("Invalid subscription plan code")
    billing_term_months = normalize_billing_term_months(billing_term_months)
    payment_gateway = payment_gateway or get_subscription_payment_gateway(company_id)
    if payment_gateway != "chip":
        raise ValueError("Unsupported subscription payment gateway")
    config = ChipConfig.from_env()
    config.validate_for_checkout()
    prepared = prepare_subscription_checkout_order(
        company_id=company_id,
        user_id=user_id,
        plan_code=plan_code,
        billing_term_months=billing_term_months,
        payment_gateway=payment_gateway,
        allow_existing_reusable_checkout=True,
        config=config,
    )
    if prepared.get("existing_order"):
        return prepared

    order = prepared["order"]
    order_reference = prepared["order_reference"]
    amount_sen = prepared["amount_sen"]
    expires_at = prepared["expires_at"]
    activation_sequence_key = prepared["activation_sequence_key"]
    try:
        purchase = create_purchase(
            config=config,
            order_reference=order_reference,
            amount_sen=amount_sen,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            description=(
                f"Subscription - {prepared['plan_code'].title()} "
                f"({prepared['billing_term_months']} month term)"
            ),
            due=int(datetime.fromisoformat(expires_at).timestamp()),
        )
    except (ValueError, ChipConfigError, ChipRequestRejectedError) as exc:
        capture_payment_failure("checkout", reason="provider_rejected", mode=config.environment, exc=exc)
        try:
            fail_pending_subscription_order_without_gateway_and_release_key(
                order_reference=order_reference,
                activation_sequence_key=activation_sequence_key,
                released_activation_sequence_key=_gateway_rejected_activation_sequence_key(
                    order, activation_sequence_key
                ),
            )
        except Exception as persistence_error:
            capture_payment_failure("checkout", reason="persistence", mode=config.environment, exc=persistence_error)
        raise RuntimeError("Payment gateway purchase creation failed. Please try again later.") from exc
    except Exception as exc:
        capture_payment_failure("checkout", reason="provider_unavailable", mode=config.environment, exc=exc)
        _mark_checkout_for_reconciliation(order_reference, config.environment)
        raise RuntimeError(
            "Payment gateway checkout outcome is pending verification. Please do not retry yet."
        ) from exc

    try:
        gateway_order_id = _clean(purchase.get("gateway_order_id"))
        checkout_url = validate_checkout_url(purchase.get("checkout_url"))
        if (
            not gateway_order_id
            or purchase.get("is_test") is not config.is_test
            or purchase.get("brand_id") != config.brand_id
        ):
            raise ValueError("CHIP purchase identity does not match checkout configuration")
        attach_pending_subscription_gateway_details(
            order_reference=order_reference,
            payment_gateway="chip",
            gateway_order_id=gateway_order_id,
            checkout_url=checkout_url,
        )
    except Exception as exc:
        capture_payment_failure("checkout", reason="persistence", mode=config.environment, exc=exc)
        _mark_checkout_for_reconciliation(order_reference, config.environment)
        raise RuntimeError(
            "Payment checkout was created but could not be recorded safely. "
            "Please contact support before retrying."
        ) from exc

    return {
        "order_reference": order_reference,
        "checkout_url": checkout_url,
        "amount_sen": amount_sen,
        "billing_term_months": prepared["billing_term_months"],
        "monthly_equivalent_sen": prepared["monthly_equivalent_sen"],
        "expires_at": expires_at,
        "payment_gateway": "chip",
        "is_test": config.is_test,
    }


def _mark_checkout_for_reconciliation(order_reference: str, mode: str) -> None:
    try:
        update_subscription_order_activation_state(
            order_reference=order_reference,
            activation_error_code="gateway_create_ambiguous",
            activation_error_message="CHIP checkout creation requires operator reconciliation.",
            reconciliation_required=True,
        )
    except Exception as exc:
        capture_payment_failure("checkout", reason="persistence", mode=mode, exc=exc)
