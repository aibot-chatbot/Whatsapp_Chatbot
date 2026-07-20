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
