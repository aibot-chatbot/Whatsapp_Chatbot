"""Read-only Phase 7 billing/subscription oversight for platform admins."""

from datetime import datetime

from app.database.db import supabase


SUBSCRIPTION_STATUSES = ("trialing", "active", "past_due", "expired", "cancelled")
SUBSCRIPTION_ORDER_STATUSES = ("pending", "created", "paid", "credited", "failed", "expired", "cancelled")
SUBSCRIPTION_PENDING_ORDER_STATUSES = ("pending", "created")
SUBSCRIPTION_FAILED_ORDER_STATUSES = ("failed",)
ACTIVATION_STATUSES = ("not_started", "claimed", "activated", "credit_pending", "completed", "conflict", "failed")
ACTIVATION_TYPES = ("initial_purchase", "renewal", "upgrade")
TOPUP_ORDER_STATUSES = ("pending", "claimed", "paid", "credited", "failed", "expired", "cancelled")
AI_CREDIT_TRANSACTION_TYPES = (
    "included_credit_grant",
    "trial_credit_grant",
    "usage_debit",
    "topup_purchase",
    "refund",
    "manual_adjustment",
    "expiry",
    "reversal",
)
AI_REQUEST_STATUSES = ("completed", "failed")
NOTIFICATION_SEVERITIES = ("info", "warning", "critical")
AI_USAGE_WINDOW_DAYS = 7

COMPANY_FIELDS = "id,company_name,status"


def get_billing_overview_for_platform_admin():
    try:
        response = supabase.rpc("get_platform_admin_billing_overview").execute()
    except Exception as exc:
        raise RuntimeError("Platform billing overview lookup failed") from exc
    return _validate_overview(_rpc_result(response))


def list_billing_companies_for_platform_admin(
    *, limit, offset, subscription_status=None, plan=None, attention=None
):
    _bounded_int(limit, "limit", 1, 100)
    _bounded_int(offset, "offset", 0, None)
    if subscription_status is not None and subscription_status not in SUBSCRIPTION_STATUSES:
        raise ValueError("unsupported subscription status")
    if plan is not None and (
        not isinstance(plan, str) or not plan.strip() or len(plan.strip()) > 50
    ):
        raise ValueError("unsupported plan")
    plan = plan.strip().lower() if isinstance(plan, str) else None
    if attention is not None and not isinstance(attention, bool):
        raise ValueError("attention must be boolean or null")

    try:
        response = supabase.rpc("get_platform_admin_billing_companies", {
            "p_limit": limit,
            "p_offset": offset,
            "p_subscription_status": subscription_status,
            "p_plan": plan,
            "p_attention": attention,
        }).execute()
    except Exception as exc:
        raise RuntimeError("Platform billing company directory lookup failed") from exc
    result = _validate_directory(_rpc_result(response))
    return result["companies"], result["pagination"]["total"]


def _rpc_result(response):
    data = getattr(response, "data", None)
    if isinstance(data, list):
        if len(data) != 1:
            raise RuntimeError("Malformed billing overview RPC result")
        data = data[0]
    if not isinstance(data, dict):
        raise RuntimeError("Malformed billing overview RPC result")
    return data


def _validate_overview(value):
    expected = {
        "generated_at",
        "subscriptions",
        "subscription_orders",
        "topup_orders",
        "ai_credit",
        "ai_usage",
        "billing_notifications",
        "subscription_lifecycle",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise RuntimeError("Malformed billing overview RPC result")
    generated_at = value["generated_at"]
    if not isinstance(generated_at, str) or not generated_at.strip():
        raise RuntimeError("Malformed billing overview generated_at")
    datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    return {
        "generated_at": generated_at,
        "subscriptions": _validate_subscriptions(value["subscriptions"]),
        "subscription_orders": _validate_subscription_orders(value["subscription_orders"]),
        "topup_orders": _validate_topup_orders(value["topup_orders"]),
        "ai_credit": _validate_ai_credit(value["ai_credit"]),
        "ai_usage": _validate_ai_usage(value["ai_usage"]),
        "billing_notifications": _validate_notifications(value["billing_notifications"]),
        "subscription_lifecycle": _validate_lifecycle(value["subscription_lifecycle"]),
    }


def _validate_subscriptions(value):
    source = _dict(value, "subscriptions")
    if set(source) != {"by_status", "by_plan", "active_plan_catalogue"}:
        raise RuntimeError("Malformed subscriptions overview")
    catalogue = source.get("active_plan_catalogue")
    if not isinstance(catalogue, list):
        raise RuntimeError("Malformed plan catalogue")
    safe_catalogue = []
    for row in catalogue:
        item = _dict(row, "active_plan_catalogue.row")
        if set(item) != {
            "code",
            "name",
            "billing_interval",
            "currency",
            "price_sen",
            "included_ai_credit_micro_myr",
        }:
            raise RuntimeError("Malformed plan catalogue row")
        safe_catalogue.append({
            "code": _text(item.get("code"), "plan.code"),
            "name": _text(item.get("name"), "plan.name"),
            "billing_interval": _nullable_text(item.get("billing_interval"), "plan.billing_interval"),
            "currency": _nullable_text(item.get("currency"), "plan.currency"),
            "price_sen": _nullable_non_negative_int(item.get("price_sen"), "plan.price_sen"),
            "included_ai_credit_micro_myr": _nullable_non_negative_int(
                item.get("included_ai_credit_micro_myr"), "plan.included_ai_credit_micro_myr"
            ),
        })
    return {
        "by_status": _count_map(source.get("by_status"), SUBSCRIPTION_STATUSES, "subscriptions.by_status"),
        "by_plan": _free_count_map(source.get("by_plan"), "subscriptions.by_plan"),
        "active_plan_catalogue": safe_catalogue,
    }


def _validate_subscription_orders(value):
    source = _dict(value, "subscription_orders")
    if set(source) != {
        "orders_by_status",
        "pending_count",
        "failed_count",
        "reconciliation_required_count",
        "activation_statuses",
        "activation_status_unset_count",
        "activation_types",
        "activation_type_unset_count",
    }:
        raise RuntimeError("Malformed subscription orders overview")
    by_status = _count_map(
        source.get("orders_by_status"), SUBSCRIPTION_ORDER_STATUSES, "subscription_orders.orders_by_status"
    )
    return {
        "orders_by_status": by_status,
        "pending_count": _count(source.get("pending_count"), "subscription_orders.pending_count"),
        "failed_count": _count(source.get("failed_count"), "subscription_orders.failed_count"),
        "reconciliation_required_count": _count(
            source.get("reconciliation_required_count"),
            "subscription_orders.reconciliation_required_count",
        ),
        "activation_statuses": _count_map(
            source.get("activation_statuses"),
            ACTIVATION_STATUSES,
            "subscription_orders.activation_statuses",
        ),
        "activation_status_unset_count": _count(
            source.get("activation_status_unset_count"),
            "subscription_orders.activation_status_unset_count",
        ),
        "activation_types": _count_map(
            source.get("activation_types"),
            ACTIVATION_TYPES,
            "subscription_orders.activation_types",
        ),
        "activation_type_unset_count": _count(
            source.get("activation_type_unset_count"),
            "subscription_orders.activation_type_unset_count",
        ),
    }


def _validate_topup_orders(value):
    source = _dict(value, "topup_orders")
    if set(source) != {"orders_by_status", "pending_count", "failed_count", "credited_count"}:
        raise RuntimeError("Malformed top-up orders overview")
    return {
        "orders_by_status": _count_map(source.get("orders_by_status"), TOPUP_ORDER_STATUSES, "topup_orders.orders_by_status"),
        "pending_count": _count(source.get("pending_count"), "topup_orders.pending_count"),
        "failed_count": _count(source.get("failed_count"), "topup_orders.failed_count"),
        "credited_count": _count(source.get("credited_count"), "topup_orders.credited_count"),
    }


def _validate_ai_credit(value):
    source = _dict(value, "ai_credit")
    if set(source) != {
        "balance_row_count",
        "depleted_company_count",
        "total_included_balance_micro_myr",
        "total_topup_balance_micro_myr",
        "transactions_by_type",
    }:
        raise RuntimeError("Malformed AI-credit overview")
    return {
        "balance_row_count": _count(source.get("balance_row_count"), "ai_credit.balance_row_count"),
        "depleted_company_count": _count(source.get("depleted_company_count"), "ai_credit.depleted_company_count"),
        "total_included_balance_micro_myr": _count(
            source.get("total_included_balance_micro_myr"),
            "ai_credit.total_included_balance_micro_myr",
        ),
        "total_topup_balance_micro_myr": _count(
            source.get("total_topup_balance_micro_myr"),
            "ai_credit.total_topup_balance_micro_myr",
        ),
        "transactions_by_type": _count_map(
            source.get("transactions_by_type"),
            AI_CREDIT_TRANSACTION_TYPES,
            "ai_credit.transactions_by_type",
        ),
    }


def _validate_ai_usage(value):
    source = _dict(value, "ai_usage")
    if set(source) != {"window", "requests_by_status", "recent_request_count", "recent_total_tokens"}:
        raise RuntimeError("Malformed AI usage overview")
    return {
        "window": _window(source.get("window"), AI_USAGE_WINDOW_DAYS, "ai_usage.window"),
        "requests_by_status": _count_map(
            source.get("requests_by_status"), AI_REQUEST_STATUSES, "ai_usage.requests_by_status"
        ),
        "recent_request_count": _count(source.get("recent_request_count"), "ai_usage.recent_request_count"),
        "recent_total_tokens": _count(source.get("recent_total_tokens"), "ai_usage.recent_total_tokens"),
    }


def _validate_notifications(value):
    source = _dict(value, "billing_notifications")
    if set(source) != {"by_type_severity_read_state"}:
        raise RuntimeError("Malformed billing notifications overview")
    rows = source.get("by_type_severity_read_state")
    if not isinstance(rows, list):
        raise RuntimeError("Malformed billing notification groups")
    safe_rows = []
    for row in rows:
        item = _dict(row, "billing_notifications.row")
        if set(item) != {"notification_type", "severity", "is_read", "count"}:
            raise RuntimeError("Malformed billing notification row")
        severity = _text(item.get("severity"), "notification.severity")
        if severity not in NOTIFICATION_SEVERITIES:
            raise RuntimeError("Unsupported notification severity")
        if not isinstance(item.get("is_read"), bool):
            raise RuntimeError("Malformed notification read state")
        safe_rows.append({
            "notification_type": _text(item.get("notification_type"), "notification.notification_type"),
            "severity": severity,
            "is_read": item["is_read"],
            "count": _count(item.get("count"), "notification.count"),
        })
    return {"by_type_severity_read_state": safe_rows}


def _validate_lifecycle(value):
    source = _dict(value, "subscription_lifecycle")
    if set(source) != {
        "pending_plan_change_count",
        "scheduled_cancellation_count",
        "pending_plan_and_cancellation_count",
    }:
        raise RuntimeError("Malformed subscription lifecycle overview")
    return {
        "pending_plan_change_count": _count(
            source.get("pending_plan_change_count"),
            "subscription_lifecycle.pending_plan_change_count",
        ),
        "scheduled_cancellation_count": _count(
            source.get("scheduled_cancellation_count"),
            "subscription_lifecycle.scheduled_cancellation_count",
        ),
        "pending_plan_and_cancellation_count": _count(
            source.get("pending_plan_and_cancellation_count"),
            "subscription_lifecycle.pending_plan_and_cancellation_count",
        ),
    }


def _validate_directory(value):
    expected = {"companies", "pagination"}
    if not isinstance(value, dict) or set(value) != expected:
        raise RuntimeError("Malformed billing company directory RPC result")
    pagination = _validate_directory_pagination(value["pagination"])
    rows = value["companies"]
    if not isinstance(rows, list) or len(rows) > pagination["limit"]:
        raise RuntimeError("Malformed billing company directory rows")
    safe_rows = [_validate_directory_row(row) for row in rows]
    return {"companies": safe_rows, "pagination": pagination}


def _validate_directory_pagination(value):
    source = _dict(value, "billing_companies.pagination")
    if set(source) != {"total", "limit", "offset"}:
        raise RuntimeError("Malformed billing company directory pagination")
    limit = _count(source.get("limit"), "billing_companies.pagination.limit")
    if limit < 1 or limit > 100:
        raise RuntimeError("Malformed billing company directory pagination")
    return {
        "total": _count(source.get("total"), "billing_companies.pagination.total"),
        "limit": limit,
        "offset": _count(source.get("offset"), "billing_companies.pagination.offset"),
    }


def _validate_directory_row(value):
    expected = {
        "company_id",
        "company_name",
        "company_status",
        "current_plan",
        "subscription_status",
        "current_period_start",
        "current_period_end",
        "pending_plan_change",
        "cancellation_scheduled",
        "ai_credit_total_balance_micro_myr",
        "subscription_order_attention",
        "topup_order_attention",
    }
    row = _dict(value, "billing_companies.row")
    if set(row) != expected:
        raise RuntimeError("Malformed billing company directory row")
    company_id = row.get("company_id")
    if not _positive_int(company_id):
        raise RuntimeError("Malformed billing company directory company_id")
    company_status = _text(row.get("company_status"), "billing_companies.company_status")
    if company_status not in {"active", "inactive"}:
        raise RuntimeError("Unsupported billing company status")
    subscription_status = _nullable_text(row.get("subscription_status"), "billing_companies.subscription_status")
    if subscription_status is not None and subscription_status not in SUBSCRIPTION_STATUSES:
        raise RuntimeError("Unsupported billing company subscription status")
    if not isinstance(row.get("pending_plan_change"), bool):
        raise RuntimeError("Malformed billing company pending_plan_change")
    if not isinstance(row.get("cancellation_scheduled"), bool):
        raise RuntimeError("Malformed billing company cancellation_scheduled")
    return {
        "company_id": company_id,
        "company_name": _text(row.get("company_name"), "billing_companies.company_name"),
        "company_status": company_status,
        "current_plan": _directory_plan(row.get("current_plan")),
        "subscription_status": subscription_status,
        "current_period_start": _nullable_timestamp(row.get("current_period_start"), "billing_companies.current_period_start"),
        "current_period_end": _nullable_timestamp(row.get("current_period_end"), "billing_companies.current_period_end"),
        "pending_plan_change": row["pending_plan_change"],
        "cancellation_scheduled": row["cancellation_scheduled"],
        "ai_credit_total_balance_micro_myr": _count(
            row.get("ai_credit_total_balance_micro_myr"),
            "billing_companies.ai_credit_total_balance_micro_myr",
        ),
        "subscription_order_attention": _attention_counts(
            row.get("subscription_order_attention"),
            {
                "pending_count",
                "failed_count",
                "reconciliation_required_count",
                "activation_failed_count",
                "activation_conflict_count",
            },
            "billing_companies.subscription_order_attention",
        ),
        "topup_order_attention": _attention_counts(
            row.get("topup_order_attention"),
            {"pending_count", "failed_count", "credited_count"},
            "billing_companies.topup_order_attention",
        ),
    }


def _directory_plan(value):
    if value is None:
        return None
    source = _dict(value, "billing_companies.current_plan")
    if set(source) != {"code", "name"}:
        raise RuntimeError("Malformed billing company plan")
    return {
        "code": _text(source.get("code"), "billing_companies.current_plan.code"),
        "name": _text(source.get("name"), "billing_companies.current_plan.name"),
    }


def _attention_counts(value, expected_keys, field_name):
    source = _dict(value, field_name)
    if set(source) != expected_keys:
        raise RuntimeError(f"Malformed billing company attention counts: {field_name}")
    return {
        key: _count(source.get(key), f"{field_name}.{key}")
        for key in sorted(expected_keys)
    }


def _dict(value, field_name):
    if not isinstance(value, dict):
        raise RuntimeError(f"Malformed billing overview section: {field_name}")
    return value


def _count(value, field_name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(f"Malformed billing overview count: {field_name}")
    return value


def _count_map(value, allowed_values, field_name):
    source = _dict(value, field_name)
    allowed = set(allowed_values)
    if set(source) - allowed:
        raise RuntimeError(f"Unsupported billing overview aggregate value: {field_name}")
    return {key: _count(source.get(key, 0), f"{field_name}.{key}") for key in allowed_values}


def _free_count_map(value, field_name):
    source = _dict(value, field_name)
    result = {}
    for key, count in source.items():
        if not isinstance(key, str) or not key.strip() or len(key) > 50:
            raise RuntimeError(f"Unsupported billing overview aggregate value: {field_name}")
        result[key] = _count(count, f"{field_name}.{key}")
    return result


def _window(value, days, field_name):
    source = _dict(value, field_name)
    if set(source) != {"days", "since"} or source.get("days") != days:
        raise RuntimeError(f"Malformed billing overview window: {field_name}")
    since = source.get("since")
    if not isinstance(since, str) or not since.strip():
        raise RuntimeError(f"Malformed billing overview window: {field_name}")
    datetime.fromisoformat(since.replace("Z", "+00:00"))
    return {"days": days, "since": since}


def _text(value, field_name):
    if not isinstance(value, str) or not value.strip() or len(value) > 100:
        raise RuntimeError(f"Malformed billing overview text: {field_name}")
    return value


def _nullable_text(value, field_name):
    if value is None:
        return None
    return _text(value, field_name)


def _nullable_timestamp(value, field_name):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Malformed billing company timestamp: {field_name}")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"Malformed billing company timestamp: {field_name}") from exc
    return value


def _nullable_non_negative_int(value, field_name):
    if value is None:
        return None
    return _count(value, field_name)


def _safe_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _bounded_int(value, field_name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field_name} is invalid")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field_name} is invalid")
