"""Supabase access for platform-admin authorization and audit events."""

import json

from app.database.db import supabase


PLATFORM_ADMIN_FIELDS = (
    "id,user_id,is_active,created_at,updated_at,created_by_user_id"
)
ALLOWED_AUDIT_ACTIONS = {
    "platform_admin.identity.read",
    "platform_admin.company.list",
    "platform_admin.company.read",
    "platform_admin.company.subscription.read",
    "platform_admin.company.ai_credit_usage.read",
}
ALLOWED_RESOURCE_TYPES = {
    "platform_admin",
    "company",
    "company_subscription",
    "company_ai_credit_usage",
}
ALLOWED_METADATA_KEYS = {
    "outcome", "endpoint", "http_method", "limit", "offset", "sort_by",
    "sort_order", "search_applied", "status_filter", "returned_count",
    "period_start", "period_end",
}
PROHIBITED_KEY_FRAGMENTS = {
    "authorization", "cookie", "token", "secret", "password", "credential",
    "api_key", "service_role", "signature", "payload", "prompt", "message",
}
MAX_AUDIT_METADATA_BYTES = 8192


def _positive_integer(value, field_name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


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


def validate_audit_event(
    platform_admin_user_id, action, resource_type, resource_id, metadata
):
    _positive_integer(platform_admin_user_id, "platform_admin_user_id")
    if not isinstance(action, str) or not action.strip() or action not in ALLOWED_AUDIT_ACTIONS:
        raise ValueError("Unsupported audit action")
    if (
        not isinstance(resource_type, str)
        or not resource_type.strip()
        or resource_type not in ALLOWED_RESOURCE_TYPES
    ):
        raise ValueError("Unsupported audit resource type")
    if resource_id is not None:
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise ValueError("resource_id must be a non-blank string or null")
        if len(resource_id) > 255:
            raise ValueError("resource_id is too long")
    if not isinstance(metadata, dict):
        raise ValueError("Audit metadata must be a JSON object")
    unknown_keys = set(metadata) - ALLOWED_METADATA_KEYS
    if unknown_keys:
        raise ValueError("Audit metadata contains unsupported keys")
    _validate_metadata_keys(metadata)
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
