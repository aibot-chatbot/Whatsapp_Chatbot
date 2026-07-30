"""Safe billing and AI-credit reads for authorized platform admins."""

from app.database.db import supabase


SUBSCRIPTION_FIELDS = (
    "id,company_id,plan_id,status,starts_at,current_period_start,current_period_end,"
    "trial_ends_at,cancelled_at,ends_at,pending_plan_id,plan_change_effective_at,"
    "cancellation_scheduled_at,cancellation_effective_at,status_updated_at,created_at,updated_at"
)
PLAN_FIELDS = "id,code,name,billing_interval,currency,price,included_ai_credit_micro_myr"
BALANCE_FIELDS = (
    "company_id,subscription_id,period_start,period_end,included_balance_micro_myr,"
    "topup_balance_micro_myr,created_at,updated_at"
)
OVERVIEW_SUBSCRIPTION_FIELDS = (
    "id,company_id,plan_id,status,status_updated_at,current_period_end,created_at"
)
OVERVIEW_PLAN_FIELDS = "id,code,name"
SUBSCRIPTION_HISTORY_FIELDS = (
    "id,plan_id,pending_plan_id,status,starts_at,current_period_start,current_period_end,"
    "trial_ends_at,cancelled_at,ends_at,plan_change_effective_at,"
    "cancellation_scheduled_at,cancellation_effective_at,status_updated_at,created_at,updated_at"
)
SUBSCRIPTION_HISTORY_PLAN_FIELDS = "id,code,name"
AI_CREDIT_TRANSACTION_HISTORY_FIELDS = (
    "id,transaction_type,included_delta_micro_myr,topup_delta_micro_myr,"
    "included_balance_after_micro_myr,topup_balance_after_micro_myr,"
    "customer_charge_micro_myr,uncovered_charge_micro_myr,period_start,period_end,created_at"
)
OVERVIEW_STATUSES = ("trialing", "active", "past_due", "expired", "cancelled")
ATTENTION_STATUSES = {"past_due", "expired"}
SUBSCRIPTION_HISTORY_STATUSES = set(OVERVIEW_STATUSES)
AI_CREDIT_TRANSACTION_TYPES = {
    "included_credit_grant",
    "trial_credit_grant",
    "usage_debit",
    "topup_purchase",
    "refund",
    "manual_adjustment",
    "expiry",
    "reversal",
}
PLAN_ORDER = {"free": 0, "essential": 1, "advanced": 2, "pro": 3}
SUBSCRIPTION_SCAN_PAGE_SIZE = 1000
SUBSCRIPTION_SCAN_MAX_ROWS = 10000


def _validate_company_id(company_id):
    if isinstance(company_id, bool) or not isinstance(company_id, int) or company_id <= 0:
        raise ValueError("company_id must be a positive integer")


def _period_iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def get_subscription_summary_for_platform_admin(company_id):
    _validate_company_id(company_id)
    response = (
        supabase.table("company_subscriptions")
        .select(SUBSCRIPTION_FIELDS)
        .eq("company_id", company_id)
        .order("created_at", desc=True)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        return None
    subscription = dict(rows[0])
    plan_id = subscription.get("plan_id")
    plan = None
    if plan_id is not None:
        plan_response = (
            supabase.table("subscription_plans")
            .select(PLAN_FIELDS)
            .eq("id", plan_id)
            .limit(1)
            .execute()
        )
        plan_rows = plan_response.data or []
        plan = plan_rows[0] if plan_rows else None
    subscription["plan"] = plan
    return subscription


def get_ai_credit_balance_for_platform_admin(company_id):
    _validate_company_id(company_id)
    response = (
        supabase.table("company_ai_credit_balances")
        .select(BALANCE_FIELDS)
        .eq("company_id", company_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def get_ai_usage_summary_for_platform_admin(company_id, period_start, period_end):
    _validate_company_id(company_id)
    response = (
        supabase.table("ai_usage_logs")
        .select("prompt_tokens,completion_tokens,total_tokens,provider_cost_micro_usd")
        .eq("company_id", company_id)
        .eq("request_status", "completed")
        .gte("created_at", _period_iso(period_start))
        .lt("created_at", _period_iso(period_end))
        .execute()
    )
    result = {
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "provider_cost_micro_usd": 0,
    }
    for row in response.data or []:
        result["request_count"] += 1
        for key in result.keys() - {"request_count"}:
            result[key] += int(row.get(key) or 0)
    return result


def get_ai_credit_charge_summary_for_platform_admin(company_id, period_start, period_end):
    _validate_company_id(company_id)
    response = (
        supabase.table("ai_credit_transactions")
        .select("customer_charge_micro_myr,uncovered_charge_micro_myr,provider_cost_micro_usd")
        .eq("company_id", company_id)
        .gte("created_at", _period_iso(period_start))
        .lt("created_at", _period_iso(period_end))
        .execute()
    )
    result = {
        "transaction_count": 0,
        "customer_charge_micro_myr": 0,
        "uncovered_charge_micro_myr": 0,
        "provider_cost_micro_usd": 0,
    }
    for row in response.data or []:
        result["transaction_count"] += 1
        for key in result.keys() - {"transaction_count"}:
            result[key] += int(row.get(key) or 0)
    return result


def _safe_plan_ref(row):
    if not isinstance(row, dict):
        return None
    return {
        "code": row.get("code"),
        "name": row.get("name"),
    }


def _positive_plan_ids(rows):
    plan_ids = set()
    for row in rows:
        for key in ("plan_id", "pending_plan_id"):
            value = row.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                plan_ids.add(value)
    return sorted(plan_ids)


def _plans_by_id_for_subscription_history(plan_ids):
    if not plan_ids:
        return {}
    response = (
        supabase.table("subscription_plans")
        .select(SUBSCRIPTION_HISTORY_PLAN_FIELDS)
        .in_("id", plan_ids)
        .execute()
    )
    return {
        row["id"]: _safe_plan_ref(row)
        for row in (response.data or [])
        if isinstance(row, dict)
        and isinstance(row.get("id"), int)
        and not isinstance(row.get("id"), bool)
        and row.get("id") > 0
    }


def _safe_subscription_history_row(row, plans_by_id):
    if not isinstance(row, dict):
        row = {}
    plan_id = row.get("plan_id")
    pending_plan_id = row.get("pending_plan_id")
    return {
        "id": row.get("id"),
        "status": row.get("status"),
        "plan": plans_by_id.get(plan_id),
        "pending_plan": plans_by_id.get(pending_plan_id),
        "starts_at": row.get("starts_at"),
        "current_period_start": row.get("current_period_start"),
        "current_period_end": row.get("current_period_end"),
        "trial_ends_at": row.get("trial_ends_at"),
        "cancelled_at": row.get("cancelled_at"),
        "ends_at": row.get("ends_at"),
        "plan_change_effective_at": row.get("plan_change_effective_at"),
        "cancellation_scheduled_at": row.get("cancellation_scheduled_at"),
        "cancellation_effective_at": row.get("cancellation_effective_at"),
        "status_updated_at": row.get("status_updated_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def list_subscription_history_for_platform_admin(company_id, *, limit, offset, status=None):
    """List historical subscription rows for one company, newest first.

    This returns persisted ``company_subscriptions`` rows. It is not an
    event-sourced transition timeline and does not infer missing transitions.
    """
    _validate_company_id(company_id)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if status is not None and status not in SUBSCRIPTION_HISTORY_STATUSES:
        raise ValueError("unsupported subscription status")

    query = (
        supabase.table("company_subscriptions")
        .select(SUBSCRIPTION_HISTORY_FIELDS, count="exact")
        .eq("company_id", company_id)
        .order("created_at", desc=True)
        .order("id", desc=True)
    )
    if status is not None:
        query = query.eq("status", status)
    response = query.range(offset, offset + limit - 1).execute()
    rows = response.data or []
    plans_by_id = _plans_by_id_for_subscription_history(_positive_plan_ids(rows))
    subscriptions = [_safe_subscription_history_row(row, plans_by_id) for row in rows]
    return subscriptions, int(response.count or 0)


def _safe_ai_credit_transaction_row(row):
    if not isinstance(row, dict):
        row = {}
    return {
        "id": row.get("id"),
        "transaction_type": row.get("transaction_type"),
        "included_delta_micro_myr": row.get("included_delta_micro_myr"),
        "topup_delta_micro_myr": row.get("topup_delta_micro_myr"),
        "included_balance_after_micro_myr": row.get("included_balance_after_micro_myr"),
        "topup_balance_after_micro_myr": row.get("topup_balance_after_micro_myr"),
        "customer_charge_micro_myr": row.get("customer_charge_micro_myr"),
        "uncovered_charge_micro_myr": row.get("uncovered_charge_micro_myr"),
        "period_start": row.get("period_start"),
        "period_end": row.get("period_end"),
        "created_at": row.get("created_at"),
    }


def list_ai_credit_transactions_for_platform_admin(
    company_id, *, limit, offset, transaction_type=None
):
    """List safe AI-credit ledger rows for one company, newest first."""
    _validate_company_id(company_id)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if transaction_type is not None and transaction_type not in AI_CREDIT_TRANSACTION_TYPES:
        raise ValueError("unsupported AI-credit transaction type")

    query = (
        supabase.table("ai_credit_transactions")
        .select(AI_CREDIT_TRANSACTION_HISTORY_FIELDS, count="exact")
        .eq("company_id", company_id)
        .order("created_at", desc=True)
        .order("id", desc=True)
    )
    if transaction_type is not None:
        query = query.eq("transaction_type", transaction_type)
    response = query.range(offset, offset + limit - 1).execute()
    transactions = [_safe_ai_credit_transaction_row(row) for row in (response.data or [])]
    return transactions, int(response.count or 0)


def _scan_latest_subscriptions_for_platform_admin():
    latest = {}
    offset = 0
    scanned = 0
    while True:
        response = (
            supabase.table("company_subscriptions")
            .select(OVERVIEW_SUBSCRIPTION_FIELDS)
            .order("created_at", desc=True)
            .order("id", desc=True)
            .range(offset, offset + SUBSCRIPTION_SCAN_PAGE_SIZE - 1)
            .execute()
        )
        rows = response.data or []
        scanned += len(rows)
        if scanned > SUBSCRIPTION_SCAN_MAX_ROWS:
            raise RuntimeError("subscription overview scan exceeded bounded row limit")
        for row in rows:
            company_id = row.get("company_id")
            if (
                isinstance(company_id, int)
                and not isinstance(company_id, bool)
                and company_id > 0
                and company_id not in latest
            ):
                latest[company_id] = row
        if len(rows) < SUBSCRIPTION_SCAN_PAGE_SIZE:
            break
        offset += SUBSCRIPTION_SCAN_PAGE_SIZE
    return latest


def _plans_by_id_for_platform_admin(plan_ids):
    valid_ids = sorted({
        plan_id for plan_id in plan_ids
        if isinstance(plan_id, int) and not isinstance(plan_id, bool) and plan_id > 0
    })
    if not valid_ids:
        return {}
    response = (
        supabase.table("subscription_plans")
        .select(OVERVIEW_PLAN_FIELDS)
        .in_("id", valid_ids)
        .execute()
    )
    return {
        row["id"]: {
            "code": row.get("code"),
            "name": row.get("name"),
        }
        for row in (response.data or [])
        if isinstance(row.get("id"), int)
    }


def _plan_sort_key(item):
    code = str(item.get("code") or "").strip().lower()
    return (PLAN_ORDER.get(code, 99), code)


def get_latest_subscription_overview_for_platform_admin():
    """Aggregate latest subscription rows using created_at DESC, id DESC."""
    latest_by_company = _scan_latest_subscriptions_for_platform_admin()
    plans_by_id = _plans_by_id_for_platform_admin(
        row.get("plan_id") for row in latest_by_company.values()
    )

    by_status = {status: 0 for status in OVERVIEW_STATUSES}
    plan_counts = {}
    attention_rows = []
    for company_id, row in latest_by_company.items():
        status = str(row.get("status") or "").strip().lower()
        if status in by_status:
            by_status[status] += 1

        plan = plans_by_id.get(row.get("plan_id"))
        if plan:
            code = str(plan.get("code") or "").strip().lower()
            name = str(plan.get("name") or "").strip() or code
            if code:
                if code not in plan_counts:
                    plan_counts[code] = {"code": code, "name": name, "count": 0}
                plan_counts[code]["count"] += 1

        if status in ATTENTION_STATUSES:
            attention_rows.append({
                "company_id": company_id,
                "subscription_status": status,
                "plan_code": (plan or {}).get("code"),
                "plan_name": (plan or {}).get("name"),
                "status_updated_at": row.get("status_updated_at"),
                "current_period_end": row.get("current_period_end"),
                "created_at": row.get("created_at"),
                "id": row.get("id"),
            })

    attention_rows.sort(
        key=lambda row: (
            row.get("status_updated_at") or row.get("current_period_end") or row.get("created_at") or "",
            row.get("id") or 0,
        ),
        reverse=True,
    )
    return {
        "by_status": by_status,
        "by_plan": sorted(plan_counts.values(), key=_plan_sort_key),
        "attention_subscriptions": attention_rows[:10],
    }
