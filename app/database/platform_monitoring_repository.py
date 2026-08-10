"""Read-only aggregate helpers for platform-admin operations monitoring."""

from datetime import datetime

from app.database.db import supabase


SUPPORT_CASE_STATUSES = ("open", "in_progress", "waiting_for_tenant", "resolved", "closed")
OPEN_SUPPORT_CASE_STATUSES = ("open", "in_progress", "waiting_for_tenant")
SUPPORT_CASE_PRIORITIES = ("low", "normal", "high", "urgent")
TENANT_SUPPORT_REQUEST_STATUSES = ("new", "reviewed", "converted", "closed")
UNRESOLVED_TENANT_REQUEST_STATUSES = ("new", "reviewed")
MESSAGE_DELIVERY_STATUSES = (
    "received", "sent", "pending", "sending", "failed", "retrying", "permanent_failed"
)
CHANNEL_CONNECTION_STATUSES = ("connected", "disconnected", "pending", "error")
BROADCAST_CAMPAIGN_STATUSES = ("draft", "sending", "completed", "failed")
BROADCAST_RECIPIENT_STATUSES = ("pending", "sending", "sent", "failed")
BILLING_ORDER_STATUSES = ("pending", "created", "paid", "credited", "failed", "expired", "cancelled")
BILLING_PENDING_STATUSES = ("pending", "created")
BILLING_FAILED_STATUSES = ("failed",)
BILLING_ACTIVATION_STATUSES = (
    "not_started", "claimed", "activated", "credit_pending", "completed", "conflict", "failed"
)
AI_REQUEST_STATUSES = ("completed", "failed")
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
AUDIT_ACTIVITY_WINDOW_DAYS = 7
AI_USAGE_WINDOW_DAYS = 7


def get_monitoring_overview_for_platform_admin():
    try:
        response = supabase.rpc("get_platform_admin_monitoring_overview").execute()
    except Exception as exc:
        raise RuntimeError("Platform monitoring aggregate lookup failed") from exc
    return _validate_monitoring_overview(_rpc_payload(response))


def _rpc_payload(response):
    data = getattr(response, "data", None)
    if isinstance(data, list):
        if len(data) != 1:
            raise RuntimeError("Malformed monitoring RPC result")
        data = data[0]
    if not isinstance(data, dict):
        raise RuntimeError("Malformed monitoring RPC result")
    return data


def _validate_monitoring_overview(value):
    if not isinstance(value, dict):
        raise RuntimeError("Malformed monitoring RPC result")
    expected = {
        "active_user_count", "support", "messaging", "billing_attention",
        "ai_usage", "platform_admin_activity",
    }
    if set(value) != expected:
        raise RuntimeError("Malformed monitoring RPC result")

    support = _dict(value["support"], "support")
    cases_by_status = _count_map(
        support.get("cases_by_status"),
        SUPPORT_CASE_STATUSES,
        "support.cases_by_status",
    )
    tenant_requests_by_status = _count_map(
        support.get("tenant_requests_by_status"),
        TENANT_SUPPORT_REQUEST_STATUSES,
        "support.tenant_requests_by_status",
    )

    billing = _dict(value["billing_attention"], "billing_attention")
    orders_by_status = _count_map(
        billing.get("orders_by_status"),
        BILLING_ORDER_STATUSES,
        "billing_attention.orders_by_status",
    )

    return {
        "active_user_count": _count(value["active_user_count"], "active_user_count"),
        "support": {
            "cases_by_status": cases_by_status,
            "cases_by_priority": _count_map(
                support.get("cases_by_priority"),
                SUPPORT_CASE_PRIORITIES,
                "support.cases_by_priority",
            ),
            "open_case_count": sum(
                cases_by_status[status] for status in OPEN_SUPPORT_CASE_STATUSES
            ),
            "tenant_requests_by_status": tenant_requests_by_status,
            "unresolved_tenant_request_count": sum(
                tenant_requests_by_status[status]
                for status in UNRESOLVED_TENANT_REQUEST_STATUSES
            ),
        },
        "messaging": _validate_messaging(value["messaging"]),
        "billing_attention": {
            "orders_by_status": orders_by_status,
            "pending_order_count": sum(
                orders_by_status[status] for status in BILLING_PENDING_STATUSES
            ),
            "failed_order_count": sum(
                orders_by_status[status] for status in BILLING_FAILED_STATUSES
            ),
            "reconciliation_required_count": _count(
                billing.get("reconciliation_required_count"),
                "billing_attention.reconciliation_required_count",
            ),
            "activation_statuses": _count_map(
                billing.get("activation_statuses"),
                BILLING_ACTIVATION_STATUSES,
                "billing_attention.activation_statuses",
            ),
            "activation_status_unset_count": _count(
                billing.get("activation_status_unset_count"),
                "billing_attention.activation_status_unset_count",
            ),
        },
        "ai_usage": _validate_ai_usage(value["ai_usage"]),
        "platform_admin_activity": _validate_activity(value["platform_admin_activity"]),
    }


def _validate_messaging(value):
    messaging = _dict(value, "messaging")
    channel_health = _dict(messaging.get("channel_health"), "messaging.channel_health")
    if set(channel_health) != {"telegram", "wasender", "meta_whatsapp"}:
        raise RuntimeError("Malformed monitoring channel health")
    return {
        "messages_by_delivery_status": _count_map(
            messaging.get("messages_by_delivery_status"),
            MESSAGE_DELIVERY_STATUSES,
            "messaging.messages_by_delivery_status",
        ),
        "retry_backlog_count": _count(
            messaging.get("retry_backlog_count"),
            "messaging.retry_backlog_count",
        ),
        "channel_health": {
            provider: _channel_health(channel_health[provider], provider)
            for provider in ("telegram", "wasender", "meta_whatsapp")
        },
        "broadcast_campaigns_by_status": _count_map(
            messaging.get("broadcast_campaigns_by_status"),
            BROADCAST_CAMPAIGN_STATUSES,
            "messaging.broadcast_campaigns_by_status",
        ),
        "broadcast_recipients_by_status": _count_map(
            messaging.get("broadcast_recipients_by_status"),
            BROADCAST_RECIPIENT_STATUSES,
            "messaging.broadcast_recipients_by_status",
        ),
    }


def _channel_health(value, provider):
    row = _dict(value, f"channel_health.{provider}")
    return {
        "total": _count(row.get("total"), f"channel_health.{provider}.total"),
        "active": _count(row.get("active"), f"channel_health.{provider}.active"),
        "inactive": _count(row.get("inactive"), f"channel_health.{provider}.inactive"),
        "attention_required": _count(
            row.get("attention_required"),
            f"channel_health.{provider}.attention_required",
        ),
        "by_connection_status": _count_map(
            row.get("by_connection_status"),
            CHANNEL_CONNECTION_STATUSES,
            f"channel_health.{provider}.by_connection_status",
        ),
    }


def _validate_ai_usage(value):
    ai_usage = _dict(value, "ai_usage")
    return {
        "window": _window(ai_usage.get("window"), AI_USAGE_WINDOW_DAYS, "ai_usage.window"),
        "requests_by_status": _count_map(
            ai_usage.get("requests_by_status"),
            AI_REQUEST_STATUSES,
            "ai_usage.requests_by_status",
        ),
        "recent_request_count": _count(
            ai_usage.get("recent_request_count"), "ai_usage.recent_request_count"
        ),
        "recent_total_tokens": _count(
            ai_usage.get("recent_total_tokens"), "ai_usage.recent_total_tokens"
        ),
        "credit_transactions_by_type": _count_map(
            ai_usage.get("credit_transactions_by_type"),
            AI_CREDIT_TRANSACTION_TYPES,
            "ai_usage.credit_transactions_by_type",
        ),
        "depleted_balance_company_count": _count(
            ai_usage.get("depleted_balance_company_count"),
            "ai_usage.depleted_balance_company_count",
        ),
    }


def _validate_activity(value):
    activity = _dict(value, "platform_admin_activity")
    return {
        "window": _window(
            activity.get("window"),
            AUDIT_ACTIVITY_WINDOW_DAYS,
            "platform_admin_activity.window",
        ),
        "recent_event_count": _count(
            activity.get("recent_event_count"),
            "platform_admin_activity.recent_event_count",
        ),
        "events_by_action": _count_map(
            activity.get("events_by_action"),
            tuple(sorted(_approved_audit_actions())),
            "platform_admin_activity.events_by_action",
        ),
        "events_by_resource_type": _count_map(
            activity.get("events_by_resource_type"),
            tuple(sorted(_approved_audit_resource_types())),
            "platform_admin_activity.events_by_resource_type",
        ),
    }


def _dict(value, field_name):
    if not isinstance(value, dict):
        raise RuntimeError(f"Malformed monitoring section: {field_name}")
    return value


def _count(value, field_name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(f"Malformed monitoring count: {field_name}")
    return value


def _count_map(value, allowed_values, field_name):
    source = _dict(value, field_name)
    allowed = set(allowed_values)
    if set(source) - allowed:
        raise RuntimeError(f"Unsupported monitoring aggregate value: {field_name}")
    return {
        key: _count(source.get(key, 0), f"{field_name}.{key}")
        for key in allowed_values
    }


def _window(value, days, field_name):
    source = _dict(value, field_name)
    if set(source) != {"days", "since"}:
        raise RuntimeError(f"Malformed monitoring window: {field_name}")
    if source["days"] != days:
        raise RuntimeError(f"Malformed monitoring window: {field_name}")
    since = source["since"]
    if not isinstance(since, str) or not since.strip():
        raise RuntimeError(f"Malformed monitoring window: {field_name}")
    datetime.fromisoformat(since.replace("Z", "+00:00"))
    return {"days": days, "since": since}


def _approved_audit_actions():
    from app.database.platform_admin_repository import AUDIT_EVENT_SCHEMAS

    return AUDIT_EVENT_SCHEMAS.keys()


def _approved_audit_resource_types():
    from app.database.platform_admin_repository import ALLOWED_RESOURCE_TYPES

    return ALLOWED_RESOURCE_TYPES
