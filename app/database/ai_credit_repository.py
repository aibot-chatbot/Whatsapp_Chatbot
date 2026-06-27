"""ai_credit_repository.py -- Read-only and RPC-wrapper access for AI credit balances and transactions.

This repository provides read access to the immutable credit-transaction ledger
and the current company credit balance. All balance-changing operations are
delegated to PostgreSQL RPC functions for atomicity.

No Python code in this file should directly INSERT, UPDATE, or DELETE rows
in `company_ai_credit_balances` or `ai_credit_transactions`.
"""

import logging
from typing import Any

from app.database.db import supabase

logger = logging.getLogger(__name__)

_BALANCE_TABLE = "company_ai_credit_balances"
_TRANSACTION_TABLE = "ai_credit_transactions"


# ---------------------------------------------------------------------------
# Read functions
# ---------------------------------------------------------------------------


def get_company_credit_balance(company_id: int) -> dict | None:
    """Return the current AI-credit balance row for a company.

    Args:
        company_id: The company to look up.

    Returns:
        One balance-row dictionary, or None when the company has no balance
        row (credit period has not been initialised).

    Raises:
        ValueError: If company_id is not a positive integer.
    """
    _validate_company_id(company_id)

    response = (
        supabase
        .table(_BALANCE_TABLE)
        .select("*")
        .eq("company_id", company_id)
        .limit(1)
        .execute()
    )

    rows = response.data or []
    return rows[0] if rows else None


def list_company_credit_transactions(
    company_id: int,
    limit: int = 50,
) -> list[dict]:
    """Return recent credit transactions for a company, newest first.

    Args:
        company_id: The company to look up.
        limit: Maximum number of records to return (capped at 200).

    Returns:
        List of immutable transaction record dictionaries.

    Raises:
        ValueError: If company_id is not a positive integer.
    """
    _validate_company_id(company_id)

    safe_limit = max(1, min(int(limit), 200))

    response = (
        supabase
        .table(_TRANSACTION_TABLE)
        .select("*")
        .eq("company_id", company_id)
        .order("created_at", desc=True)
        .limit(safe_limit)
        .execute()
    )

    return response.data or []


def get_credit_transaction_by_usage(ai_usage_log_id: int) -> dict | None:
    """Return the existing debit transaction for a given usage-log entry.

    This supports idempotency checks: if an AI usage log already has an
    associated debit transaction, charging it again should be rejected.

    Args:
        ai_usage_log_id: The AI usage log ID to look up.

    Returns:
        The credit-transaction dictionary, or None if no debit transaction
        exists yet for this usage log.

    Raises:
        ValueError: If ai_usage_log_id is not a positive integer.
    """
    if not ai_usage_log_id or not isinstance(ai_usage_log_id, int) or ai_usage_log_id < 1:
        raise ValueError(
            f"ai_usage_log_id must be a positive integer, got {ai_usage_log_id!r}"
        )

    response = (
        supabase
        .table(_TRANSACTION_TABLE)
        .select("*")
        .eq("ai_usage_log_id", ai_usage_log_id)
        .limit(1)
        .execute()
    )

    rows = response.data or []
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# RPC wrappers
# ---------------------------------------------------------------------------


def ensure_company_ai_credit_period(company_id: int) -> dict:
    """Initialise or renew the AI-credit period for a company.

    Delegates the entire operation to the PostgreSQL RPC function
    ensure_company_ai_credit_period so that the grant, expiry,
    and balance updates happen in a single database transaction.

    Args:
        company_id: The company whose credit period to initialise or renew.

    Returns:
        RPC result dictionary containing:
        - company_id
        - subscription_id
        - period_start
        - period_end
        - included_balance_micro_myr
        - topup_balance_micro_myr
        - included_credit_granted_micro_myr
        - period_changed (bool)
        - transaction_id (nullable)

    Raises:
        ValueError: If company_id is not a positive integer.
        RuntimeError: If the RPC call fails or returns no data.
    """
    _validate_company_id(company_id)

    result = supabase.rpc(
        "ensure_company_ai_credit_period",
        {"p_company_id": company_id},
    ).execute()

    data = result.data

    if not data or not isinstance(data, list) or len(data) == 0:
        raise RuntimeError(
            f"ensure_company_ai_credit_period RPC returned no data for company {company_id}"
        )

    return data[0]


def charge_ai_usage_credit(
    ai_usage_log_id: int,
    markup_basis_points: int,
    fx_rate_micro_myr_per_usd: int,
) -> dict:
    """Atomically charge a completed AI usage against a company's credit.

    Delegates the entire operation to the PostgreSQL RPC function
    charge_ai_usage_credit so that the usage check, balance check,
    cost calculation, deduction, and ledger insert happen in a single
    database transaction.

    Args:
        ai_usage_log_id: The AI usage log to charge.
        markup_basis_points: Retail markup in basis points (integer).
        fx_rate_micro_myr_per_usd: USD-to-MYR exchange rate in micro-MYR per
            whole USD (positive integer).

    Returns:
        RPC result dictionary containing:
        - status: "charged", "already_charged", "unknown_cost",
                  "no_active_subscription", "no_balance",
                  "usage_not_found"
        - transaction_id
        - company_id
        - subscription_id
        - ai_usage_log_id
        - provider_cost_micro_usd
        - customer_charge_micro_myr
        - included_used_micro_myr
        - topup_used_micro_myr
        - uncovered_charge_micro_myr
        - included_balance_micro_myr
        - topup_balance_micro_myr
        - markup_basis_points
        - fx_rate_micro_myr_per_usd

    Raises:
        ValueError: If ai_usage_log_id is not a positive integer, or
                    markup_basis_points is negative, or fx_rate is invalid.
        RuntimeError: If the RPC call fails or returns no data.
    """
    if not ai_usage_log_id or not isinstance(ai_usage_log_id, int) or ai_usage_log_id < 1:
        raise ValueError(
            f"ai_usage_log_id must be a positive integer, got {ai_usage_log_id!r}"
        )
    _validate_non_negative_markup(markup_basis_points)
    _validate_positive_fx_rate(fx_rate_micro_myr_per_usd)

    result = supabase.rpc(
        "charge_ai_usage_credit",
        {
            "p_ai_usage_log_id": ai_usage_log_id,
            "p_markup_basis_points": markup_basis_points,
            "p_fx_rate_micro_myr_per_usd": fx_rate_micro_myr_per_usd,
        },
    ).execute()

    data = result.data

    if not data or not isinstance(data, list) or len(data) == 0:
        raise RuntimeError(
            f"charge_ai_usage_credit RPC returned no data for ai_usage_log_id {ai_usage_log_id}"
        )

    return data[0]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_company_id(company_id: int):
    if not company_id or not isinstance(company_id, int) or company_id < 1:
        raise ValueError(
            f"company_id must be a positive integer, got {company_id!r}"
        )


def _validate_non_negative_markup(markup_basis_points: int):
    if not isinstance(markup_basis_points, int):
        raise ValueError(
            f"markup_basis_points must be an integer, got {markup_basis_points!r}"
        )
    if markup_basis_points < 0:
        raise ValueError(
            f"markup_basis_points must be non-negative, got {markup_basis_points!r}"
        )


def _validate_positive_fx_rate(fx_rate_micro_myr_per_usd: int):
    if not isinstance(fx_rate_micro_myr_per_usd, int):
        raise ValueError(
            f"fx_rate_micro_myr_per_usd must be an integer, got {fx_rate_micro_myr_per_usd!r}"
        )
    if fx_rate_micro_myr_per_usd <= 0:
        raise ValueError(
            f"fx_rate_micro_myr_per_usd must be a positive integer, got {fx_rate_micro_myr_per_usd}"
        )

