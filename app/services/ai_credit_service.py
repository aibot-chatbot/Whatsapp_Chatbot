"""ai_credit_service.py -- Service layer for AI-credit operations.

This module sits between routes and the credit repository. It handles
configuration, input normalisation, and result formatting. All balance-
changing operations are delegated to PostgreSQL RPC functions via the
repository layer.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from app.database.ai_credit_repository import (
    get_company_credit_balance as _get_balance,
    list_company_credit_transactions as _list_transactions,
    list_company_credit_transactions_by_range_strict as _list_transactions_by_range_strict,
    get_credit_transaction_by_usage as _get_transaction_by_usage,
    ensure_company_ai_credit_period as _ensure_period,
    charge_ai_usage_credit as _charge_usage,
    add_ai_credit_topup as _add_topup,
    allocate_subscription_included_credit as _allocate_included_credit,
)
from app.database.ai_usage_repository import (
    list_company_completed_usage_by_range as _list_usage_by_range,
)

logger = logging.getLogger(__name__)

_ENV_KEY_ENFORCEMENT = "AI_CREDIT_ENFORCEMENT_ENABLED"
_ENV_KEY_MARKUP = "AI_RETAIL_MARKUP_BPS"

_ENV_KEY_FX_RATE = "AI_USD_TO_MYR_RATE_MICRO_MYR_PER_USD"

# Boolean string values accepted for the enforcement flag.
# Parsing is case-insensitive with whitespace stripped.
_TRUTHY_STRINGS = frozenset({"true", "1", "yes", "on"})
_FALSY_STRINGS = frozenset({"false", "0", "no", "off"})


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def is_ai_credit_enforcement_enabled() -> bool:
    """Check whether AI-credit enforcement is switched on.

    Reads ``AI_CREDIT_ENFORCEMENT_ENABLED`` from the environment.

    Returns:
        True when enforcement is enabled; False when absent, empty,
        or set to an recognised false value.

    Raises:
        ValueError: If the variable contains a value that is not a
                    recognised boolean string.
    """
    raw = os.getenv(_ENV_KEY_ENFORCEMENT)

    if raw is None or raw.strip() == "":
        return False

    cleaned = raw.strip().lower()

    if cleaned in _TRUTHY_STRINGS:
        return True
    if cleaned in _FALSY_STRINGS:
        return False

    raise ValueError(
        f"{_ENV_KEY_ENFORCEMENT} has an unrecognised value {raw!r}. "
        f"Accepted values: {', '.join(sorted(_TRUTHY_STRINGS))} "
        f"(true) or {', '.join(sorted(_FALSY_STRINGS))} (false)."
    )


def get_ai_retail_markup_basis_points() -> int:
    """Read the configured AI retail markup from the environment.

    The value is stored in basis points (100 bps = 1 %).

    Behaviour when ``AI_RETAIL_MARKUP_BPS`` is **present**:
        Strip whitespace, parse as integer, reject negative values,
        return the validated non-negative integer.

    Behaviour when ``AI_RETAIL_MARKUP_BPS`` is **absent or empty**:
        - If enforcement is disabled (default): return 0 and log a
          warning explaining that the value is temporary.
        - If enforcement is enabled: raise a ``RuntimeError`` to
          prevent silent zero-markup charging.

    Returns:
        Non-negative integer markup in basis points.

    Raises:
        ValueError: If the configured value is negative or not a valid integer.
        RuntimeError: If the variable is missing while enforcement is enabled.
    """
    raw = os.getenv(_ENV_KEY_MARKUP)

    if raw is None or raw.strip() == "":
        if is_ai_credit_enforcement_enabled():
            raise RuntimeError(
                f"{_ENV_KEY_MARKUP} is not set but AI-credit enforcement is enabled. "
                "Set a valid non-negative integer markup before enabling enforcement."
            )
        logger.warning(
            "%s is not set and AI-credit enforcement is disabled. "
            "Using 0 temporarily. Set %s before enabling enforcement.",
            _ENV_KEY_MARKUP, _ENV_KEY_MARKUP,
        )
        return 0

    try:
        value = int(raw.strip())
    except (ValueError, TypeError):
        raise ValueError(
            f"{_ENV_KEY_MARKUP} must be a non-negative integer, got {raw!r}"
        )

    if value < 0:
        raise ValueError(
            f"{_ENV_KEY_MARKUP} must be non-negative, got {value}"
        )

    return value


# ---------------------------------------------------------------------------
# FX rate configuration
# ---------------------------------------------------------------------------


def get_ai_usd_to_myr_rate_micro_myr_per_usd() -> int:
    """Read the configured USD-to-MYR exchange rate from the environment.

    The value is stored as micro-MYR per whole USD.
    Example: 4_500_000 means RM 4.50 per USD.

    Behaviour:
        - Present: parse as positive integer.
        - Absent/empty + enforcement disabled: return 0 with a warning.
        - Absent/empty + enforcement enabled: raise RuntimeError.
        - Zero, negative, non-integer, malformed: always raise ValueError.

    Returns:
        Positive integer exchange rate in micro-MYR per USD, or 0 when
        enforcement is disabled and the value is not configured.

    Raises:
        ValueError: If the configured value is zero, negative, non-integer.
        RuntimeError: If the variable is missing while enforcement is enabled.
    """
    raw = os.getenv(_ENV_KEY_FX_RATE)

    if raw is None or raw.strip() == "":
        if is_ai_credit_enforcement_enabled():
            raise RuntimeError(
                f"{_ENV_KEY_FX_RATE} is not set but AI-credit enforcement is enabled. "
                "Set a valid positive integer exchange rate before enabling enforcement."
            )
        logger.warning(
            "%s is not set and AI-credit enforcement is disabled. "
            "Using 0 temporarily. Set %s before enabling enforcement.",
            _ENV_KEY_FX_RATE, _ENV_KEY_FX_RATE,
        )
        return 0

    try:
        value = int(raw.strip())
    except (ValueError, TypeError):
        raise ValueError(
            f"{_ENV_KEY_FX_RATE} must be a positive integer, got {raw!r}"
        )

    if value <= 0:
        raise ValueError(
            f"{_ENV_KEY_FX_RATE} must be a positive integer, got {value}"
        )

    return value


# ---------------------------------------------------------------------------
# Balance and summary
# ---------------------------------------------------------------------------


def get_company_ai_credit_summary(company_id: int) -> dict:
    """Return a human-friendly AI-credit summary for a company.

    Args:
        company_id: The company to look up.

    Returns:
        Dictionary with keys:
        - included_balance_micro_myr
        - topup_balance_micro_myr
        - total_balance_micro_myr (included + topup)
        - period_start (str or None)
        - period_end (str or None)
        - subscription_id (int or None)
        - initialised (bool): True when a balance row exists.
    """
    balance = _get_balance(company_id)

    if balance is None:
        return {
            "included_balance_micro_myr": None,
            "topup_balance_micro_myr": None,
            "total_balance_micro_myr": None,
            "period_start": None,
            "period_end": None,
            "subscription_id": None,
            "initialised": False,
            "currency": "MYR",
            "unit": "micro_myr",
        }

    included = balance.get("included_balance_micro_myr") or 0
    topup = balance.get("topup_balance_micro_myr") or 0

    return {
        "included_balance_micro_myr": included,
        "topup_balance_micro_myr": topup,
        "total_balance_micro_myr": included + topup,
        "period_start": balance.get("period_start"),
        "period_end": balance.get("period_end"),
        "subscription_id": balance.get("subscription_id"),
        "initialised": True,
        "currency": "MYR",
        "unit": "micro_myr",
    }


def list_credit_transactions(
    company_id: int,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return recent AI-credit transactions for a company.

    This is a thin pass-through to the repository; it exists so that
    routes can depend on the service layer rather than the repository
    directly.

    Args:
        company_id: The company to look up.
        limit: Maximum number of records (capped at 200).
        offset: Pagination offset.

    Returns:
        List of transaction record dictionaries.
    """
    return _list_transactions(company_id, limit=limit, offset=offset)


def get_company_ai_usage_analytics(company_id: int, days: int = 30) -> dict:
    """Return tenant-facing AI usage analytics for a bounded recent period."""
    if not company_id or not isinstance(company_id, int) or company_id < 1:
        raise ValueError("company_id must be a positive integer")

    safe_days = int(days)
    if safe_days not in (7, 30, 90):
        raise ValueError("days must be one of: 7, 30, 90")

    date_to = _next_utc_midnight()
    date_from = date_to - timedelta(days=safe_days)
    date_from_iso = date_from.isoformat()
    date_to_iso = date_to.isoformat()

    usage_rows = _list_usage_by_range(company_id, date_from_iso, date_to_iso)
    credit_rows = _list_transactions_by_range_strict(company_id, date_from_iso, date_to_iso)
    balance = _get_balance(company_id)

    usage_by_id = {
        row.get("id"): row
        for row in usage_rows
        if row.get("id") is not None
    }
    charge_by_usage_id = {}

    spend_days = _empty_daily_buckets(date_from, safe_days)
    token_days = _empty_daily_buckets(date_from, safe_days)
    request_days = _empty_daily_buckets(date_from, safe_days)
    total_spend = 0
    legacy_spend = 0
    linked_spend = 0

    for txn in credit_rows:
        if (txn.get("transaction_type") or "").lower() != "usage_debit":
            continue
        charged = _usage_charge_micro_myr(txn)
        total_spend += charged
        day_key = _day_key(txn.get("created_at"))
        if day_key in spend_days:
            spend_days[day_key]["spent_micro_myr"] += charged
        usage_id = txn.get("ai_usage_log_id")
        if usage_id:
            charge_by_usage_id[usage_id] = charge_by_usage_id.get(usage_id, 0) + charged
            if usage_id in usage_by_id:
                linked_spend += charged
            else:
                legacy_spend += charged
        else:
            legacy_spend += charged

    total_prompt = 0
    total_completion = 0
    total_tokens = 0
    model_map = {}
    model_daily_map = {}
    operation_map = {}
    provider_map = {}
    unknown_model_count = 0

    for usage in usage_rows:
        prompt_tokens = _safe_int(usage.get("prompt_tokens"))
        completion_tokens = _safe_int(usage.get("completion_tokens"))
        tokens = _safe_int(usage.get("total_tokens")) or (prompt_tokens + completion_tokens)
        total_prompt += prompt_tokens
        total_completion += completion_tokens
        total_tokens += tokens

        day_key = _day_key(usage.get("created_at"))
        if day_key in token_days:
            token_days[day_key]["input_tokens"] += prompt_tokens
            token_days[day_key]["output_tokens"] += completion_tokens
            token_days[day_key]["total_tokens"] += tokens
        if day_key in request_days:
            request_days[day_key]["request_count"] = request_days[day_key].get("request_count", 0) + 1

        model_name = (usage.get("model") or "").strip()
        provider = (usage.get("provider") or "").strip()
        operation_type = (usage.get("operation_type") or "").strip()
        usage_charge = charge_by_usage_id.get(usage.get("id"), 0)

        if model_name:
            model_row = model_map.setdefault(model_name, {
                "model": model_name,
                "provider": provider or None,
                "request_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "customer_charge_micro_myr": 0,
            })
            model_row["request_count"] += 1
            model_row["input_tokens"] += prompt_tokens
            model_row["output_tokens"] += completion_tokens
            model_row["total_tokens"] += tokens
            model_row["customer_charge_micro_myr"] += usage_charge
            if not model_row.get("provider") and provider:
                model_row["provider"] = provider
            model_daily_row = model_daily_map.setdefault(model_name, {
                "model": model_name,
                "provider": provider or None,
                "days": _empty_daily_buckets(date_from, safe_days),
            })
            if not model_daily_row.get("provider") and provider:
                model_daily_row["provider"] = provider
            if day_key in model_daily_row["days"]:
                model_daily_row["days"][day_key]["input_tokens"] += prompt_tokens
                model_daily_row["days"][day_key]["output_tokens"] += completion_tokens
                model_daily_row["days"][day_key]["total_tokens"] += tokens
                model_daily_row["days"][day_key]["request_count"] = model_daily_row["days"][day_key].get("request_count", 0) + 1
        else:
            unknown_model_count += 1

        if operation_type:
            operation_row = operation_map.setdefault(operation_type, {
                "operation_type": operation_type,
                "request_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "customer_charge_micro_myr": 0,
            })
            operation_row["request_count"] += 1
            operation_row["input_tokens"] += prompt_tokens
            operation_row["output_tokens"] += completion_tokens
            operation_row["total_tokens"] += tokens
            operation_row["customer_charge_micro_myr"] += usage_charge

        if provider:
            provider_row = provider_map.setdefault(provider, {
                "provider": provider,
                "request_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "customer_charge_micro_myr": 0,
            })
            provider_row["request_count"] += 1
            provider_row["input_tokens"] += prompt_tokens
            provider_row["output_tokens"] += completion_tokens
            provider_row["total_tokens"] += tokens
            provider_row["customer_charge_micro_myr"] += usage_charge

    model_rows = sorted(
        model_map.values(),
        key=lambda row: (row["total_tokens"], row["customer_charge_micro_myr"], row["request_count"]),
        reverse=True,
    )
    provider_rows = sorted(
        provider_map.values(),
        key=lambda row: (row["total_tokens"], row["customer_charge_micro_myr"], row["request_count"]),
        reverse=True,
    )
    operation_rows = sorted(
        operation_map.values(),
        key=lambda row: (row["total_tokens"], row["customer_charge_micro_myr"], row["request_count"]),
        reverse=True,
    )
    model_daily_rows = []
    for model_row in model_rows:
        daily_row = model_daily_map.get(model_row["model"])
        if daily_row:
            model_daily_rows.append({
                "model": daily_row["model"],
                "provider": daily_row.get("provider"),
                "days": list(daily_row["days"].values()),
            })

    most_used_model = model_rows[0]["model"] if model_rows else None
    if most_used_model is None and legacy_spend:
        most_used_model = "Unknown / Legacy"

    included_balance = None
    topup_balance = None
    total_balance = None
    if balance is not None:
        included_balance = _safe_int(balance.get("included_balance_micro_myr"))
        topup_balance = _safe_int(balance.get("topup_balance_micro_myr"))
        total_balance = included_balance + topup_balance

    return {
        "period": {
            "days": safe_days,
            "label": f"Last {safe_days} days",
            "start": date_from_iso,
            "end": date_to_iso,
        },
        "summary": {
            "ai_credit_balance_micro_myr": total_balance,
            "included_balance_micro_myr": included_balance,
            "topup_balance_micro_myr": topup_balance,
            "ai_spend_micro_myr": total_spend,
            "total_tokens": total_tokens,
            "input_tokens": total_prompt,
            "output_tokens": total_completion,
            "most_used_model": most_used_model,
            "usage_count": len(usage_rows),
            "request_count": len(usage_rows),
            "average_cost_per_million_tokens_micro_myr": (
                round(total_spend * 1000000 / total_tokens)
                if total_tokens > 0 else None
            ),
        },
        "spend_trend": list(spend_days.values()),
        "token_trend": list(token_days.values()),
        "request_trend": list(request_days.values()),
        "models": model_rows,
        "model_daily_usage": model_daily_rows,
        "operations": operation_rows,
        "providers": provider_rows,
        "legacy": {
            "usage_debit_without_usage_log_count": sum(
                1 for txn in credit_rows
                if (txn.get("transaction_type") or "").lower() == "usage_debit"
                and not txn.get("ai_usage_log_id")
            ),
            "usage_debit_with_missing_usage_log_count": sum(
                1 for txn in credit_rows
                if (txn.get("transaction_type") or "").lower() == "usage_debit"
                and txn.get("ai_usage_log_id")
                and txn.get("ai_usage_log_id") not in usage_by_id
            ),
            "usage_logs_without_model_count": unknown_model_count,
            "legacy_spend_micro_myr": legacy_spend,
            "linked_spend_micro_myr": linked_spend,
        },
        "currency": "MYR",
        "unit": "micro_myr",
    }


def _next_utc_midnight() -> datetime:
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return today + timedelta(days=1)


def _empty_daily_buckets(start: datetime, days: int) -> dict:
    buckets = {}
    for offset in range(days):
        day = start + timedelta(days=offset)
        key = day.date().isoformat()
        buckets[key] = {
            "date": key,
            "spent_micro_myr": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "request_count": 0,
        }
    return buckets


def _day_key(raw_value) -> str | None:
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).date().isoformat()


def _safe_int(value) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _usage_charge_micro_myr(txn: dict) -> int:
    explicit = txn.get("customer_charge_micro_myr")
    if explicit is not None:
        return max(0, _safe_int(explicit))
    return abs(_safe_int(txn.get("included_delta_micro_myr"))) + abs(_safe_int(txn.get("topup_delta_micro_myr")))


# ---------------------------------------------------------------------------
# Period initialisation
# ---------------------------------------------------------------------------


def ensure_company_ai_credit(company_id: int) -> dict:
    """Initialise or renew the AI-credit period for a company.

    Delegates to the PostgreSQL RPC function.  The RPC handles period
    detection, included-credit grant, balance expiry for the previous
    period, and ledger inserts atomically.

    Args:
        company_id: The company whose credit period to initialise.

    Returns:
        RPC result dictionary (see repository docstring).
    """
    return _ensure_period(company_id)


# ---------------------------------------------------------------------------
# Usage charging
# ---------------------------------------------------------------------------


def charge_logged_ai_usage(
    ai_usage_log_id: int,
    markup_basis_points: int | None = None,
    fx_rate_micro_myr_per_usd: int | None = None,
) -> dict:
    """Charge a completed AI usage against the company's credit.

    Steps performed (all atomically in the RPC):
    1. Read the usage log row.
    2. Resolve the company and subscription.
    3. Calculate the customer charge using markup and USD-to-MYR FX rate.
    4. Deduct from the balance (included credit first, then top-up).
    5. Insert an immutable credit-transaction record.
    6. Return the complete result including balances after charge.

    When markup_basis_points or fx_rate_micro_myr_per_usd are not
    supplied, they are read from the current configuration.  The
    explicit parameters allow the caller to pass request-time
    snapshots so that a configuration change between the provider
    request and the charge call does not affect the customer charge.

    Args:
        ai_usage_log_id: The AI usage log entry to charge.
        markup_basis_points: Override markup (optional, from config if None).
        fx_rate_micro_myr_per_usd: Override FX rate (optional, from config if None).

    Returns:
        RPC result dictionary.

    Raises:
        ValueError: If the usage-log ID is invalid.
        RuntimeError: If configuration validation fails, or if the
                      RPC call itself fails.
    """
    markup = markup_basis_points if markup_basis_points is not None else get_ai_retail_markup_basis_points()
    fx_rate = fx_rate_micro_myr_per_usd if fx_rate_micro_myr_per_usd is not None else get_ai_usd_to_myr_rate_micro_myr_per_usd()
    return _charge_usage(ai_usage_log_id, markup, fx_rate)

# ---------------------------------------------------------------------------
# Top-up
# ---------------------------------------------------------------------------


def add_company_ai_credit_topup(
    company_id: int,
    amount_micro_myr: int,
    idempotency_key: str,
    payment_reference: str,
    description: str | None = None,
) -> dict:
    """Add top-up credit to a company's AI credit balance.

    This function is intended for authenticated internal use only. It is
    not exposed directly via any public API endpoint.

    Steps performed (all atomically in the RPC):
    1. Validates all input parameters.
    2. Calls the `add_ai_credit_topup` RPC.
    3. Returns a structured result with the new balances.

    Args:
        company_id: The company to top up (must be a positive integer).
        amount_micro_myr: Amount in micro-MYR (must be a positive integer).
        idempotency_key: Unique key to prevent duplicate processing
            (must be a non-empty string).
        payment_reference: External payment reference (must be a non-empty
            string, e.g. gateway transaction ID).
        description: Optional human-readable description for the ledger
            entry.

    Returns:
        Dictionary containing:
        - status: `"applied"` or `"already_applied"`
        - transaction_id (int or None)
        - company_id (int)
        - amount_micro_myr (int)
        - included_balance_micro_myr (int)
        - topup_balance_micro_myr (int)
        - total_balance_micro_myr (int)
        - payment_reference (str)
        - idempotency_key (str)

    Raises:
        ValueError: If any input parameter is invalid.
        RuntimeError: If the RPC call fails or returns no data.
    """
    if not company_id or not isinstance(company_id, int) or company_id < 1:
        raise ValueError(
            f"company_id must be a positive integer, got {company_id!r}"
        )
    if not isinstance(amount_micro_myr, int) or amount_micro_myr <= 0:
        raise ValueError(
            f"amount_micro_myr must be a positive integer, got {amount_micro_myr!r}"
        )
    if not idempotency_key or not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError(
            "idempotency_key must be a non-empty string"
        )
    if not payment_reference or not isinstance(payment_reference, str) or not payment_reference.strip():
        raise ValueError(
            "payment_reference must be a non-empty string"
        )

    result = _add_topup(
        company_id=company_id,
        amount_micro_myr=amount_micro_myr,
        idempotency_key=idempotency_key.strip(),
        payment_reference=payment_reference.strip(),
        description=description.strip() if description else None,
    )

    included = result.get("included_balance_micro_myr", 0) or 0
    topup = result.get("topup_balance_micro_myr", 0) or 0

    return {
        "status": result.get("status"),
        "transaction_id": result.get("transaction_id"),
        "company_id": result.get("company_id", company_id),
        "amount_micro_myr": result.get("amount_micro_myr", amount_micro_myr),
        "included_balance_micro_myr": included,
        "topup_balance_micro_myr": topup,
        "total_balance_micro_myr": included + topup,
        "payment_reference": result.get("payment_reference", payment_reference),
        "idempotency_key": result.get("idempotency_key", idempotency_key),
    }
# ---------------------------------------------------------------------------
# Subscription included credit
# ---------------------------------------------------------------------------


def allocate_subscription_included_credit(
    company_id: int,
    amount_micro_myr: int,
    idempotency_key: str,
    payment_reference: str,
    period_start: str | None = None,
    period_end: str | None = None,
    plan_code: str | None = None,
    description: str | None = None,
) -> dict:
    """Allocate subscription included AI credit to the correct balance bucket.

    This is the canonical function for granting subscription-period included
    credit.  It delegates to the PostgreSQL RPC ``allocate_subscription_included_credit``
    which targets the **included** balance bucket (``included_balance_micro_myr``),
    not the top-up bucket.

    Unlike ``add_company_ai_credit_topup``, this function is designed for
    subscription plan credit allocation and should be the only code path
    that grants included credit for a new billing period.

    Steps performed (all atomically in the RPC):
    1. Checks idempotency by ``idempotency_key``.
    2. Adds the amount to ``included_balance_micro_myr`` (not top-up).
    3. Inserts a ledger entry with ``transaction_type = 'subscription_included'``.
    4. Returns structured result with both included and top-up balances.

    Args:
        company_id: The company to allocate credit for.
        amount_micro_myr: Amount in micro-MYR (must be a positive integer).
        idempotency_key: Unique key to prevent duplicate allocation.
        payment_reference: External payment reference (gateway transaction ID).
        period_start: ISO-8601 timestamp for the billing period start.
        period_end: ISO-8601 timestamp for the billing period end.
        plan_code: Plan code for the description (e.g. "pro").
        description: Custom description override.

    Returns:
        Dictionary containing:
        - status: ``"applied"`` or ``"already_applied"``
        - transaction_id (int or None)
        - company_id (int)
        - amount_micro_myr (int)
        - included_balance_micro_myr (int)
        - topup_balance_micro_myr (int)
        - total_balance_micro_myr (int)
        - payment_reference (str)
        - idempotency_key (str)

    Raises:
        ValueError: If any input parameter is invalid.
        RuntimeError: If the RPC call fails or returns no data.
    """
    if not company_id or not isinstance(company_id, int) or company_id < 1:
        raise ValueError(f"company_id must be a positive integer, got {company_id!r}")
    if not isinstance(amount_micro_myr, int) or amount_micro_myr <= 0:
        raise ValueError(f"amount_micro_myr must be a positive integer, got {amount_micro_myr!r}")
    if not idempotency_key or not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError("idempotency_key must be a non-empty string")
    if not payment_reference or not isinstance(payment_reference, str) or not payment_reference.strip():
        raise ValueError("payment_reference must be a non-empty string")

    result = _allocate_included_credit(
        company_id=company_id,
        amount_micro_myr=amount_micro_myr,
        idempotency_key=idempotency_key.strip(),
        payment_reference=payment_reference.strip(),
        period_start=period_start,
        period_end=period_end,
        plan_code=plan_code.strip().lower() if plan_code else None,
        description=description.strip() if description else None,
    )

    included = result.get("included_balance_micro_myr", 0) or 0
    topup = result.get("topup_balance_micro_myr", 0) or 0

    return {
        "status": result.get("status"),
        "transaction_id": result.get("transaction_id"),
        "company_id": result.get("company_id", company_id),
        "amount_micro_myr": result.get("amount_micro_myr", amount_micro_myr),
        "included_balance_micro_myr": included,
        "topup_balance_micro_myr": topup,
        "total_balance_micro_myr": included + topup,
        "payment_reference": result.get("payment_reference", payment_reference),
        "idempotency_key": result.get("idempotency_key", idempotency_key),
    }
