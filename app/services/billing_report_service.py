"""billing_report_service.py - Company-scoped billing and usage reporting.

Provides aggregated billing reports including monthly summaries, trends,
plan usage, and CSV exports. All calculations use integer micro-MYR
arithmetic internally and convert to display MYR only at output.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MICRO_MYR_PER_MYR = 100_000_000


def _micro_myr_to_myr(value: int | float | str | None) -> float:
    """Convert micro-MYR to display MYR."""
    try:
        return round(int(value or 0) / _MICRO_MYR_PER_MYR, 2)
    except (ValueError, TypeError):
        return 0.0


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _first_of_month(dt: datetime) -> datetime:
    """Return first day of the month at midnight UTC."""
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _parse_date(date_str: str) -> datetime | None:
    """Parse an ISO date string (YYYY-MM-DD) to UTC datetime at start of day."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Billing summary  subscription orders
# ---------------------------------------------------------------------------

def _summarize_subscription_orders(company_id: int, date_from: str, date_to: str) -> dict:
    """Aggregate subscription payment orders for a company over a date range.

    Returns dict with counts and totals per payment status.
    """
    from app.database.company_subscription_order_repository import list_billing_report_orders

    orders = list_billing_report_orders(company_id, date_from, date_to)

    result = {
        "orders_created": 0,
        "payments_completed": 0,
        "payments_pending": 0,
        "payments_failed": 0,
        "gross_paid_micro_myr": 0,
        "gross_paid_myr": 0.0,
        "plans": {},
    }

    for order in orders:
        result["orders_created"] += 1
        status = (order.get("status") or "").strip().lower()

        if status == "credited":
            result["payments_completed"] += 1
            amount_sen = int(order.get("amount_sen", 0) or 0)
            amount_micro = amount_sen * 1_000_000  # sen to micro-MYR
            result["gross_paid_micro_myr"] += amount_micro
            plan_code = (order.get("plan_code") or "unknown").lower()
            result["plans"][plan_code] = result["plans"].get(plan_code, 0) + 1
        elif status in ("pending", "paid"):
            result["payments_pending"] += 1
        elif status in ("failed", "expired"):
            result["payments_failed"] += 1

    result["gross_paid_myr"] = _micro_myr_to_myr(result["gross_paid_micro_myr"])
    return result


# ---------------------------------------------------------------------------
# AI credit summary
# ---------------------------------------------------------------------------

def _summarize_ai_credit(company_id: int, date_from: str, date_to: str) -> dict:
    """Aggregate AI credit transactions for a company over a date range."""
    from app.database.ai_credit_repository import list_company_credit_transactions_by_range

    transactions = list_company_credit_transactions_by_range(company_id, date_from, date_to)

    result = {
        "included_granted_micro_myr": 0,
        "topup_purchased_micro_myr": 0,
        "usage_spent_micro_myr": 0,
        "expired_micro_myr": 0,
        "reversed_micro_myr": 0,
        "net_change_micro_myr": 0,
        "included_granted_myr": 0.0,
        "topup_purchased_myr": 0.0,
        "usage_spent_myr": 0.0,
        "expired_myr": 0.0,
        "reversed_myr": 0.0,
        "net_change_myr": 0.0,
    }

    for txn in transactions:
        txn_type = (txn.get("transaction_type") or "").strip().lower()
        inc_delta = int(txn.get("included_delta_micro_myr", 0) or 0)
        topup_delta = int(txn.get("topup_delta_micro_myr", 0) or 0)

        if txn_type == "included_grant" or txn_type == "subscription_included":
            result["included_granted_micro_myr"] += inc_delta
            result["net_change_micro_myr"] += inc_delta
        elif txn_type == "topup_purchase":
            result["topup_purchased_micro_myr"] += topup_delta
            result["net_change_micro_myr"] += topup_delta
        elif txn_type == "usage_debit":
            spent = abs(inc_delta) + abs(topup_delta)
            result["usage_spent_micro_myr"] += spent
            result["net_change_micro_myr"] -= spent
        elif txn_type == "included_expiry" or txn_type == "expiry":
            expired = abs(inc_delta)
            result["expired_micro_myr"] += expired
            result["net_change_micro_myr"] -= expired
        elif txn_type == "reversal":
            result["reversed_micro_myr"] += abs(inc_delta) + abs(topup_delta)
            result["net_change_micro_myr"] += abs(inc_delta) + abs(topup_delta)
        elif txn_type == "adjustment":
            result["net_change_micro_myr"] += inc_delta + topup_delta

    result["included_granted_myr"] = _micro_myr_to_myr(result["included_granted_micro_myr"])
    result["topup_purchased_myr"] = _micro_myr_to_myr(result["topup_purchased_micro_myr"])
    result["usage_spent_myr"] = _micro_myr_to_myr(result["usage_spent_micro_myr"])
    result["expired_myr"] = _micro_myr_to_myr(result["expired_micro_myr"])
    result["reversed_myr"] = _micro_myr_to_myr(result["reversed_micro_myr"])
    result["net_change_myr"] = _micro_myr_to_myr(result["net_change_micro_myr"])

    return result


# ---------------------------------------------------------------------------
# AI usage summary
# ---------------------------------------------------------------------------

def _summarize_ai_usage(company_id: int, date_from: str, date_to: str) -> dict:
    """Aggregate AI usage logs for a company over a date range."""
    from app.database.billing_usage_repository import sum_company_ai_usage_tokens

    # Try to parse date range into datetime objects
    start_dt = _parse_date(date_from)
    end_dt = _parse_date(date_to)

    if not start_dt or not end_dt:
        return {
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "customer_charge_micro_myr": 0,
            "provider_cost_micro_usd": 0,
            "customer_charge_myr": 0.0,
            "provider_cost_myr": 0.0,
        }

    tokens = sum_company_ai_usage_tokens(
        company_id,
        start_dt.isoformat(),
        end_dt.isoformat(),
    )

    # Get customer charges from credit transactions linked to usage in this period
    from app.database.ai_credit_repository import list_company_credit_transactions_by_range
    txns = list_company_credit_transactions_by_range(company_id, date_from, date_to)

    total_charge = 0
    total_cost = 0
    request_count = 0

    for txn in txns:
        if (txn.get("transaction_type") or "").strip().lower() == "usage_debit":
            total_charge += int(txn.get("customer_charge_micro_myr", 0) or 0)
            total_cost += int(txn.get("provider_cost_micro_usd", 0) or 0)
            if txn.get("ai_usage_log_id"):
                request_count += 1

    # Also count usage logs directly for the period
    # Use the token data already fetched
    prompt = tokens.get("prompt_tokens", 0) or 0
    completion = tokens.get("completion_tokens", 0) or 0
    total_tok = tokens.get("total_tokens", 0) or 0

    return {
        "requests": tokens.get("request_count", 0) or 0,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total_tok,
        "customer_charge_micro_myr": total_charge,
        "provider_cost_micro_usd": total_cost,
        "customer_charge_myr": _micro_myr_to_myr(total_charge),
        "provider_cost_myr": round(total_cost / 1_000_000, 6) if total_cost else 0.0,
    }


# ---------------------------------------------------------------------------
# Main report generation
# ---------------------------------------------------------------------------

def get_company_billing_report(
    company_id: int,
    date_from: str,
    date_to: str,
) -> dict:
    """Generate a comprehensive billing report for a company over a date range.

    Args:
        company_id: Company to report on.
        date_from: ISO date string (YYYY-MM-DD), inclusive start.
        date_to: ISO date string (YYYY-MM-DD), exclusive end.

    Returns:
        Structured report dictionary with subscription, AI credit, and AI usage sections.
    """
    subscription = _summarize_subscription_orders(company_id, date_from, date_to)
    ai_credit = _summarize_ai_credit(company_id, date_from, date_to)
    ai_usage = _summarize_ai_usage(company_id, date_from, date_to)

    return {
        "period": {
            "from": date_from,
            "to": date_to,
        },
        "subscription": subscription,
        "ai_credit": ai_credit,
        "ai_usage": ai_usage,
    }


def get_company_monthly_trend(
    company_id: int,
    months: int = 6,
) -> list[dict]:
    """Generate monthly trend data for a company.

    Args:
        company_id: Company to report on.
        months: Number of past months to include (max 12).

    Returns:
        List of monthly trend entries, ascending, with zero-fill for inactive months.
    """
    safe_months = max(1, min(months, 12))
    now = _now_utc()
    result = []

    for i in range(safe_months - 1, -1, -1):
        month_start = _first_of_month(now) - timedelta(days=30 * i)
        month_start = _first_of_month(month_start)
        month_end = _first_of_month(month_start + timedelta(days=35))

        month_key = month_start.strftime("%Y-%m")
        date_from = month_start.strftime("%Y-%m-%d")
        date_to = month_end.strftime("%Y-%m-%d")

        report = get_company_billing_report(company_id, date_from, date_to)

        entry = {
            "month": month_key,
            "subscription_payments_myr": report["subscription"]["gross_paid_myr"],
            "payment_count": report["subscription"]["payments_completed"],
            "included_credit_granted_myr": report["ai_credit"]["included_granted_myr"],
            "topup_credit_added_myr": report["ai_credit"]["topup_purchased_myr"],
            "credit_spent_myr": report["ai_credit"]["usage_spent_myr"],
            "credit_expired_myr": report["ai_credit"]["expired_myr"],
            "reversals_myr": report["ai_credit"]["reversed_myr"],
            "AI_requests": report["ai_usage"]["requests"],
            "prompt_tokens": report["ai_usage"]["prompt_tokens"],
            "completion_tokens": report["ai_usage"]["completion_tokens"],
            "total_tokens": report["ai_usage"]["total_tokens"],
            "customer_charge_myr": report["ai_usage"]["customer_charge_myr"],
            "provider_cost_myr": report["ai_usage"]["provider_cost_myr"],
        }
        result.append(entry)

    return result


def get_company_plan_usage_report(company_id: int) -> dict:
    """Return current plan usage against plan limits.

    Reuses existing billing_service.get_company_usage logic.
    """
    from app.services.billing_service import get_company_usage

    usage = get_company_usage(company_id)
    if not usage:
        return {
            "status": "no_subscription",
            "data": None,
        }

    u = usage.get("usage", {})
    plan = usage.get("plan", {})
    period = usage.get("period", {})

    def _pct(used, limit):
        """Calculate percentage, avoiding division by zero and handling unlimited."""
        if limit is None:
            return None  # unlimited
        if limit == 0:
            return 0.0
        return round(used / limit * 100, 1)

    chatbots = u.get("chatbots", {})
    members = u.get("team_members", {})
    channels = u.get("channels", {})
    files = u.get("knowledge_files", {})
    storage = u.get("knowledge_storage_bytes", {})
    tokens = u.get("ai_tokens", {})

    result = {
        "subscription_status": plan.get("status", "unknown"),
        "plan": {
            "name": plan.get("name"),
            "code": plan.get("code"),
        },
        "period": {
            "start": period.get("start"),
            "end": period.get("end"),
        },
        "chatbots": {
            "used": chatbots.get("used", 0),
            "limit": chatbots.get("limit"),
            "percentage": _pct(chatbots.get("used", 0), chatbots.get("limit")),
        },
        "team_members": {
            "used": members.get("used", 0),
            "limit": members.get("limit"),
            "percentage": _pct(members.get("used", 0), members.get("limit")),
        },
        "channels": {
            "used": channels.get("used", 0),
            "limit": channels.get("limit"),
            "percentage": _pct(channels.get("used", 0), channels.get("limit")),
        },
        "knowledge_files": {
            "used": files.get("used", 0),
            "limit": files.get("limit"),
            "percentage": _pct(files.get("used", 0), files.get("limit")),
        },
        "knowledge_storage_bytes": {
            "used": storage.get("used", 0),
            "limit": storage.get("limit"),
            "percentage": _pct(storage.get("used", 0), storage.get("limit")),
        },
        "ai_tokens": {
            "input_tokens": tokens.get("input_tokens", 0),
            "output_tokens": tokens.get("output_tokens", 0),
            "total_tokens": tokens.get("total_tokens", 0),
        },
    }

    return {
        "status": "active",
        "data": result,
    }
