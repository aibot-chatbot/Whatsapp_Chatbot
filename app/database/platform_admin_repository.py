"""Supabase access for platform-admin authorization and audit events."""

import json
from datetime import datetime

from app.database.db import supabase


PLATFORM_ADMIN_FIELDS = (
    "id,user_id,is_active,created_at,updated_at,created_by_user_id"
)
PROHIBITED_KEY_FRAGMENTS = {
    "authorization", "cookie", "token", "secret", "password", "credential",
    "api_key", "service_role", "signature", "payload", "prompt", "message",
}
MAX_AUDIT_METADATA_BYTES = 8192
COMPANY_LIST_SORT_FIELDS = {"created_at", "company_name", "status", "id"}
COMPANY_LIST_SORT_ORDERS = {"asc", "desc"}
COMPANY_STATUS_FILTERS = {None, "active", "inactive"}
AUDIT_OUTCOMES = {"success", "not_found"}
PLATFORM_ADMIN_ENDPOINTS = {
    "identity": "/api/platform-admin/me",
    "company_list": "/api/platform-admin/companies",
    "company_detail": "/api/platform-admin/companies/<company_id>",
    "company_subscription": "/api/platform-admin/companies/<company_id>/subscription",
    "company_ai_credit_usage": "/api/platform-admin/companies/<company_id>/ai-credit-usage",
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
    _exact_string(metadata["http_method"], "http_method", "GET")

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

    if action == "platform_admin.company.ai_credit_usage.read":
        if metadata["outcome"] == "not_found":
            if "period_start" in metadata or "period_end" in metadata:
                raise ValueError("Period metadata is not allowed for not_found events")
            return
        _validate_ai_credit_usage_period_pair(metadata)


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
