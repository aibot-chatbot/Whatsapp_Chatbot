"""ai_credit_service.py -- Service layer for AI-credit operations.

This module sits between routes and the credit repository. It handles
configuration, input normalisation, and result formatting. All balance-
changing operations are delegated to PostgreSQL RPC functions via the
repository layer.
"""

import logging
import os

from app.database.ai_credit_repository import (
    get_company_credit_balance as _get_balance,
    list_company_credit_transactions as _list_transactions,
    get_credit_transaction_by_usage as _get_transaction_by_usage,
    ensure_company_ai_credit_period as _ensure_period,
    charge_ai_usage_credit as _charge_usage,
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
    }


def list_credit_transactions(
    company_id: int,
    limit: int = 50,
) -> list[dict]:
    """Return recent AI-credit transactions for a company.

    This is a thin pass-through to the repository; it exists so that
    routes can depend on the service layer rather than the repository
    directly.

    Args:
        company_id: The company to look up.
        limit: Maximum number of records (capped at 200).

    Returns:
        List of transaction record dictionaries.
    """
    return _list_transactions(company_id, limit=limit)


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
