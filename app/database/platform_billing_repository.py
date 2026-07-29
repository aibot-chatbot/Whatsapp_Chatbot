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
OVERVIEW_STATUSES = ("trialing", "active", "past_due", "expired", "cancelled")
ATTENTION_STATUSES = {"past_due", "expired"}
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
