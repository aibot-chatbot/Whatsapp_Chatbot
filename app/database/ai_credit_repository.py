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
        .select("company_id,subscription_id,period_start,period_end,included_balance_micro_myr,topup_balance_micro_myr,created_at,updated_at")
        .eq("company_id", company_id)
        .limit(1)
        .execute()
    )

    rows = response.data or []
    return rows[0] if rows else None


def list_company_credit_transactions(
    company_id: int,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return recent credit transactions for a company, newest first.

    Args:
        company_id: The company to look up.
        limit: Maximum number of records to return (capped at 200).
        offset: Pagination offset.

    Returns:
        List of immutable transaction record dictionaries.

    Raises:
        ValueError: If company_id is not a positive integer.
    """
    _validate_company_id(company_id)

    safe_limit = max(1, min(int(limit), 200))
    safe_offset = max(0, int(offset))

    response = (
        supabase
        .table(_TRANSACTION_TABLE)
        .select("id,transaction_type,included_delta_micro_myr,topup_delta_micro_myr,included_balance_after_micro_myr,topup_balance_after_micro_myr,customer_charge_micro_myr,uncovered_charge_micro_myr,provider_cost_micro_usd,fx_rate_micro_myr_per_usd,markup_basis_points,ai_usage_log_id,reversal_of_transaction_id,period_start,period_end,description,created_at")
        .eq("company_id", company_id)
        .order("created_at", desc=True)
        .range(safe_offset, safe_offset + safe_limit - 1)
        .execute()
    )

    transactions = response.data or []
    return _attach_ai_usage_types(transactions)


def _attach_ai_usage_types(transactions: list[dict]) -> list[dict]:
    """Attach linked ai_usage_logs.operation_type to credit transactions.

    The credit ledger stores only ai_usage_log_id. The UI needs the linked
    operation type to distinguish chat replies from knowledge training.
    This lookup is read-only and best-effort: missing usage rows or lookup
    failures should not prevent the ledger from rendering.
    """
    usage_ids = sorted({
        txn.get("ai_usage_log_id")
        for txn in transactions
        if txn.get("ai_usage_log_id")
    })

    if not usage_ids:
        return transactions

    try:
        response = (
            supabase
            .table("ai_usage_logs")
            .select("id,operation_type")
            .in_("id", usage_ids)
            .execute()
        )
    except Exception as exc:
        logger.warning("Unable to enrich AI-credit transactions with usage types: %s", exc)
        return transactions

    usage_type_by_id = {
        row.get("id"): row.get("operation_type")
        for row in (response.data or [])
        if row.get("id")
    }

    for txn in transactions:
        usage_id = txn.get("ai_usage_log_id")
        if usage_id in usage_type_by_id:
            txn["ai_usage_type"] = usage_type_by_id[usage_id]

    return transactions


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
        .select("id,transaction_type,included_delta_micro_myr,topup_delta_micro_myr,included_balance_after_micro_myr,topup_balance_after_micro_myr,customer_charge_micro_myr,uncovered_charge_micro_myr,provider_cost_micro_usd,fx_rate_micro_myr_per_usd,markup_basis_points,ai_usage_log_id,reversal_of_transaction_id,period_start,period_end,description,created_at,company_id,subscription_id")
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

# ---------------------------------------------------------------------------
# Top-up
# ---------------------------------------------------------------------------


def add_ai_credit_topup(
    company_id: int,
    amount_micro_myr: int,
    idempotency_key: str,
    payment_reference: str,
    description: str | None = None,
) -> dict:
    """Atomically add top-up credit to a company's AI credit balance.

    Delegates to the PostgreSQL RPC function `add_ai_credit_topup` so
    that the balance update, ledger insert, and duplicate checks happen
    in a single database transaction.

    The RPC protects against duplicate idempotency keys and duplicate
    payment references, returning `already_applied` instead of
    creating a duplicate top-up.

    Args:
        company_id: The company to top up.
        amount_micro_myr: Amount of top-up credit in micro-MYR (must be
            a positive integer).
        idempotency_key: Unique key to prevent duplicate processing.
        payment_reference: External payment reference (e.g. gateway
            transaction ID).
        description: Optional human-readable description for the ledger
            entry.

    Returns:
        RPC result dictionary containing:
        - status: `"applied"` or `"already_applied"`
        - transaction_id
        - company_id
        - amount_micro_myr
        - included_balance_micro_myr
        - topup_balance_micro_myr
        - total_balance_micro_myr
        - payment_reference
        - idempotency_key

    Raises:
        ValueError: If company_id, amount, idempotency_key or
            payment_reference are invalid.
        RuntimeError: If the RPC call fails or returns no data.
    """
    _validate_company_id(company_id)
    _validate_topup_amount(amount_micro_myr)

    if not idempotency_key or not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError(
            f"idempotency_key must be a non-empty string, got {idempotency_key!r}"
        )
    if not payment_reference or not isinstance(payment_reference, str) or not payment_reference.strip():
        raise ValueError(
            f"payment_reference must be a non-empty string, got {payment_reference!r}"
        )

    params = {
        "p_company_id": company_id,
        "p_amount_micro_myr": amount_micro_myr,
        "p_idempotency_key": idempotency_key.strip(),
        "p_payment_reference": payment_reference.strip(),
        "p_description": description.strip() if description else None,
    }

    result = supabase.rpc(
        "add_ai_credit_topup",
        params,
    ).execute()

    data = result.data

    if not data or not isinstance(data, list) or len(data) == 0:
        raise RuntimeError(
            f"add_ai_credit_topup RPC returned no data for company {company_id}, "
            f"idempotency_key={idempotency_key!r}"
        )

    return data[0]

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
    """Atomically allocate subscription included AI credit to the included balance bucket.

    Delegates to the PostgreSQL RPC function ``allocate_subscription_included_credit``
    so that the balance update, ledger insert, and idempotency checks happen
    in a single database transaction.

    Unlike ``add_ai_credit_topup``, this function targets the **included** balance
    bucket (``included_balance_micro_myr``) rather than the top-up bucket.

    Args:
        company_id: The company to allocate credit for.
        amount_micro_myr: Amount of included credit in micro-MYR (positive integer).
        idempotency_key: Unique key to prevent duplicate allocation.
        payment_reference: External payment reference (e.g. callback transaction ID).
        period_start: ISO-8601 timestamp for the billing period start.
        period_end: ISO-8601 timestamp for the billing period end.
        plan_code: Plan code for description (optional).
        description: Custom description override (optional).

    Returns:
        RPC result dictionary containing:
        - status: ``"applied"`` or ``"already_applied"``
        - transaction_id
        - company_id
        - amount_micro_myr
        - included_balance_micro_myr
        - topup_balance_micro_myr
        - total_balance_micro_myr
        - payment_reference
        - idempotency_key

    Raises:
        ValueError: If company_id, amount, or idempotency_key are invalid.
        RuntimeError: If the RPC call fails or returns no data.
    """
    _validate_company_id(company_id)
    _validate_topup_amount(amount_micro_myr)

    if not idempotency_key or not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError(
            f"idempotency_key must be a non-empty string, got {idempotency_key!r}"
        )
    if not payment_reference or not isinstance(payment_reference, str) or not payment_reference.strip():
        raise ValueError(
            f"payment_reference must be a non-empty string, got {payment_reference!r}"
        )

    params = {
        "p_company_id": company_id,
        "p_amount_micro_myr": amount_micro_myr,
        "p_idempotency_key": idempotency_key.strip(),
        "p_payment_reference": payment_reference.strip(),
        "p_period_start": period_start,
        "p_period_end": period_end,
        "p_plan_code": plan_code.strip() if plan_code else None,
        "p_description": description.strip() if description else None,
    }

    result = supabase.rpc(
        "allocate_subscription_included_credit",
        params,
    ).execute()

    data = result.data

    if not data or not isinstance(data, list) or len(data) == 0:
        raise RuntimeError(
            f"allocate_subscription_included_credit RPC returned no data for "
            f"company {company_id}, idempotency_key={idempotency_key!r}"
        )

    return data[0]

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


def _validate_topup_amount(amount_micro_myr: int):
    if not isinstance(amount_micro_myr, int):
        raise ValueError(
            f"amount_micro_myr must be an integer, got {amount_micro_myr!r}"
        )
    if amount_micro_myr <= 0:
        raise ValueError(
            f"amount_micro_myr must be a positive integer, got {amount_micro_myr}"
        )


def list_company_credit_transactions_by_range(
    company_id: int,
    date_from: str,
    date_to: str,
) -> list[dict]:
    """Return credit transactions for a company within a date range.

    Used by billing reports. Returns same fields as list_company_credit_transactions
    but filtered by created_at range instead of limited by row count.

    Args:
        company_id: The company to look up.
        date_from: ISO date string (inclusive), matched against created_at.
        date_to: ISO date string (exclusive), matched against created_at.

    Returns:
        List of transaction record dictionaries.
    """
    _validate_company_id(company_id)
    try:
        response = (
            supabase
            .table(_TRANSACTION_TABLE)
            .select("id,transaction_type,included_delta_micro_myr,topup_delta_micro_myr,included_balance_after_micro_myr,topup_balance_after_micro_myr,customer_charge_micro_myr,provider_cost_micro_usd,ai_usage_log_id,description,created_at")
            .eq("company_id", company_id)
            .gte("created_at", date_from)
            .lt("created_at", date_to)
            .order("created_at", desc=False)
            .execute()
        )
        return response.data or []
    except Exception as exc:
        logger.error(
            "Error listing credit transactions by range for company %d: %s",
            company_id, exc,
        )
        return []
