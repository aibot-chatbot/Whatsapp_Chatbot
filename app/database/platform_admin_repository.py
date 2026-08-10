"""Supabase access for platform-admin authorization and audit events."""

import json
from datetime import datetime

from app.database.db import supabase


PLATFORM_ADMIN_FIELDS = (
    "id,user_id,is_active,created_at,updated_at,created_by_user_id"
)
AUDIT_EVENT_FIELDS = (
    "id,platform_admin_user_id,action,resource_type,resource_id,metadata,created_at"
)
PROHIBITED_KEY_FRAGMENTS = {
    "authorization", "cookie", "token", "secret", "password", "credential",
    "api_key", "service_role", "signature", "payload", "prompt", "message",
}
MAX_AUDIT_METADATA_BYTES = 8192
COMPANY_LIST_SORT_FIELDS = {"created_at", "company_name", "status", "id"}
COMPANY_LIST_SORT_ORDERS = {"asc", "desc"}
COMPANY_STATUS_FILTERS = {None, "active", "inactive"}
COMPANY_USER_LIST_SORT_FIELDS = {"created_at", "email", "full_name", "id"}
COMPANY_CHATBOT_LIST_SORT_FIELDS = {"created_at", "updated_at", "bot_name", "id"}
COMPANY_CHATBOT_STATE_FILTERS = {"current", "archived", "all"}
SUBSCRIPTION_HISTORY_STATUS_FILTERS = {None, "trialing", "active", "past_due", "expired", "cancelled"}
AI_CREDIT_TRANSACTION_TYPE_FILTERS = {
    None,
    "included_credit_grant",
    "trial_credit_grant",
    "usage_debit",
    "topup_purchase",
    "refund",
    "manual_adjustment",
    "expiry",
    "reversal",
}
TENANT_SUPPORT_REQUEST_STATUSES = {"new", "reviewed", "converted", "closed"}
SUPPORT_CASE_STATUSES = {"open", "in_progress", "waiting_for_tenant", "resolved", "closed"}
SUPPORT_CASE_PRIORITIES = {"low", "normal", "high", "urgent"}
AUDIT_OUTCOMES = {"success", "not_found"}
PLATFORM_ADMIN_ENDPOINTS = {
    "identity": "/api/platform-admin/me",
    "operations_overview": "/api/platform-admin/overview",
    "company_list": "/api/platform-admin/companies",
    "company_detail": "/api/platform-admin/companies/<company_id>",
    "company_subscription": "/api/platform-admin/companies/<company_id>/subscription",
    "company_ai_credit_usage": "/api/platform-admin/companies/<company_id>/ai-credit-usage",
    "company_users": "/api/platform-admin/companies/<company_id>/users",
    "company_chatbots": "/api/platform-admin/companies/<company_id>/chatbots",
    "company_subscription_history": "/api/platform-admin/companies/<company_id>/subscription-history",
    "company_ai_credit_transactions": "/api/platform-admin/companies/<company_id>/ai-credit-transactions",
    "company_billing_orders": "/api/platform-admin/companies/<company_id>/billing-orders",
    "company_suspend": "/api/platform-admin/companies/<company_id>/suspend",
    "company_restore": "/api/platform-admin/companies/<company_id>/restore",
    "audit_events": "/api/platform-admin/audit-events",
    "support_case_list": "/api/platform-admin/support-cases",
    "support_case_create": "/api/platform-admin/support-cases",
    "support_case_read": "/api/platform-admin/support-cases/<case_id>",
    "support_case_assignee_list": "/api/platform-admin/support-case-assignees",
    "support_case_note_create": "/api/platform-admin/support-cases/<case_id>/notes",
    "support_case_assign": "/api/platform-admin/support-cases/<case_id>/assignment",
    "support_case_status_update": "/api/platform-admin/support-cases/<case_id>/status",
    "support_case_priority_update": "/api/platform-admin/support-cases/<case_id>/priority",
    "support_case_reply_list": "/api/platform-admin/support-cases/<case_id>/replies",
    "support_case_reply_create": "/api/platform-admin/support-cases/<case_id>/replies",
    "tenant_support_request_list": "/api/platform-admin/tenant-support-requests",
    "tenant_support_request_read": "/api/platform-admin/tenant-support-requests/<request_id>",
    "platform_admin_user_list": "/api/platform-admin/platform-admin-users",
    "platform_admin_user_read": "/api/platform-admin/platform-admin-users/<platform_admin_user_id>",
    "platform_admin_user_create": "/api/platform-admin/platform-admin-users",
    "platform_admin_user_active": "/api/platform-admin/platform-admin-users/<platform_admin_user_id>/active",
}


def _resource_id_none(value):
    if value is not None:
        raise ValueError("resource_id must be null for this audit action")


def _resource_id_positive_integer_string(value):
    if value is None:
        raise ValueError("resource_id is required for this audit action")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("resource_id must be a non-blank string")
    if len(value) > 255:
        raise ValueError("resource_id is too long")
    if not value.isdecimal() or int(value) <= 0:
        raise ValueError("resource_id must be a positive integer string")


AUDIT_EVENT_SCHEMAS = {
    "platform_admin.identity.read": {
        "resource_type": "platform_admin",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {"outcome", "endpoint", "http_method"},
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["identity"],
    },
    "platform_admin.operations.overview.read": {
        "resource_type": "platform_operations_overview",
        "resource_id": _resource_id_none,
        "required_metadata": {
            "outcome", "endpoint", "http_method", "attention_company_count",
            "generated_at",
        },
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["operations_overview"],
    },
    "platform_admin.company.list": {
        "resource_type": "company",
        "resource_id": _resource_id_none,
        "required_metadata": {
            "outcome", "endpoint", "http_method", "limit", "offset",
            "sort_by", "sort_order", "search_applied", "status_filter",
            "returned_count",
        },
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["company_list"],
    },
    "platform_admin.company.read": {
        "resource_type": "company",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {"outcome", "endpoint", "http_method"},
        "optional_metadata": set(),
        "outcomes": AUDIT_OUTCOMES,
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["company_detail"],
    },
    "platform_admin.company.subscription.read": {
        "resource_type": "company_subscription",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {"outcome", "endpoint", "http_method"},
        "optional_metadata": set(),
        "outcomes": AUDIT_OUTCOMES,
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["company_subscription"],
    },
    "platform_admin.company.ai_credit_usage.read": {
        "resource_type": "company_ai_credit_usage",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {"outcome", "endpoint", "http_method"},
        "optional_metadata": {"period_start", "period_end"},
        "outcomes": AUDIT_OUTCOMES,
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["company_ai_credit_usage"],
        "required_metadata_by_outcome": {
            "success": {"period_start", "period_end"},
            "not_found": set(),
        },
    },
    "platform_admin.company.users.read": {
        "resource_type": "company_users",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {"outcome", "endpoint", "http_method"},
        "optional_metadata": {
            "limit", "offset", "sort_by", "sort_order", "search_applied",
            "returned_count",
        },
        "outcomes": AUDIT_OUTCOMES,
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["company_users"],
        "required_metadata_by_outcome": {
            "success": {"limit", "offset", "sort_by", "sort_order", "search_applied", "returned_count"},
            "not_found": set(),
        },
    },
    "platform_admin.company.chatbots.read": {
        "resource_type": "company_chatbots",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {"outcome", "endpoint", "http_method"},
        "optional_metadata": {
            "limit", "offset", "sort_by", "sort_order", "search_applied",
            "state_filter", "returned_count",
        },
        "outcomes": AUDIT_OUTCOMES,
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["company_chatbots"],
        "required_metadata_by_outcome": {
            "success": {
                "limit", "offset", "sort_by", "sort_order", "search_applied",
                "state_filter", "returned_count",
            },
            "not_found": set(),
        },
    },
    "platform_admin.company.subscription_history.read": {
        "resource_type": "company_subscription_history",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {"outcome", "endpoint", "http_method"},
        "optional_metadata": {
            "limit", "offset", "status_filter", "returned_count",
        },
        "outcomes": AUDIT_OUTCOMES,
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["company_subscription_history"],
        "required_metadata_by_outcome": {
            "success": {"limit", "offset", "status_filter", "returned_count"},
            "not_found": set(),
        },
    },
    "platform_admin.company.ai_credit_transactions.read": {
        "resource_type": "company_ai_credit_transactions",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {"outcome", "endpoint", "http_method"},
        "optional_metadata": {
            "limit", "offset", "transaction_type_filter", "returned_count",
        },
        "outcomes": AUDIT_OUTCOMES,
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["company_ai_credit_transactions"],
        "required_metadata_by_outcome": {
            "success": {"limit", "offset", "transaction_type_filter", "returned_count"},
            "not_found": set(),
        },
    },
    "platform_admin.company.billing_orders.read": {
        "resource_type": "company_billing_orders",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {"outcome", "endpoint", "http_method"},
        "optional_metadata": {
            "limit", "offset", "status_filter_applied",
            "created_after_filter_applied", "created_before_filter_applied",
            "returned_count",
        },
        "outcomes": AUDIT_OUTCOMES,
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["company_billing_orders"],
        "required_metadata_by_outcome": {
            "success": {
                "limit", "offset", "status_filter_applied",
                "created_after_filter_applied", "created_before_filter_applied",
                "returned_count",
            },
            "not_found": set(),
        },
    },
    "platform_admin.company.suspend": {
        "resource_type": "company",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {
            "outcome", "endpoint", "http_method", "company_id",
            "old_status", "new_status",
        },
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["company_suspend"],
        "http_methods": {"POST"},
    },
    "platform_admin.company.restore": {
        "resource_type": "company",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {
            "outcome", "endpoint", "http_method", "company_id",
            "old_status", "new_status",
        },
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["company_restore"],
        "http_methods": {"POST"},
    },
    "platform_admin.audit_events.list": {
        "resource_type": "platform_admin_audit_events",
        "resource_id": _resource_id_none,
        "required_metadata": {
            "outcome", "endpoint", "http_method", "limit", "offset",
            "action_filter_applied", "resource_type_filter_applied",
            "actor_user_id_filter_applied", "resource_id_filter_applied",
            "created_after_filter_applied", "created_before_filter_applied",
            "returned_count",
        },
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["audit_events"],
    },
    "platform_admin.support_case.list": {
        "resource_type": "platform_support_cases",
        "resource_id": _resource_id_none,
        "required_metadata": {
            "outcome", "endpoint", "http_method", "limit", "offset",
            "company_filter_applied", "status_filter_applied",
            "priority_filter_applied", "returned_count",
        },
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["support_case_list"],
    },
    "platform_admin.support_case.read": {
        "resource_type": "platform_support_cases",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {"outcome", "endpoint", "http_method"},
        "optional_metadata": set(),
        "outcomes": AUDIT_OUTCOMES,
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["support_case_read"],
    },
    "platform_admin.support_case.create": {
        "resource_type": "platform_support_cases",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {"outcome", "endpoint", "http_method", "company_id"},
        "optional_metadata": {"status", "priority"},
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["support_case_create"],
        "http_methods": {"POST"},
    },
    "platform_admin.support_case.note.create": {
        "resource_type": "platform_support_case_events",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {"outcome", "endpoint", "http_method"},
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["support_case_note_create"],
        "http_methods": {"POST"},
    },
    "platform_admin.support_case.assignee.list": {
        "resource_type": "platform_admin_users",
        "resource_id": _resource_id_none,
        "required_metadata": {"outcome", "endpoint", "http_method", "returned_count"},
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["support_case_assignee_list"],
        "http_methods": {"GET"},
    },
    "platform_admin.support_case.assign": {
        "resource_type": "platform_support_cases",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {
            "outcome", "endpoint", "http_method",
            "old_assigned_platform_admin_user_id",
            "new_assigned_platform_admin_user_id",
        },
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["support_case_assign"],
        "http_methods": {"PATCH"},
    },
    "platform_admin.support_case.unassign": {
        "resource_type": "platform_support_cases",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {
            "outcome", "endpoint", "http_method",
            "old_assigned_platform_admin_user_id",
            "new_assigned_platform_admin_user_id",
        },
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["support_case_assign"],
        "http_methods": {"PATCH"},
    },
    "platform_admin.support_case.status.update": {
        "resource_type": "platform_support_cases",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {"outcome", "endpoint", "http_method", "old_status", "new_status"},
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["support_case_status_update"],
        "http_methods": {"PATCH"},
    },
    "platform_admin.support_case.priority.update": {
        "resource_type": "platform_support_cases",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {"outcome", "endpoint", "http_method", "old_priority", "new_priority"},
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["support_case_priority_update"],
        "http_methods": {"PATCH"},
    },
    "platform_admin.support_case.reply.list": {
        "resource_type": "platform_support_cases",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {"outcome", "endpoint", "http_method", "returned_count"},
        "optional_metadata": {"request_id", "company_id"},
        "outcomes": AUDIT_OUTCOMES,
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["support_case_reply_list"],
        "http_methods": {"GET"},
    },
    "platform_admin.support_case.reply.create": {
        "resource_type": "tenant_support_replies",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {
            "outcome", "endpoint", "http_method", "case_id", "request_id",
            "company_id", "reply_id", "notification_channel", "delivery_status",
        },
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["support_case_reply_create"],
        "http_methods": {"POST"},
    },
    "platform_admin.tenant_support_request.list": {
        "resource_type": "tenant_support_requests",
        "resource_id": _resource_id_none,
        "required_metadata": {
            "outcome", "endpoint", "http_method", "limit", "offset",
            "returned_count", "company_filter_applied", "category_filter_applied",
            "status_filter_applied",
        },
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["tenant_support_request_list"],
    },
    "platform_admin.tenant_support_request.read": {
        "resource_type": "tenant_support_requests",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {"outcome", "endpoint", "http_method"},
        "optional_metadata": set(),
        "outcomes": AUDIT_OUTCOMES,
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["tenant_support_request_read"],
    },
    "platform_admin.tenant_support_request.review": {
        "resource_type": "tenant_support_requests",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {
            "outcome", "endpoint", "http_method", "old_status", "new_status",
        },
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["tenant_support_request_read"],
        "http_methods": {"PATCH"},
    },
    "platform_admin.tenant_support_request.close": {
        "resource_type": "tenant_support_requests",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {
            "outcome", "endpoint", "http_method", "old_status", "new_status",
        },
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["tenant_support_request_read"],
        "http_methods": {"PATCH"},
    },
    "platform_admin.tenant_support_request.convert": {
        "resource_type": "tenant_support_requests",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {
            "outcome", "endpoint", "http_method", "old_status", "new_status",
            "converted_platform_support_case_id",
        },
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": "/api/platform-admin/tenant-support-requests/<request_id>/convert",
        "http_methods": {"POST"},
    },
    "platform_admin.user.list": {
        "resource_type": "platform_admin_users",
        "resource_id": _resource_id_none,
        "required_metadata": {"outcome", "endpoint", "http_method", "returned_count"},
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["platform_admin_user_list"],
        "http_methods": {"GET"},
    },
    "platform_admin.user.read": {
        "resource_type": "platform_admin_users",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {"outcome", "endpoint", "http_method", "target_platform_admin_user_id"},
        "optional_metadata": {"target_user_id", "old_is_active", "new_is_active"},
        "outcomes": AUDIT_OUTCOMES,
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["platform_admin_user_read"],
        "http_methods": {"GET"},
    },
    "platform_admin.user.create": {
        "resource_type": "platform_admin_users",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {
            "outcome", "endpoint", "http_method", "target_platform_admin_user_id",
            "target_user_id", "old_is_active", "new_is_active",
        },
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["platform_admin_user_create"],
        "http_methods": {"POST"},
    },
    "platform_admin.user.activate": {
        "resource_type": "platform_admin_users",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {
            "outcome", "endpoint", "http_method", "target_platform_admin_user_id",
            "target_user_id", "old_is_active", "new_is_active",
        },
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["platform_admin_user_active"],
        "http_methods": {"PATCH"},
    },
    "platform_admin.user.deactivate": {
        "resource_type": "platform_admin_users",
        "resource_id": _resource_id_positive_integer_string,
        "required_metadata": {
            "outcome", "endpoint", "http_method", "target_platform_admin_user_id",
            "target_user_id", "old_is_active", "new_is_active",
        },
        "optional_metadata": set(),
        "outcomes": {"success"},
        "endpoint": PLATFORM_ADMIN_ENDPOINTS["platform_admin_user_active"],
        "http_methods": {"PATCH"},
    },
}
ALLOWED_AUDIT_ACTIONS = frozenset(AUDIT_EVENT_SCHEMAS)
ALLOWED_RESOURCE_TYPES = frozenset(
    schema["resource_type"] for schema in AUDIT_EVENT_SCHEMAS.values()
)
ALLOWED_METADATA_KEYS = frozenset().union(
    *(
        schema["required_metadata"] | schema["optional_metadata"]
        for schema in AUDIT_EVENT_SCHEMAS.values()
    )
)


def _positive_integer(value, field_name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _non_negative_integer(value, field_name, *, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field_name} is too large")


def _bounded_integer(value, field_name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{field_name} is outside the allowed range")


def _exact_string(value, field_name, expected):
    if value != expected:
        raise ValueError(f"{field_name} has an unsupported value")


def _member(value, field_name, allowed):
    try:
        is_allowed = value in allowed
    except TypeError:
        is_allowed = False
    if not is_allowed:
        raise ValueError(f"{field_name} has an unsupported value")


def _boolean(value, field_name):
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")


def _parse_timezone_aware_iso_datetime(value, field_name):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be an ISO-8601 datetime string or null")
    if len(value) > 64:
        raise ValueError(f"{field_name} is too long")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return parsed


def _validate_ai_credit_usage_period_pair(metadata):
    period_start = metadata["period_start"]
    period_end = metadata["period_end"]
    if period_start is None and period_end is None:
        return
    if period_start is None or period_end is None:
        raise ValueError("period_start and period_end must both be null or both be datetimes")
    parsed_start = _parse_timezone_aware_iso_datetime(period_start, "period_start")
    parsed_end = _parse_timezone_aware_iso_datetime(period_end, "period_end")
    if parsed_start >= parsed_end:
        raise ValueError("period_start must be earlier than period_end")


def _validate_metadata_keys(value):
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if not isinstance(key, str):
                raise ValueError("Audit metadata keys must be strings")
            normalized = key.casefold()
            if any(fragment in normalized for fragment in PROHIBITED_KEY_FRAGMENTS):
                raise ValueError("Audit metadata contains a prohibited key")
            _validate_metadata_keys(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            _validate_metadata_keys(nested_value)


def _validate_metadata_schema(action, schema, metadata):
    metadata_keys = set(metadata)
    required_keys = set(schema["required_metadata"])
    required_keys.update(
        schema.get("required_metadata_by_outcome", {}).get(
            metadata.get("outcome"), set()
        )
    )
    allowed_keys = schema["required_metadata"] | schema["optional_metadata"]
    missing_keys = required_keys - metadata_keys
    if missing_keys:
        raise ValueError("Audit metadata is missing required keys")
    unknown_keys = metadata_keys - allowed_keys
    if unknown_keys:
        raise ValueError("Audit metadata contains unsupported keys")

    _member(metadata["outcome"], "outcome", schema["outcomes"])
    _exact_string(metadata["endpoint"], "endpoint", schema["endpoint"])
    _member(metadata["http_method"], "http_method", schema.get("http_methods", {"GET"}))

    if action == "platform_admin.company.list":
        _bounded_integer(metadata["limit"], "limit", 1, 100)
        _non_negative_integer(metadata["offset"], "offset")
        _member(metadata["sort_by"], "sort_by", COMPANY_LIST_SORT_FIELDS)
        _member(metadata["sort_order"], "sort_order", COMPANY_LIST_SORT_ORDERS)
        _boolean(metadata["search_applied"], "search_applied")
        _member(metadata["status_filter"], "status_filter", COMPANY_STATUS_FILTERS)
        _non_negative_integer(metadata["returned_count"], "returned_count", maximum=100)
        if metadata["returned_count"] > metadata["limit"]:
            raise ValueError("returned_count cannot exceed limit")

    if action == "platform_admin.operations.overview.read":
        _non_negative_integer(metadata["attention_company_count"], "attention_company_count", maximum=10)
        _parse_timezone_aware_iso_datetime(metadata["generated_at"], "generated_at")

    if action == "platform_admin.company.ai_credit_usage.read":
        if metadata["outcome"] == "not_found":
            if "period_start" in metadata or "period_end" in metadata:
                raise ValueError("Period metadata is not allowed for not_found events")
            return
        _validate_ai_credit_usage_period_pair(metadata)

    if action == "platform_admin.company.users.read":
        if metadata["outcome"] == "not_found":
            list_keys = {"limit", "offset", "sort_by", "sort_order", "search_applied", "returned_count"}
            if any(key in metadata for key in list_keys):
                raise ValueError("List metadata is not allowed for not_found events")
            return
        _bounded_integer(metadata["limit"], "limit", 1, 100)
        _non_negative_integer(metadata["offset"], "offset")
        _member(metadata["sort_by"], "sort_by", COMPANY_USER_LIST_SORT_FIELDS)
        _member(metadata["sort_order"], "sort_order", COMPANY_LIST_SORT_ORDERS)
        _boolean(metadata["search_applied"], "search_applied")
        _non_negative_integer(metadata["returned_count"], "returned_count", maximum=100)
        if metadata["returned_count"] > metadata["limit"]:
            raise ValueError("returned_count cannot exceed limit")

    if action == "platform_admin.company.chatbots.read":
        if metadata["outcome"] == "not_found":
            list_keys = {
                "limit", "offset", "sort_by", "sort_order", "search_applied",
                "state_filter", "returned_count",
            }
            if any(key in metadata for key in list_keys):
                raise ValueError("List metadata is not allowed for not_found events")
            return
        _bounded_integer(metadata["limit"], "limit", 1, 100)
        _non_negative_integer(metadata["offset"], "offset")
        _member(metadata["sort_by"], "sort_by", COMPANY_CHATBOT_LIST_SORT_FIELDS)
        _member(metadata["sort_order"], "sort_order", COMPANY_LIST_SORT_ORDERS)
        _boolean(metadata["search_applied"], "search_applied")
        _member(metadata["state_filter"], "state_filter", COMPANY_CHATBOT_STATE_FILTERS)
        _non_negative_integer(metadata["returned_count"], "returned_count", maximum=100)
        if metadata["returned_count"] > metadata["limit"]:
            raise ValueError("returned_count cannot exceed limit")

    if action == "platform_admin.company.subscription_history.read":
        if metadata["outcome"] == "not_found":
            list_keys = {"limit", "offset", "status_filter", "returned_count"}
            if any(key in metadata for key in list_keys):
                raise ValueError("List metadata is not allowed for not_found events")
            return
        _bounded_integer(metadata["limit"], "limit", 1, 100)
        _non_negative_integer(metadata["offset"], "offset")
        _member(metadata["status_filter"], "status_filter", SUBSCRIPTION_HISTORY_STATUS_FILTERS)
        _non_negative_integer(metadata["returned_count"], "returned_count", maximum=100)
        if metadata["returned_count"] > metadata["limit"]:
            raise ValueError("returned_count cannot exceed limit")

    if action == "platform_admin.company.ai_credit_transactions.read":
        if metadata["outcome"] == "not_found":
            list_keys = {"limit", "offset", "transaction_type_filter", "returned_count"}
            if any(key in metadata for key in list_keys):
                raise ValueError("List metadata is not allowed for not_found events")
            return
        _bounded_integer(metadata["limit"], "limit", 1, 100)
        _non_negative_integer(metadata["offset"], "offset")
        _member(
            metadata["transaction_type_filter"],
            "transaction_type_filter",
            AI_CREDIT_TRANSACTION_TYPE_FILTERS,
        )
        _non_negative_integer(metadata["returned_count"], "returned_count", maximum=100)
        if metadata["returned_count"] > metadata["limit"]:
            raise ValueError("returned_count cannot exceed limit")

    if action == "platform_admin.company.billing_orders.read":
        if metadata["outcome"] == "not_found":
            list_keys = {
                "limit", "offset", "status_filter_applied",
                "created_after_filter_applied", "created_before_filter_applied",
                "returned_count",
            }
            if any(key in metadata for key in list_keys):
                raise ValueError("List metadata is not allowed for not_found events")
            return
        _bounded_integer(metadata["limit"], "limit", 1, 100)
        _non_negative_integer(metadata["offset"], "offset")
        for key in (
            "status_filter_applied",
            "created_after_filter_applied",
            "created_before_filter_applied",
        ):
            _boolean(metadata[key], key)
        _non_negative_integer(metadata["returned_count"], "returned_count", maximum=100)
        if metadata["returned_count"] > metadata["limit"]:
            raise ValueError("returned_count cannot exceed limit")

    if action in {"platform_admin.company.suspend", "platform_admin.company.restore"}:
        _positive_integer(metadata["company_id"], "company_id")
        if action.endswith(".suspend"):
            _exact_string(metadata["old_status"], "old_status", "active")
            _exact_string(metadata["new_status"], "new_status", "inactive")
        else:
            _exact_string(metadata["old_status"], "old_status", "inactive")
            _exact_string(metadata["new_status"], "new_status", "active")

    if action == "platform_admin.audit_events.list":
        _bounded_integer(metadata["limit"], "limit", 1, 100)
        _non_negative_integer(metadata["offset"], "offset")
        for key in (
            "action_filter_applied", "resource_type_filter_applied",
            "actor_user_id_filter_applied", "resource_id_filter_applied",
            "created_after_filter_applied", "created_before_filter_applied",
        ):
            _boolean(metadata[key], key)
        _non_negative_integer(metadata["returned_count"], "returned_count", maximum=100)
        if metadata["returned_count"] > metadata["limit"]:
            raise ValueError("returned_count cannot exceed limit")

    if action == "platform_admin.support_case.list":
        _bounded_integer(metadata["limit"], "limit", 1, 100)
        _non_negative_integer(metadata["offset"], "offset")
        for key in (
            "company_filter_applied", "status_filter_applied",
            "priority_filter_applied",
        ):
            _boolean(metadata[key], key)
        _non_negative_integer(metadata["returned_count"], "returned_count", maximum=100)
        if metadata["returned_count"] > metadata["limit"]:
            raise ValueError("returned_count cannot exceed limit")

    if action == "platform_admin.support_case.assignee.list":
        _non_negative_integer(metadata["returned_count"], "returned_count", maximum=1000)

    if action == "platform_admin.support_case.create":
        if "company_id" in metadata:
            _positive_integer(metadata["company_id"], "company_id")
        for key in ("status", "priority"):
            if key in metadata and not isinstance(metadata[key], str):
                raise ValueError(f"{key} must be text")

    if action in {"platform_admin.support_case.assign", "platform_admin.support_case.unassign"}:
        old_assignee = metadata["old_assigned_platform_admin_user_id"]
        new_assignee = metadata["new_assigned_platform_admin_user_id"]
        if old_assignee is not None:
            _positive_integer(old_assignee, "old_assigned_platform_admin_user_id")
        if new_assignee is not None:
            _positive_integer(new_assignee, "new_assigned_platform_admin_user_id")
        if action.endswith(".assign") and new_assignee is None:
            raise ValueError("assign audit must include a new assignee")
        if action.endswith(".unassign") and new_assignee is not None:
            raise ValueError("unassign audit must clear the assignee")

    if action == "platform_admin.support_case.status.update":
        if metadata["old_status"] not in SUPPORT_CASE_STATUSES:
            raise ValueError("old_status must be a valid support-case status")
        if metadata["new_status"] not in SUPPORT_CASE_STATUSES:
            raise ValueError("new_status must be a valid support-case status")

    if action == "platform_admin.support_case.priority.update":
        if metadata["old_priority"] not in SUPPORT_CASE_PRIORITIES:
            raise ValueError("old_priority must be a valid support-case priority")
        if metadata["new_priority"] not in SUPPORT_CASE_PRIORITIES:
            raise ValueError("new_priority must be a valid support-case priority")

    if action == "platform_admin.support_case.reply.list":
        _non_negative_integer(metadata["returned_count"], "returned_count", maximum=1000)
        if "company_id" in metadata:
            _positive_integer(metadata["company_id"], "company_id")
        if "request_id" in metadata:
            _positive_integer(metadata["request_id"], "request_id")

    if action == "platform_admin.support_case.reply.create":
        for key in ("case_id", "request_id", "company_id", "reply_id"):
            _positive_integer(metadata[key], key)
        _exact_string(metadata["notification_channel"], "notification_channel", "in_app")
        _member(metadata["delivery_status"], "delivery_status", {"pending"})

    if action in {
        "platform_admin.tenant_support_request.review",
        "platform_admin.tenant_support_request.close",
        "platform_admin.tenant_support_request.convert",
    }:
        for key in ("old_status", "new_status"):
            if metadata[key] not in TENANT_SUPPORT_REQUEST_STATUSES:
                raise ValueError(f"{key} must be a valid tenant support request status")
        if action.endswith(".review") and metadata["new_status"] != "reviewed":
            raise ValueError("review audit must have reviewed new_status")
        if action.endswith(".close") and metadata["new_status"] != "closed":
            raise ValueError("close audit must have closed new_status")
        if action.endswith(".convert"):
            if metadata["new_status"] != "converted":
                raise ValueError("convert audit must have converted new_status")
            _positive_integer(
                metadata["converted_platform_support_case_id"],
                "converted_platform_support_case_id",
            )

    if action in {
        "platform_admin.user.list",
        "platform_admin.user.read",
        "platform_admin.user.create",
        "platform_admin.user.activate",
        "platform_admin.user.deactivate",
    }:
        if "returned_count" in metadata:
            _non_negative_integer(metadata["returned_count"], "returned_count", maximum=1000)
        if "target_platform_admin_user_id" in metadata:
            _positive_integer(metadata["target_platform_admin_user_id"], "target_platform_admin_user_id")
        if "target_user_id" in metadata:
            _positive_integer(metadata["target_user_id"], "target_user_id")
        for key in ("old_is_active", "new_is_active"):
            if key in metadata and metadata[key] is not None:
                _boolean(metadata[key], key)


def validate_audit_event(
    platform_admin_user_id, action, resource_type, resource_id, metadata
):
    _positive_integer(platform_admin_user_id, "platform_admin_user_id")
    if not isinstance(action, str) or not action.strip() or action not in AUDIT_EVENT_SCHEMAS:
        raise ValueError("Unsupported audit action")
    schema = AUDIT_EVENT_SCHEMAS[action]
    if (
        not isinstance(resource_type, str)
        or not resource_type.strip()
        or resource_type != schema["resource_type"]
    ):
        raise ValueError("Unsupported audit resource type")
    schema["resource_id"](resource_id)
    if not isinstance(metadata, dict):
        raise ValueError("Audit metadata must be a JSON object")
    _validate_metadata_keys(metadata)
    _validate_metadata_schema(action, schema, metadata)
    try:
        canonical = json.dumps(
            metadata, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Audit metadata must be JSON serializable") from exc
    if len(canonical.encode("utf-8")) > MAX_AUDIT_METADATA_BYTES:
        raise ValueError("Audit metadata exceeds the 8192-byte limit")


def get_active_platform_admin_by_user_id(user_id):
    _positive_integer(user_id, "user_id")
    response = (
        supabase.table("platform_admin_users")
        .select(PLATFORM_ADMIN_FIELDS)
        .eq("user_id", user_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


PLATFORM_ADMIN_USER_SAFE_FIELDS = (
    "id,user_id,is_active,created_at,updated_at,created_by_user_id"
)
PLATFORM_ADMIN_USER_IDENTITY_FIELDS = "id,email,full_name,status"


def _safe_positive_id(value, field_name):
    _positive_integer(value, field_name)
    return value


def _load_users_by_ids(user_ids):
    ids = sorted({value for value in user_ids if isinstance(value, int) and not isinstance(value, bool) and value > 0})
    if not ids:
        return {}
    response = (
        supabase.table("users")
        .select(PLATFORM_ADMIN_USER_IDENTITY_FIELDS)
        .in_("id", ids)
        .execute()
    )
    return {
        row.get("id"): row
        for row in (response.data or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }


def _recent_activity_for_mapping(mapping_id):
    response = (
        supabase.table("platform_admin_audit_events")
        .select("created_at")
        .eq("platform_admin_user_id", mapping_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0].get("created_at") if rows else None


def _project_platform_admin_user(row, users_by_id):
    user = users_by_id.get(row.get("user_id")) or {}
    creator = users_by_id.get(row.get("created_by_user_id")) or {}
    return {
        "platform_admin_user_id": row.get("id"),
        "user_id": row.get("user_id"),
        "is_active": row.get("is_active"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "created_by_user_id": row.get("created_by_user_id"),
        "user_email": user.get("email"),
        "user_full_name": user.get("full_name"),
        "user_status": user.get("status"),
        "creator_user_id": row.get("created_by_user_id"),
        "creator_email": creator.get("email"),
        "creator_full_name": creator.get("full_name"),
        "recent_platform_admin_activity_at": _recent_activity_for_mapping(row.get("id")),
    }


def list_platform_admin_users_for_platform_admin(*, limit, offset, is_active=None):
    _bounded_integer(limit, "limit", 1, 100)
    _non_negative_integer(offset, "offset")
    if is_active is not None and not isinstance(is_active, bool):
        raise ValueError("is_active must be boolean or null")
    query = supabase.table("platform_admin_users").select(
        PLATFORM_ADMIN_USER_SAFE_FIELDS, count="exact"
    )
    if is_active is not None:
        query = query.eq("is_active", is_active)
    response = (
        query
        .order("created_at", desc=True)
        .order("id", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = response.data or []
    users_by_id = _load_users_by_ids(
        [row.get("user_id") for row in rows] + [row.get("created_by_user_id") for row in rows]
    )
    return [_project_platform_admin_user(row, users_by_id) for row in rows], int(response.count or 0)


def get_platform_admin_user_for_platform_admin(mapping_id):
    _safe_positive_id(mapping_id, "platform_admin_user_id")
    response = (
        supabase.table("platform_admin_users")
        .select(PLATFORM_ADMIN_USER_SAFE_FIELDS)
        .eq("id", mapping_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        return None
    row = rows[0]
    users_by_id = _load_users_by_ids([row.get("user_id"), row.get("created_by_user_id")])
    return _project_platform_admin_user(row, users_by_id)


def _is_positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _validate_mapping_rpc_result(result, *, actor_user_id, target_user_id):
    if not isinstance(result, dict):
        raise RuntimeError("Malformed platform-admin create RPC result")
    mapping = result.get("platform_admin_user")
    audit = result.get("audit_event")
    if not isinstance(mapping, dict) or not isinstance(audit, dict):
        raise RuntimeError("Malformed platform-admin create RPC result")
    mapping_id = mapping.get("id")
    if not _is_positive_int(mapping_id):
        raise RuntimeError("Malformed platform-admin create RPC result")
    if mapping.get("user_id") != target_user_id:
        raise RuntimeError("Platform-admin create RPC user mismatch")
    if mapping.get("is_active") is not True:
        raise RuntimeError("Platform-admin create RPC active state mismatch")
    if mapping.get("created_by_user_id") != actor_user_id:
        raise RuntimeError("Platform-admin create RPC creator mismatch")
    if not _is_positive_int(audit.get("id")):
        raise RuntimeError("Malformed platform-admin create audit result")
    if audit.get("action") != "platform_admin.user.create":
        raise RuntimeError("Platform-admin create audit action mismatch")
    if audit.get("resource_type") != "platform_admin_users":
        raise RuntimeError("Platform-admin create audit resource mismatch")
    if audit.get("resource_id") != str(mapping_id):
        raise RuntimeError("Platform-admin create audit resource mismatch")
    return {"platform_admin_user": mapping, "audit_event": audit}


def create_platform_admin_user_mapping_for_platform_admin(actor_mapping_id, actor_user_id, target_user_id):
    _safe_positive_id(actor_mapping_id, "actor_platform_admin_user_id")
    _safe_positive_id(actor_user_id, "actor_user_id")
    _safe_positive_id(target_user_id, "target_user_id")
    response = supabase.rpc(
        "create_platform_admin_user_mapping",
        {
            "p_actor_platform_admin_user_id": actor_mapping_id,
            "p_target_user_id": target_user_id,
        },
    ).execute()
    return _validate_mapping_rpc_result(response.data, actor_user_id=actor_user_id, target_user_id=target_user_id)


def _validate_active_rpc_result(result, *, target_mapping_id, is_active):
    if not isinstance(result, dict):
        raise RuntimeError("Malformed platform-admin active RPC result")
    mapping = result.get("platform_admin_user")
    audit = result.get("audit_event")
    if not isinstance(mapping, dict) or not isinstance(audit, dict):
        raise RuntimeError("Malformed platform-admin active RPC result")
    if mapping.get("id") != target_mapping_id:
        raise RuntimeError("Platform-admin active RPC mapping mismatch")
    if not _is_positive_int(mapping.get("user_id")):
        raise RuntimeError("Platform-admin active RPC user mismatch")
    if mapping.get("is_active") is not is_active:
        raise RuntimeError("Platform-admin active RPC state mismatch")
    expected_action = "platform_admin.user.activate" if is_active else "platform_admin.user.deactivate"
    if not _is_positive_int(audit.get("id")):
        raise RuntimeError("Malformed platform-admin active audit result")
    if audit.get("action") != expected_action:
        raise RuntimeError("Platform-admin active audit action mismatch")
    if audit.get("resource_type") != "platform_admin_users":
        raise RuntimeError("Platform-admin active audit resource mismatch")
    if audit.get("resource_id") != str(target_mapping_id):
        raise RuntimeError("Platform-admin active audit resource mismatch")
    return {"platform_admin_user": mapping, "audit_event": audit}


def set_platform_admin_user_active_for_platform_admin(actor_mapping_id, target_mapping_id, is_active):
    _safe_positive_id(actor_mapping_id, "actor_platform_admin_user_id")
    _safe_positive_id(target_mapping_id, "target_platform_admin_user_id")
    if not isinstance(is_active, bool):
        raise ValueError("is_active must be boolean")
    response = supabase.rpc(
        "set_platform_admin_user_active",
        {
            "p_actor_platform_admin_user_id": actor_mapping_id,
            "p_target_platform_admin_user_id": target_mapping_id,
            "p_is_active": is_active,
        },
    ).execute()
    return _validate_active_rpc_result(response.data, target_mapping_id=target_mapping_id, is_active=is_active)


def list_platform_admin_audit_events_for_platform_admin(
    *, limit, offset, action=None, resource_type=None, actor_user_id=None,
    resource_id=None, created_after=None, created_before=None
):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if action is not None and action not in AUDIT_EVENT_SCHEMAS:
        raise ValueError("Unsupported audit action")
    if resource_type is not None and resource_type not in ALLOWED_RESOURCE_TYPES:
        raise ValueError("Unsupported audit resource type")
    if actor_user_id is not None:
        _positive_integer(actor_user_id, "actor_user_id")
    if resource_id is not None and (
        not isinstance(resource_id, str) or not resource_id.strip() or len(resource_id) > 255
    ):
        raise ValueError("resource_id must be a non-blank string no longer than 255 characters")

    actor_mapping_ids = None
    if actor_user_id is not None:
        mapping_response = (
            supabase.table("platform_admin_users")
            .select("id")
            .eq("user_id", actor_user_id)
            .execute()
        )
        actor_mapping_ids = [
            row.get("id") for row in (mapping_response.data or [])
            if isinstance(row.get("id"), int) and not isinstance(row.get("id"), bool)
        ]
        if not actor_mapping_ids:
            return [], 0

    query = supabase.table("platform_admin_audit_events").select(
        AUDIT_EVENT_FIELDS, count="exact"
    )
    if action is not None:
        query = query.eq("action", action)
    if resource_type is not None:
        query = query.eq("resource_type", resource_type)
    if actor_mapping_ids is not None:
        query = query.in_("platform_admin_user_id", actor_mapping_ids)
    if resource_id is not None:
        query = query.eq("resource_id", resource_id)
    if created_after is not None:
        query = query.gte("created_at", created_after.isoformat())
    if created_before is not None:
        query = query.lt("created_at", created_before.isoformat())

    response = (
        query
        .order("created_at", desc=True)
        .order("id", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return response.data or [], int(response.count or 0)


def insert_platform_admin_audit_event(
    platform_admin_user_id, action, resource_type, resource_id, metadata
):
    validate_audit_event(
        platform_admin_user_id, action, resource_type, resource_id, metadata
    )
    payload = {
        "platform_admin_user_id": platform_admin_user_id,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "metadata": metadata,
    }
    response = (
        supabase.table("platform_admin_audit_events")
        .insert(payload)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise RuntimeError("Audit insert returned no row")
    return rows[0]
