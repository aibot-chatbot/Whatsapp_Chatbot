"""Application service for the read-only platform-admin API."""

import logging
from datetime import datetime, timezone

from app.database import platform_admin_repository
from app.database import platform_billing_oversight_repository
from app.database import platform_billing_repository
from app.database import platform_chatbot_repository
from app.database import platform_company_repository
from app.database import platform_company_user_repository
from app.database import platform_monitoring_repository
from app.database import platform_support_case_repository
from app.database import tenant_support_repository


logger = logging.getLogger(__name__)


class PlatformAdminServiceError(Exception):
    def __init__(self, status_code, code, message):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _validation(code, message):
    raise PlatformAdminServiceError(400, code, message)


def _data_unavailable():
    raise PlatformAdminServiceError(
        503, "platform_admin_data_unavailable",
        "Platform data is temporarily unavailable.",
    )


def _audit_unavailable():
    raise PlatformAdminServiceError(
        503, "platform_admin_audit_unavailable",
        "Platform audit logging is temporarily unavailable.",
    )


def _positive_id(value, code="invalid_company_id"):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        label = {
            "invalid_case_id": "Case ID",
            "invalid_request_id": "Request ID",
        }.get(code, "Company ID")
        _validation(code, f"{label} must be a positive integer.")
    return value


def _validated_actor_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PlatformAdminServiceError(
            500, "platform_admin_context_invalid", "Platform context is invalid."
        )
    return value


def _rpc_error_text(exc):
    parts = []
    for attr in ("message", "details", "hint", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, str):
            parts.append(value)
    if getattr(exc, "args", None):
        for value in exc.args:
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, dict):
                for key in ("message", "details", "hint", "code"):
                    item = value.get(key)
                    if isinstance(item, str):
                        parts.append(item)
    if not parts:
        parts.append(str(exc))
    return " ".join(parts).casefold()


def _handle_support_case_rpc_error(exc, *, operation):
    text = _rpc_error_text(exc)
    if "support case not found" in text:
        raise PlatformAdminServiceError(
            404, "support_case_not_found", "Support case not found."
        )
    if "unchanged" in text:
        raise PlatformAdminServiceError(
            400, "no_change", "Support case is unchanged."
        )
    if "transition is not allowed" in text:
        _validation("invalid_status", "Support case status transition is not allowed.")
    if "unsupported support case status" in text:
        _validation("invalid_status", "Support case status is not supported.")
    if "unsupported support case priority" in text:
        _validation("invalid_priority", "Support case priority is not supported.")
    if "active platform-admin mapping is required" in text:
        if operation == "assignment":
            _validation(
                "invalid_assignee",
                "Assignee must be an active platform-admin mapping ID or null.",
            )
        raise PlatformAdminServiceError(
            403, "platform_admin_access_denied", "Platform-admin access is denied."
        )
    if "invalid internal note" in text:
        _validation("invalid_redacted_note", "redacted_note is invalid.")
    if "invalid tenant-visible reply" in text:
        _validation("invalid_redacted_body", "redacted_body is invalid.")
    if "converted tenant support request not found" in text:
        raise PlatformAdminServiceError(
            404,
            "tenant_support_request_not_found",
            "Converted tenant support request not found.",
        )
    if "tenant support request and case company mismatch" in text:
        raise PlatformAdminServiceError(
            409,
            "support_case_linkage_invalid",
            "Support case linkage is invalid.",
        )
    logger.error("Platform support-case RPC failed")
    _data_unavailable()


def _integer_parameter(value, *, name, default, minimum, maximum=None):
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        _validation(f"invalid_{name}", f"{name} must be an integer.")
    if isinstance(value, bool) or parsed < minimum or (maximum is not None and parsed > maximum):
        bounds = f"between {minimum} and {maximum}" if maximum is not None else f"at least {minimum}"
        _validation(f"invalid_{name}", f"{name} must be {bounds}.")
    return parsed


def _optional_exact_member_parameter(value, *, name, allowed, code):
    if value is None:
        return None
    if not isinstance(value, str):
        _validation(code, f"{name} is not supported.")
    normalized = value.strip()
    if not normalized or normalized not in allowed:
        _validation(code, f"{name} is not supported.")
    return normalized


def _optional_resource_id_parameter(value):
    if value is None:
        return None
    if not isinstance(value, str):
        _validation("invalid_resource_id", "resource_id must be text.")
    normalized = value.strip()
    if not normalized or len(normalized) > 255:
        _validation("invalid_resource_id", "resource_id must contain 1 to 255 characters.")
    return normalized


def _optional_billing_status_parameter(value):
    if value is None:
        return None
    if not isinstance(value, str):
        _validation("invalid_status", "status must be text.")
    normalized = value.strip()
    if not normalized or len(normalized) > 20:
        _validation("invalid_status", "status must contain 1 to 20 characters.")
    return normalized


def _optional_positive_integer_parameter(value, *, name):
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        _validation(f"invalid_{name}", f"{name} must be a positive integer.")
    if isinstance(value, bool) or parsed <= 0:
        _validation(f"invalid_{name}", f"{name} must be a positive integer.")
    return parsed


def _optional_datetime_parameter(value, *, name):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        _validation(f"invalid_{name}", f"{name} must be a timezone-aware ISO-8601 datetime.")
    if len(value.strip()) > 64:
        _validation(f"invalid_{name}", f"{name} is too long.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        _validation(f"invalid_{name}", f"{name} must be a valid ISO-8601 datetime.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _validation(f"invalid_{name}", f"{name} must include a timezone offset.")
    return parsed


def _audit(actor_id, action, resource_type, resource_id, metadata):
    try:
        platform_admin_repository.insert_platform_admin_audit_event(
            actor_id, action, resource_type, resource_id, metadata
        )
    except Exception:
        logger.error("Platform-admin audit insertion failed")
        _audit_unavailable()


SAFE_AUDIT_METADATA_KEYS = {
    "outcome",
    "endpoint",
    "http_method",
    "limit",
    "offset",
    "sort_by",
    "sort_order",
    "search_applied",
    "status_filter",
    "state_filter",
    "transaction_type_filter",
    "status_filter_applied",
    "returned_count",
    "attention_company_count",
    "generated_at",
    "subscription_status_filter_applied",
    "plan_filter_applied",
    "attention_filter_applied",
    "period_start",
    "period_end",
    "action_filter_applied",
    "resource_type_filter_applied",
    "actor_user_id_filter_applied",
    "resource_id_filter_applied",
    "created_after_filter_applied",
    "created_before_filter_applied",
    "company_filter_applied",
    "priority_filter_applied",
    "company_id",
    "status",
    "priority",
    "old_status",
    "new_status",
    "old_priority",
    "new_priority",
    "old_assigned_platform_admin_user_id",
    "new_assigned_platform_admin_user_id",
    "category_filter_applied",
    "case_id",
    "request_id",
    "reply_id",
    "notification_channel",
    "delivery_status",
    "target_platform_admin_user_id",
    "target_user_id",
    "old_is_active",
    "new_is_active",
}


def _safe_audit_metadata(metadata):
    if not isinstance(metadata, dict):
        return {}
    safe = {}
    for key in SAFE_AUDIT_METADATA_KEYS:
        if key not in metadata:
            continue
        value = metadata.get(key)
        if isinstance(value, (dict, list, tuple, set)):
            continue
        safe[key] = value
    return safe


def _safe_audit_event_response_row(row):
    if not isinstance(row, dict):
        row = {}
    return {
        "id": row.get("id"),
        "actor": {
            "platform_admin_user_id": row.get("platform_admin_user_id"),
        },
        "action": row.get("action"),
        "resource_type": row.get("resource_type"),
        "resource_id": row.get("resource_id"),
        "metadata": _safe_audit_metadata(row.get("metadata")),
        "created_at": row.get("created_at"),
    }


def _now_utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _invalid_platform_admin_user_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _validation(
            "invalid_platform_admin_user_id",
            "Platform-admin mapping ID must be a positive integer.",
        )
    return value


def _invalid_user_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _validation("invalid_user_id", "user_id must be a positive integer.")
    return value


def _strict_body(payload, allowed_keys):
    if not isinstance(payload, dict):
        _validation("invalid_request", "Request body must be a JSON object.")
    unknown = set(payload) - set(allowed_keys)
    if unknown:
        _validation("invalid_request", "Request body contains unsupported fields.")
    return payload


def _empty_body(payload):
    if payload is None:
        return {}
    payload = _strict_body(payload, set())
    return payload


def _handle_platform_admin_user_rpc_error(exc):
    text = _rpc_error_text(exc)
    if "target user not found" in text:
        raise PlatformAdminServiceError(404, "target_user_not_found", "Target user not found.")
    if "target user must be active" in text:
        _validation("target_user_inactive", "Target user must be active.")
    if "target user must belong to a protected company" in text:
        _validation(
            "target_user_not_protected",
            "Target user is not eligible for platform-admin access.",
        )
    if "already exists" in text or "23505" in text:
        _validation("platform_admin_mapping_exists", "Platform-admin mapping already exists.")
    if "platform-admin mapping not found" in text:
        raise PlatformAdminServiceError(
            404, "platform_admin_user_not_found", "Platform-admin mapping not found."
        )
    if "unchanged" in text:
        _validation("no_change", "No change is required.")
    if "self-deactivation is not allowed" in text:
        _validation("self_deactivation_not_allowed", "You cannot deactivate your own mapping.")
    if "at least one active platform-admin mapping is required" in text:
        _validation(
            "final_active_platform_admin",
            "The final active platform admin cannot be deactivated.",
        )
    if "active platform-admin mapping is required" in text:
        raise PlatformAdminServiceError(
            403, "platform_admin_access_denied", "Platform-admin access is denied."
        )
    logger.error("Platform-admin user-management RPC failed")
    _data_unavailable()


def _handle_company_lifecycle_rpc_error(exc):
    text = _rpc_error_text(exc)
    if "company not found" in text:
        raise PlatformAdminServiceError(404, "company_not_found", "Company not found.")
    if "company status is unchanged" in text or "unchanged" in text:
        _validation("no_change", "No change is required.")
    if "protected platform-admin company cannot be suspended" in text:
        _validation(
            "protected_company",
            "Protected platform-admin companies cannot be suspended.",
        )
    if "active platform-admin mapping is required" in text:
        raise PlatformAdminServiceError(
            403, "platform_admin_access_denied", "Platform-admin access is denied."
        )
    if "invalid company id" in text:
        _validation("invalid_company_id", "Company ID must be a positive integer.")
    logger.error("Platform company lifecycle RPC failed")
    _data_unavailable()


def _safe_platform_admin_user(row):
    if not isinstance(row, dict):
        row = {}
    return {
        "platform_admin_user_id": row.get("platform_admin_user_id") or row.get("id"),
        "user_id": row.get("user_id"),
        "is_active": row.get("is_active"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "created_by_user_id": row.get("created_by_user_id"),
        "user_email": row.get("user_email"),
        "user_full_name": row.get("user_full_name"),
        "user_status": row.get("user_status"),
        "creator_user_id": row.get("creator_user_id") or row.get("created_by_user_id"),
        "creator_email": row.get("creator_email"),
        "creator_full_name": row.get("creator_full_name"),
        "recent_platform_admin_activity_at": row.get("recent_platform_admin_activity_at"),
    }


def _safe_rpc_mapping(row):
    if not isinstance(row, dict):
        row = {}
    return {
        "platform_admin_user_id": row.get("id"),
        "user_id": row.get("user_id"),
        "is_active": row.get("is_active"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "created_by_user_id": row.get("created_by_user_id"),
    }


def list_platform_admin_users(actor_id, *, limit=None, offset=None, is_active=None):
    actor_id = _validated_actor_id(actor_id)
    limit = _integer_parameter(limit, name="limit", default=100, minimum=1, maximum=100)
    offset = _integer_parameter(offset, name="offset", default=0, minimum=0)
    active_filter = None
    if is_active is not None:
        if isinstance(is_active, str):
            lowered = is_active.strip().lower()
            if lowered == "true":
                active_filter = True
            elif lowered == "false":
                active_filter = False
            else:
                _validation("invalid_is_active", "is_active must be true or false.")
        else:
            _validation("invalid_is_active", "is_active must be true or false.")
    try:
        users, total = platform_admin_repository.list_platform_admin_users_for_platform_admin(
            limit=limit, offset=offset, is_active=active_filter
        )
    except Exception:
        logger.error("Platform-admin user listing failed")
        _data_unavailable()
    safe_users = [_safe_platform_admin_user(row) for row in users]
    _audit(actor_id, "platform_admin.user.list", "platform_admin_users", None, {
        "outcome": "success",
        "endpoint": platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["platform_admin_user_list"],
        "http_method": "GET",
        "returned_count": len(safe_users),
    })
    return {
        "platform_admin_users": safe_users,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(safe_users),
            "total": total,
            "has_more": offset + len(safe_users) < total,
        },
        "filters": {"is_active": active_filter},
    }


def get_platform_admin_user(mapping_id, actor_id):
    actor_id = _validated_actor_id(actor_id)
    mapping_id = _invalid_platform_admin_user_id(mapping_id)
    endpoint = platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["platform_admin_user_read"]
    try:
        row = platform_admin_repository.get_platform_admin_user_for_platform_admin(mapping_id)
    except ValueError:
        _validation("invalid_platform_admin_user_id", "Platform-admin mapping ID must be a positive integer.")
    except Exception:
        logger.error("Platform-admin user detail lookup failed")
        _data_unavailable()
    if not row:
        _audit(actor_id, "platform_admin.user.read", "platform_admin_users", str(mapping_id), {
            "outcome": "not_found",
            "endpoint": endpoint,
            "http_method": "GET",
            "target_platform_admin_user_id": mapping_id,
        })
        raise PlatformAdminServiceError(
            404, "platform_admin_user_not_found", "Platform-admin mapping not found."
        )
    safe = _safe_platform_admin_user(row)
    _audit(actor_id, "platform_admin.user.read", "platform_admin_users", str(mapping_id), {
        "outcome": "success",
        "endpoint": endpoint,
        "http_method": "GET",
        "target_platform_admin_user_id": mapping_id,
        "target_user_id": safe.get("user_id"),
        "old_is_active": None,
        "new_is_active": safe.get("is_active"),
    })
    return {"platform_admin_user": safe}


def create_platform_admin_user(payload, actor_mapping):
    if not isinstance(actor_mapping, dict):
        raise PlatformAdminServiceError(
            500, "platform_admin_context_invalid", "Platform context is invalid."
        )
    actor_id = _validated_actor_id(actor_mapping.get("id"))
    actor_user_id = _invalid_user_id(actor_mapping.get("user_id"))
    payload = _strict_body(payload, {"user_id"})
    target_user_id = _invalid_user_id(payload.get("user_id"))
    try:
        result = platform_admin_repository.create_platform_admin_user_mapping_for_platform_admin(
            actor_id, actor_user_id, target_user_id
        )
    except ValueError:
        _validation("invalid_user_id", "user_id must be a positive integer.")
    except Exception as exc:
        _handle_platform_admin_user_rpc_error(exc)
    return {
        "platform_admin_user": _safe_rpc_mapping(result["platform_admin_user"])
    }


def set_platform_admin_user_active(mapping_id, payload, actor_id):
    actor_id = _validated_actor_id(actor_id)
    mapping_id = _invalid_platform_admin_user_id(mapping_id)
    payload = _strict_body(payload, {"is_active"})
    if not isinstance(payload.get("is_active"), bool):
        _validation("invalid_is_active", "is_active must be true or false.")
    try:
        result = platform_admin_repository.set_platform_admin_user_active_for_platform_admin(
            actor_id, mapping_id, payload["is_active"]
        )
    except ValueError:
        _validation("invalid_platform_admin_user_id", "Platform-admin mapping ID must be a positive integer.")
    except Exception as exc:
        _handle_platform_admin_user_rpc_error(exc)
    return {
        "platform_admin_user": _safe_rpc_mapping(result["platform_admin_user"])
    }


def suspend_company(company_id, payload, actor_id):
    actor_id = _validated_actor_id(actor_id)
    company_id = _positive_id(company_id)
    _empty_body(payload)
    try:
        result = platform_company_repository.suspend_platform_company_for_platform_admin(
            actor_id, company_id
        )
    except ValueError:
        _validation("invalid_company_id", "Company ID must be a positive integer.")
    except Exception as exc:
        _handle_company_lifecycle_rpc_error(exc)
    return {"company": result["company"]}


def restore_company(company_id, payload, actor_id):
    actor_id = _validated_actor_id(actor_id)
    company_id = _positive_id(company_id)
    _empty_body(payload)
    try:
        result = platform_company_repository.restore_platform_company_for_platform_admin(
            actor_id, company_id
        )
    except ValueError:
        _validation("invalid_company_id", "Company ID must be a positive integer.")
    except Exception as exc:
        _handle_company_lifecycle_rpc_error(exc)
    return {"company": result["company"]}


SUPPORT_CASE_ENDPOINTS = platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS
SUPPORT_CASE_TEXT_LIMITS = {
    "title": 160,
    "redacted_summary": 2000,
    "redacted_note": 2000,
    "redacted_body": 4000,
}
SUPPORT_CASE_FORBIDDEN_TERMS = (
    "authorization", "cookie", "credential", "password", "secret", "token",
    "provider payload", "payment reference", "payment_reference", "checkout",
    "gateway", "impersonat", "customer message", "conversation content",
)
SUPPORT_REPLY_FORBIDDEN_TERMS = (
    "authorization", "cookie", "credential", "password", "secret", "token",
    "provider payload", "payment reference", "payment_reference", "checkout",
    "gateway", "impersonat",
)


def _support_case_text(value, *, field_name, required=True):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        _validation(f"invalid_{field_name}", f"{field_name} must be text.")
    normalized = value.strip()
    maximum = SUPPORT_CASE_TEXT_LIMITS[field_name]
    if required and not normalized:
        _validation(f"invalid_{field_name}", f"{field_name} is required.")
    if len(normalized) > maximum:
        _validation(f"invalid_{field_name}", f"{field_name} is too long.")
    lowered = normalized.casefold()
    if any(term in lowered for term in SUPPORT_CASE_FORBIDDEN_TERMS):
        _validation(
            f"invalid_{field_name}",
            f"{field_name} contains content outside the redacted support-case boundary.",
        )
    return normalized


def _support_reply_text(value):
    if not isinstance(value, str):
        _validation("invalid_redacted_body", "redacted_body must be text.")
    normalized = value.strip()
    if not normalized:
        _validation("invalid_redacted_body", "redacted_body is required.")
    if len(normalized) > SUPPORT_CASE_TEXT_LIMITS["redacted_body"]:
        _validation("invalid_redacted_body", "redacted_body is too long.")
    lowered = normalized.casefold()
    if any(term in lowered for term in SUPPORT_REPLY_FORBIDDEN_TERMS):
        _validation(
            "invalid_redacted_body",
            "redacted_body contains unsupported sensitive content.",
        )
    return normalized


def _support_case_company(company_id, actor_id):
    _positive_id(company_id)
    try:
        company = platform_company_repository.get_company_for_platform_admin(company_id)
    except Exception:
        logger.error("Platform support-case company lookup failed")
        _data_unavailable()
    if not company:
        _audit(actor_id, "platform_admin.company.read", "company", str(company_id), {
            "outcome": "not_found",
            "endpoint": platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["company_detail"],
            "http_method": "GET",
        })
        raise PlatformAdminServiceError(404, "company_not_found", "Company not found.")
    return company


def _safe_support_case_company(company):
    if not isinstance(company, dict):
        return None
    return {
        "id": company.get("id"),
        "company_name": company.get("company_name"),
        "status": company.get("status"),
    }


def _safe_support_case_row(row, company=None):
    if not isinstance(row, dict):
        row = {}
    return {
        "id": row.get("id"),
        "company_id": row.get("company_id"),
        "company": _safe_support_case_company(company),
        "created_by_platform_admin_user_id": row.get("created_by_platform_admin_user_id"),
        "assigned_platform_admin_user_id": row.get("assigned_platform_admin_user_id"),
        "status": row.get("status"),
        "priority": row.get("priority"),
        "title": row.get("title"),
        "redacted_summary": row.get("redacted_summary"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "closed_at": row.get("closed_at"),
    }


def _safe_platform_admin_assignee(row):
    if not isinstance(row, dict):
        row = {}
    return {
        "id": row.get("id"),
        "user_id": row.get("user_id"),
        "is_active": row.get("is_active"),
    }


def _safe_support_case_event(row):
    if not isinstance(row, dict):
        row = {}
    return {
        "id": row.get("id"),
        "case_id": row.get("case_id"),
        "event_type": row.get("event_type"),
        "actor_platform_admin_user_id": row.get("actor_platform_admin_user_id"),
        "old_status": row.get("old_status"),
        "new_status": row.get("new_status"),
        "old_priority": row.get("old_priority"),
        "new_priority": row.get("new_priority"),
        "old_assigned_platform_admin_user_id": row.get("old_assigned_platform_admin_user_id"),
        "new_assigned_platform_admin_user_id": row.get("new_assigned_platform_admin_user_id"),
        "tenant_support_reply_id": row.get("tenant_support_reply_id"),
        "redacted_note": row.get("redacted_note"),
        "created_at": row.get("created_at"),
    }


def _safe_support_case_reply(row):
    if not isinstance(row, dict):
        row = {}
    return {
        "reply_id": row.get("id"),
        "request_id": row.get("request_id"),
        "case_id": row.get("platform_support_case_id"),
        "company_id": row.get("company_id"),
        "author_type": row.get("author_type"),
        "redacted_body": row.get("redacted_body"),
        "visibility_status": row.get("visibility_status"),
        "created_at": row.get("created_at"),
    }


def _safe_support_reply_notification(row):
    if not isinstance(row, dict):
        row = {}
    return {
        "notification_id": row.get("id"),
        "reply_id": row.get("reply_id"),
        "channel": row.get("channel"),
        "status": row.get("status"),
        "attempt_count": row.get("attempt_count"),
        "last_attempt_at": row.get("last_attempt_at"),
        "delivered_at": row.get("delivered_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _support_case_or_not_found(case_id, actor_id, action, endpoint):
    _positive_id(case_id, "invalid_case_id")
    try:
        case = platform_support_case_repository.get_support_case_for_platform_admin(case_id)
    except Exception:
        logger.error("Platform support-case lookup failed")
        _data_unavailable()
    if not case:
        _audit(actor_id, action, "platform_support_cases", str(case_id), {
            "outcome": "not_found", "endpoint": endpoint, "http_method": "GET",
        })
        raise PlatformAdminServiceError(404, "support_case_not_found", "Support case not found.")
    return case


def _support_case_companies(cases):
    ids = [row.get("company_id") for row in cases if isinstance(row, dict)]
    try:
        return platform_company_repository.get_companies_by_ids_for_platform_admin(ids)
    except Exception:
        logger.error("Platform support-case company lookup failed")
        _data_unavailable()


def list_support_cases(actor_id, *, limit=None, offset=None, company_id=None,
                       status=None, priority=None):
    actor_id = _validated_actor_id(actor_id)
    endpoint = SUPPORT_CASE_ENDPOINTS["support_case_list"]
    limit = _integer_parameter(limit, name="limit", default=25, minimum=1, maximum=100)
    offset = _integer_parameter(offset, name="offset", default=0, minimum=0)
    company_id = _optional_positive_integer_parameter(company_id, name="company_id")
    normalized_status = _optional_exact_member_parameter(
        status, name="status", allowed=platform_support_case_repository.ALLOWED_STATUSES,
        code="invalid_status",
    )
    normalized_priority = _optional_exact_member_parameter(
        priority, name="priority", allowed=platform_support_case_repository.ALLOWED_PRIORITIES,
        code="invalid_priority",
    )
    try:
        cases, total = platform_support_case_repository.list_support_cases_for_platform_admin(
            limit=limit, offset=offset, company_id=company_id,
            status=normalized_status, priority=normalized_priority,
        )
        companies = _support_case_companies(cases)
    except PlatformAdminServiceError:
        raise
    except Exception:
        logger.error("Platform support-case listing failed")
        _data_unavailable()
    result = {
        "cases": [_safe_support_case_row(row, companies.get(row.get("company_id"))) for row in cases],
        "pagination": {
            "limit": limit, "offset": offset, "returned": len(cases),
            "total": total, "has_more": offset + len(cases) < total,
        },
        "filters": {
            "company_id": company_id, "status": normalized_status,
            "priority": normalized_priority,
        },
    }
    _audit(actor_id, "platform_admin.support_case.list", "platform_support_cases", None, {
        "outcome": "success", "endpoint": endpoint, "http_method": "GET",
        "limit": limit, "offset": offset,
        "company_filter_applied": company_id is not None,
        "status_filter_applied": normalized_status is not None,
        "priority_filter_applied": normalized_priority is not None,
        "returned_count": len(cases),
    })
    return result


SUPPORT_CASE_STATUS_TRANSITIONS = {
    "open": {"in_progress", "waiting_for_tenant", "resolved"},
    "in_progress": {"waiting_for_tenant", "resolved"},
    "waiting_for_tenant": {"in_progress", "resolved"},
    "resolved": {"closed", "in_progress"},
    "closed": {"in_progress"},
}


def _safe_support_case_transition_options(status):
    return sorted(SUPPORT_CASE_STATUS_TRANSITIONS.get(status, set()))


def list_support_case_assignees(actor_id):
    actor_id = _validated_actor_id(actor_id)
    try:
        assignees = platform_support_case_repository.list_active_platform_admin_assignees_for_platform_admin()
    except Exception:
        logger.error("Platform support-case assignee lookup failed")
        _data_unavailable()
    _audit(actor_id, "platform_admin.support_case.assignee.list", "platform_admin_users", None, {
        "outcome": "success",
        "endpoint": SUPPORT_CASE_ENDPOINTS["support_case_assignee_list"],
        "http_method": "GET",
        "returned_count": len(assignees),
    })
    return {"assignees": [_safe_platform_admin_assignee(row) for row in assignees]}


def get_support_case(case_id, actor_id):
    actor_id = _validated_actor_id(actor_id)
    endpoint = SUPPORT_CASE_ENDPOINTS["support_case_read"]
    case = _support_case_or_not_found(
        case_id, actor_id, "platform_admin.support_case.read",
        SUPPORT_CASE_ENDPOINTS["support_case_read"],
    )
    try:
        events = platform_support_case_repository.list_support_case_events_for_platform_admin(case_id)
        company = platform_company_repository.get_company_for_platform_admin(case.get("company_id"))
        source_request = (
            tenant_support_repository
            .get_tenant_support_request_by_converted_case_id_for_platform_admin(case_id)
        )
    except Exception:
        logger.error("Platform support-case detail lookup failed")
        _data_unavailable()
    result = {
        "case": _safe_support_case_row(case, company),
        "events": [_safe_support_case_event(event) for event in events],
        "source_tenant_request": (
            _safe_tenant_support_request_row(source_request)
            if source_request else None
        ),
        "status_transitions": _safe_support_case_transition_options(case.get("status")),
    }
    _audit(actor_id, "platform_admin.support_case.read", "platform_support_cases", str(case_id), {
        "outcome": "success", "endpoint": endpoint, "http_method": "GET",
    })
    return result


def list_support_case_replies(case_id, actor_id):
    actor_id = _validated_actor_id(actor_id)
    endpoint = SUPPORT_CASE_ENDPOINTS["support_case_reply_list"]
    case = _support_case_or_not_found(
        case_id, actor_id, "platform_admin.support_case.reply.list", endpoint
    )
    try:
        source_request = (
            tenant_support_repository
            .get_tenant_support_request_by_converted_case_id_for_platform_admin(case_id)
        )
        replies = platform_support_case_repository.list_support_case_replies_for_platform_admin(case_id)
        notifications = (
            platform_support_case_repository
            .list_support_case_reply_notifications_for_platform_admin(case_id)
        )
    except Exception:
        logger.error("Platform support-case reply list failed")
        _data_unavailable()
    metadata = {
        "outcome": "success",
        "endpoint": endpoint,
        "http_method": "GET",
        "returned_count": len(replies),
        "company_id": case.get("company_id"),
    }
    if source_request:
        metadata["request_id"] = source_request.get("id")
    _audit(
        actor_id,
        "platform_admin.support_case.reply.list",
        "platform_support_cases",
        str(case_id),
        metadata,
    )
    return {
        "case": _safe_support_case_row(case),
        "source_tenant_request": (
            _safe_tenant_support_request_row(source_request)
            if source_request else None
        ),
        "replies": [_safe_support_case_reply(reply) for reply in replies],
        "notifications": [
            _safe_support_reply_notification(notification)
            for notification in notifications
        ],
    }


def create_support_case_reply(case_id, payload, actor_id):
    actor_id = _validated_actor_id(actor_id)
    _positive_id(case_id, "invalid_case_id")
    if not isinstance(payload, dict):
        _validation("invalid_request", "Request body must be an object.")
    if set(payload) != {"redacted_body"}:
        _validation("invalid_request", "Only redacted_body may be submitted.")
    body = _support_reply_text(payload.get("redacted_body"))
    _support_case_or_not_found(
        case_id, actor_id, "platform_admin.support_case.read",
        SUPPORT_CASE_ENDPOINTS["support_case_read"],
    )
    try:
        result = platform_support_case_repository.create_support_case_reply_for_platform_admin(
            case_id, actor_id, body
        )
    except ValueError:
        _validation("invalid_redacted_body", "redacted_body is invalid.")
    except Exception as exc:
        _handle_support_case_rpc_error(exc, operation="reply")
    try:
        company = platform_company_repository.get_company_for_platform_admin(
            result["case"].get("company_id")
        )
    except Exception:
        logger.error("Platform support-case reply response refresh failed")
        _data_unavailable()
    return {
        "case": _safe_support_case_row(result["case"], company),
        "event": _safe_support_case_event(result["event"]),
        "reply": _safe_support_case_reply(result.get("reply")),
        "notification": _safe_support_reply_notification(result.get("notification")),
        "status_transitions": _safe_support_case_transition_options(result["case"].get("status")),
    }


def create_support_case(payload, actor_id):
    actor_id = _validated_actor_id(actor_id)
    endpoint = SUPPORT_CASE_ENDPOINTS["support_case_create"]
    if not isinstance(payload, dict):
        _validation("invalid_request", "Request body must be an object.")
    company_id = payload.get("company_id")
    if isinstance(company_id, bool) or not isinstance(company_id, int) or company_id <= 0:
        _validation("invalid_company_id", "Company ID must be a positive integer.")
    title = _support_case_text(payload.get("title"), field_name="title")
    summary = _support_case_text(payload.get("redacted_summary"), field_name="redacted_summary")
    status = payload.get("status", "open")
    priority = payload.get("priority", "normal")
    status = _optional_exact_member_parameter(
        status, name="status", allowed=platform_support_case_repository.ALLOWED_STATUSES,
        code="invalid_status",
    )
    priority = _optional_exact_member_parameter(
        priority, name="priority", allowed=platform_support_case_repository.ALLOWED_PRIORITIES,
        code="invalid_priority",
    )
    company = _support_case_company(company_id, actor_id)
    now = _now_utc_iso()
    try:
        case = platform_support_case_repository.create_support_case_for_platform_admin({
            "company_id": company_id,
            "created_by_platform_admin_user_id": actor_id,
            "status": status,
            "priority": priority,
            "title": title,
            "redacted_summary": summary,
            "created_at": now,
            "updated_at": now,
        })
        platform_support_case_repository.create_support_case_event_for_platform_admin({
            "case_id": case["id"], "event_type": "created",
            "actor_platform_admin_user_id": actor_id, "new_status": status,
            "new_priority": priority, "created_at": now,
        })
    except Exception:
        logger.error("Platform support-case creation failed")
        _data_unavailable()
    _audit(actor_id, "platform_admin.support_case.create", "platform_support_cases", str(case["id"]), {
        "outcome": "success", "endpoint": endpoint, "http_method": "POST",
        "company_id": company_id, "status": status, "priority": priority,
    })
    return {"case": _safe_support_case_row(case, company)}


def add_support_case_note(case_id, payload, actor_id):
    actor_id = _validated_actor_id(actor_id)
    _positive_id(case_id, "invalid_case_id")
    if not isinstance(payload, dict):
        _validation("invalid_request", "Request body must be an object.")
    if set(payload) != {"redacted_note"}:
        _validation("invalid_request", "Only redacted_note may be submitted.")
    note = _support_case_text(payload.get("redacted_note"), field_name="redacted_note")
    _support_case_or_not_found(
        case_id, actor_id, "platform_admin.support_case.read",
        SUPPORT_CASE_ENDPOINTS["support_case_read"],
    )
    try:
        result = platform_support_case_repository.add_support_case_note_for_platform_admin(
            case_id, actor_id, note
        )
    except Exception as exc:
        _handle_support_case_rpc_error(exc, operation="note")
    try:
        company = platform_company_repository.get_company_for_platform_admin(
            result["case"].get("company_id")
        )
    except Exception:
        logger.error("Platform support-case note response refresh failed")
        _data_unavailable()
    return {
        "case": _safe_support_case_row(result["case"], company),
        "event": _safe_support_case_event(result["event"]),
        "status_transitions": _safe_support_case_transition_options(result["case"].get("status")),
    }


def assign_support_case(case_id, payload, actor_id):
    actor_id = _validated_actor_id(actor_id)
    _positive_id(case_id, "invalid_case_id")
    if not isinstance(payload, dict):
        _validation("invalid_request", "Request body must be an object.")
    if set(payload) != {"assigned_platform_admin_user_id"}:
        _validation("invalid_request", "Only assigned_platform_admin_user_id may be updated.")
    assignee_id = payload.get("assigned_platform_admin_user_id")
    if assignee_id is not None and (
        isinstance(assignee_id, bool) or not isinstance(assignee_id, int) or assignee_id <= 0
    ):
        _validation("invalid_assignee", "Assignee must be an active platform-admin mapping ID or null.")
    if assignee_id is not None:
        try:
            assignee = (
                platform_support_case_repository
                .get_active_platform_admin_assignee_for_platform_admin(assignee_id)
            )
        except Exception:
            logger.error("Platform support-case assignee validation failed")
            _data_unavailable()
        if not assignee:
            _validation("invalid_assignee", "Assignee must be an active platform-admin mapping ID or null.")
    case = _support_case_or_not_found(
        case_id, actor_id, "platform_admin.support_case.read",
        SUPPORT_CASE_ENDPOINTS["support_case_read"],
    )
    if case.get("assigned_platform_admin_user_id") == assignee_id:
        _validation("no_change", "Support case assignee is unchanged.")
    try:
        result = platform_support_case_repository.assign_support_case_for_platform_admin(
            case_id, actor_id, assignee_id
        )
    except Exception as exc:
        _handle_support_case_rpc_error(exc, operation="assignment")
    try:
        company = platform_company_repository.get_company_for_platform_admin(
            result["case"].get("company_id")
        )
    except Exception:
        logger.error("Platform support-case assignment response refresh failed")
        _data_unavailable()
    event = result["event"]
    return {
        "case": _safe_support_case_row(result["case"], company),
        "event": _safe_support_case_event(event),
        "status_transitions": _safe_support_case_transition_options(result["case"].get("status")),
    }


def update_support_case_status(case_id, payload, actor_id):
    actor_id = _validated_actor_id(actor_id)
    _positive_id(case_id, "invalid_case_id")
    if not isinstance(payload, dict):
        _validation("invalid_request", "Request body must be an object.")
    if set(payload) != {"status"}:
        _validation("invalid_request", "Only status may be updated.")
    status = _optional_exact_member_parameter(
        payload.get("status"), name="status", allowed=platform_support_case_repository.ALLOWED_STATUSES,
        code="invalid_status",
    )
    case = _support_case_or_not_found(
        case_id, actor_id, "platform_admin.support_case.read",
        SUPPORT_CASE_ENDPOINTS["support_case_read"],
    )
    current_status = case.get("status")
    if status == current_status:
        _validation("no_change", "Support case status is unchanged.")
    if status not in SUPPORT_CASE_STATUS_TRANSITIONS.get(current_status, set()):
        _validation("invalid_status", "Support case status transition is not allowed.")
    try:
        result = platform_support_case_repository.set_support_case_status_for_platform_admin(
            case_id, actor_id, status
        )
    except ValueError as exc:
        _validation("invalid_status", str(exc))
    except Exception as exc:
        _handle_support_case_rpc_error(exc, operation="status")
    try:
        company = platform_company_repository.get_company_for_platform_admin(
            result["case"].get("company_id")
        )
    except Exception:
        logger.error("Platform support-case status response refresh failed")
        _data_unavailable()
    event = result["event"]
    return {
        "case": _safe_support_case_row(result["case"], company),
        "event": _safe_support_case_event(event),
        "status_transitions": _safe_support_case_transition_options(result["case"].get("status")),
    }


def update_support_case_priority(case_id, payload, actor_id):
    actor_id = _validated_actor_id(actor_id)
    _positive_id(case_id, "invalid_case_id")
    if not isinstance(payload, dict):
        _validation("invalid_request", "Request body must be an object.")
    if set(payload) != {"priority"}:
        _validation("invalid_request", "Only priority may be updated.")
    priority = _optional_exact_member_parameter(
        payload.get("priority"), name="priority", allowed=platform_support_case_repository.ALLOWED_PRIORITIES,
        code="invalid_priority",
    )
    case = _support_case_or_not_found(
        case_id, actor_id, "platform_admin.support_case.read",
        SUPPORT_CASE_ENDPOINTS["support_case_read"],
    )
    if priority == case.get("priority"):
        _validation("no_change", "Support case priority is unchanged.")
    try:
        result = platform_support_case_repository.set_support_case_priority_for_platform_admin(
            case_id, actor_id, priority
        )
    except ValueError as exc:
        _validation("invalid_priority", str(exc))
    except Exception as exc:
        _handle_support_case_rpc_error(exc, operation="priority")
    try:
        company = platform_company_repository.get_company_for_platform_admin(
            result["case"].get("company_id")
        )
    except Exception:
        logger.error("Platform support-case priority response refresh failed")
        _data_unavailable()
    event = result["event"]
    return {
        "case": _safe_support_case_row(result["case"], company),
        "event": _safe_support_case_event(event),
        "status_transitions": _safe_support_case_transition_options(result["case"].get("status")),
    }


def _safe_tenant_support_request_row(row, *, include_content=False):
    safe = {
        "request_id": row.get("id"),
        "company_id": row.get("company_id"),
        "requester_user_id": row.get("requester_user_id"),
        "category": row.get("category"),
        "status": row.get("status"),
        "priority": row.get("priority"),
        "source": row.get("source"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "closed_at": row.get("closed_at"),
    }
    if include_content:
        safe["title"] = row.get("title")
        safe["redacted_description"] = row.get("redacted_description")
    return safe


def _safe_tenant_support_event(row):
    return {
        "event_type": row.get("event_type"),
        "actor_type": row.get("actor_type"),
        "created_at": row.get("created_at"),
    }


def list_tenant_support_requests(actor_id, *, limit=None, offset=None,
                                 company_id=None, category=None, status=None):
    actor_id = _validated_actor_id(actor_id)
    endpoint = SUPPORT_CASE_ENDPOINTS["tenant_support_request_list"]
    limit = _integer_parameter(limit, name="limit", default=25, minimum=1, maximum=100)
    offset = _integer_parameter(offset, name="offset", default=0, minimum=0)
    company_id = _optional_positive_integer_parameter(company_id, name="company_id")
    category = _optional_exact_member_parameter(
        category, name="category", allowed=tenant_support_repository.ALLOWED_CATEGORIES,
        code="invalid_category",
    )
    status = _optional_exact_member_parameter(
        status, name="status", allowed=tenant_support_repository.ALLOWED_STATUSES,
        code="invalid_status",
    )
    try:
        rows, total = tenant_support_repository.list_tenant_support_requests_for_platform_admin(
            limit=limit, offset=offset, company_id=company_id,
            category=category, status=status,
        )
    except Exception:
        logger.error("Tenant support request list lookup failed")
        _data_unavailable()
    result = {
        "requests": [_safe_tenant_support_request_row(row) for row in rows],
        "pagination": {
            "limit": limit, "offset": offset, "returned": len(rows),
            "total": total, "has_more": offset + len(rows) < total,
        },
        "filters": {
            "company_id": company_id, "category": category, "status": status,
        },
    }
    _audit(actor_id, "platform_admin.tenant_support_request.list",
           "tenant_support_requests", None, {
               "outcome": "success", "endpoint": endpoint, "http_method": "GET",
               "limit": limit, "offset": offset, "returned_count": len(rows),
               "company_filter_applied": company_id is not None,
               "category_filter_applied": category is not None,
               "status_filter_applied": status is not None,
           })
    return result


def get_tenant_support_request(request_id, actor_id):
    actor_id = _validated_actor_id(actor_id)
    request_id = _positive_id(request_id, "invalid_request_id")
    endpoint = SUPPORT_CASE_ENDPOINTS["tenant_support_request_read"]
    try:
        row = tenant_support_repository.get_tenant_support_request_for_platform_admin(request_id)
    except Exception:
        logger.error("Tenant support request detail lookup failed")
        _data_unavailable()
    if not row:
        _audit(actor_id, "platform_admin.tenant_support_request.read",
               "tenant_support_requests", str(request_id), {
                   "outcome": "not_found", "endpoint": endpoint, "http_method": "GET",
               })
        raise PlatformAdminServiceError(
            404, "tenant_support_request_not_found", "Tenant support request not found."
        )
    try:
        events = tenant_support_repository.list_tenant_support_request_events_for_platform_admin(
            request_id
        )
    except Exception:
        logger.error("Tenant support request event lookup failed")
        _data_unavailable()
    result = {
        "request": _safe_tenant_support_request_row(row, include_content=True),
        "events": [_safe_tenant_support_event(event) for event in events],
    }
    _audit(actor_id, "platform_admin.tenant_support_request.read",
           "tenant_support_requests", str(request_id), {
               "outcome": "success", "endpoint": endpoint, "http_method": "GET",
           })
    return result


def update_tenant_support_request(request_id, payload, actor_id):
    actor_id = _validated_actor_id(actor_id)
    request_id = _positive_id(request_id, "invalid_request_id")
    if not isinstance(payload, dict):
        _validation("invalid_request", "Request body must be an object.")
    if set(payload) != {"status"}:
        _validation("invalid_request", "Only status may be updated.")
    status = _optional_exact_member_parameter(
        payload.get("status"), name="status",
        allowed={"reviewed", "closed"}, code="invalid_status",
    )
    try:
        result = tenant_support_repository.set_tenant_support_request_status_for_platform_admin(
            request_id, actor_id, status
        )
    except ValueError as exc:
        _validation("invalid_status", str(exc))
    except Exception:
        logger.error("Tenant support request status update failed")
        _data_unavailable()
    safe = {
        "request_id": result["request_id"],
        "status": result["status"],
    }
    for key in ("old_status", "new_status", "closed_at"):
        if key in result:
            safe[key] = result[key]
    return safe


def convert_tenant_support_request(request_id, payload, actor_id):
    actor_id = _validated_actor_id(actor_id)
    request_id = _positive_id(request_id, "invalid_request_id")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict) or payload:
        _validation("invalid_request", "Conversion request body must be empty.")
    try:
        result = tenant_support_repository.convert_tenant_support_request_for_platform_admin(
            request_id, actor_id
        )
    except Exception:
        logger.error("Tenant support request conversion failed")
        _data_unavailable()
    return {
        "request_id": result["request_id"],
        "status": result["status"],
        "converted_platform_support_case_id": result[
            "converted_platform_support_case_id"
        ],
    }


def _company_or_not_found(company_id, actor_id, action, resource_type, endpoint):
    _positive_id(company_id)
    try:
        company = platform_company_repository.get_company_for_platform_admin(company_id)
    except Exception:
        logger.error("Platform company lookup failed")
        _data_unavailable()
    if not company:
        _audit(actor_id, action, resource_type, str(company_id), {
            "outcome": "not_found", "endpoint": endpoint, "http_method": "GET",
        })
        raise PlatformAdminServiceError(404, "company_not_found", "Company not found.")
    return company


def get_current_platform_admin_identity(authenticated_user, platform_admin_user):
    user_id = authenticated_user.get("id") if isinstance(authenticated_user, dict) else None
    actor_id = platform_admin_user.get("id") if isinstance(platform_admin_user, dict) else None
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise PlatformAdminServiceError(500, "platform_admin_context_invalid", "Platform context is invalid.")
    actor_id = _validated_actor_id(actor_id)
    data = {
        "user": {
            "id": user_id,
            "email": authenticated_user.get("email"),
            "full_name": authenticated_user.get("full_name"),
            "status": authenticated_user.get("status"),
        },
        "platform_admin": {
            "id": actor_id,
            "is_active": platform_admin_user.get("is_active"),
            "created_at": platform_admin_user.get("created_at"),
            "updated_at": platform_admin_user.get("updated_at"),
        },
    }
    _audit(actor_id, "platform_admin.identity.read", "platform_admin", str(actor_id), {
        "outcome": "success",
        "endpoint": platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["identity"],
        "http_method": "GET",
    })
    return data


def list_audit_events(
    actor_id, *, limit=None, offset=None, action=None, resource_type=None,
    actor_user_id=None, resource_id=None, created_after=None, created_before=None
):
    actor_id = _validated_actor_id(actor_id)
    endpoint = platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["audit_events"]
    limit = _integer_parameter(limit, name="limit", default=25, minimum=1, maximum=100)
    offset = _integer_parameter(offset, name="offset", default=0, minimum=0)
    normalized_action = _optional_exact_member_parameter(
        action,
        name="action",
        allowed=platform_admin_repository.ALLOWED_AUDIT_ACTIONS,
        code="invalid_action",
    )
    normalized_resource_type = _optional_exact_member_parameter(
        resource_type,
        name="resource_type",
        allowed=platform_admin_repository.ALLOWED_RESOURCE_TYPES,
        code="invalid_resource_type",
    )
    normalized_actor_user_id = _optional_positive_integer_parameter(
        actor_user_id, name="actor_user_id"
    )
    normalized_resource_id = _optional_resource_id_parameter(resource_id)
    parsed_after = _optional_datetime_parameter(created_after, name="created_after")
    parsed_before = _optional_datetime_parameter(created_before, name="created_before")
    if parsed_after and parsed_before and parsed_after >= parsed_before:
        _validation("invalid_created_before", "created_after must be earlier than created_before.")

    try:
        rows, total = platform_admin_repository.list_platform_admin_audit_events_for_platform_admin(
            limit=limit,
            offset=offset,
            action=normalized_action,
            resource_type=normalized_resource_type,
            actor_user_id=normalized_actor_user_id,
            resource_id=normalized_resource_id,
            created_after=parsed_after,
            created_before=parsed_before,
        )
    except Exception:
        logger.error("Platform audit event listing failed")
        _data_unavailable()

    safe_rows = [_safe_audit_event_response_row(row) for row in (rows or [])]
    result = {
        "audit_events": safe_rows,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(safe_rows),
            "total": int(total or 0),
            "has_more": offset + len(safe_rows) < int(total or 0),
        },
        "filters": {
            "action": normalized_action,
            "resource_type": normalized_resource_type,
            "actor_user_id": normalized_actor_user_id,
            "resource_id": normalized_resource_id,
            "created_after": parsed_after.isoformat() if parsed_after else None,
            "created_before": parsed_before.isoformat() if parsed_before else None,
        },
        "ordering": {
            "by": "created_at",
            "order": "desc",
            "tie_breaker": "id desc",
        },
    }
    _audit(actor_id, "platform_admin.audit_events.list",
           "platform_admin_audit_events", None, {
               "outcome": "success",
               "endpoint": endpoint,
               "http_method": "GET",
               "limit": limit,
               "offset": offset,
               "action_filter_applied": normalized_action is not None,
               "resource_type_filter_applied": normalized_resource_type is not None,
               "actor_user_id_filter_applied": normalized_actor_user_id is not None,
               "resource_id_filter_applied": normalized_resource_id is not None,
               "created_after_filter_applied": parsed_after is not None,
               "created_before_filter_applied": parsed_before is not None,
               "returned_count": len(safe_rows),
           })
    return result


def get_operations_overview(actor_id):
    actor_id = _validated_actor_id(actor_id)
    generated_at = _now_utc_iso()
    try:
        company_counts = platform_company_repository.get_company_counts_for_platform_admin()
        subscription_overview = (
            platform_billing_repository.get_latest_subscription_overview_for_platform_admin()
        )
        attention_subscriptions = subscription_overview.get("attention_subscriptions") or []
        companies_by_id = platform_company_repository.get_companies_by_ids_for_platform_admin(
            row.get("company_id") for row in attention_subscriptions
        )
        monitoring_overview = (
            platform_monitoring_repository.get_monitoring_overview_for_platform_admin()
        )
    except Exception:
        logger.error("Platform operations overview lookup failed")
        _data_unavailable()

    def _safe_count(value):
        return int(value) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    def _strict_count(value, *, field_name):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RuntimeError(f"Malformed monitoring count for {field_name}")
        return value

    def _strict_count_map(value, *, field_name, allowed_keys):
        if not isinstance(value, dict):
            raise RuntimeError(f"Malformed monitoring map for {field_name}")
        allowed = set(allowed_keys)
        result = {}
        for key in sorted(allowed):
            result[key] = _strict_count(value.get(key, 0), field_name=f"{field_name}.{key}")
        unknown = set(value) - allowed
        if unknown:
            raise RuntimeError(f"Unexpected monitoring keys for {field_name}")
        return result

    def _strict_window(value, *, days):
        if not isinstance(value, dict):
            raise RuntimeError("Malformed monitoring window")
        since = value.get("since")
        if not isinstance(since, str) or not since.strip():
            raise RuntimeError("Malformed monitoring window")
        if value.get("days") != days:
            raise RuntimeError("Malformed monitoring window")
        datetime.fromisoformat(since.replace("Z", "+00:00"))
        return {"days": days, "since": since}

    try:
        active_user_count = _strict_count(
            monitoring_overview.get("active_user_count"),
            field_name="active_user_count",
        )
        support_monitoring = _safe_support_monitoring(
            monitoring_overview.get("support"),
            _strict_count,
            _strict_count_map,
        )
        messaging_monitoring = _safe_messaging_monitoring(
            monitoring_overview.get("messaging"),
            _strict_count,
            _strict_count_map,
        )
        billing_attention = _safe_billing_attention(
            monitoring_overview.get("billing_attention"),
            _strict_count,
            _strict_count_map,
        )
        ai_usage = _safe_ai_usage_monitoring(
            monitoring_overview.get("ai_usage"),
            _strict_count,
            _strict_count_map,
            _strict_window,
        )
        platform_activity = _safe_platform_activity_monitoring(
            monitoring_overview.get("platform_admin_activity"),
            _strict_count,
            _strict_count_map,
            _strict_window,
        )
    except Exception:
        logger.error("Platform operations overview validation failed")
        _data_unavailable()

    by_status = subscription_overview.get("by_status") or {}
    attention = []
    for row in attention_subscriptions[:10]:
        company_id = row.get("company_id")
        company = companies_by_id.get(company_id) or {}
        if not isinstance(company_id, int) or isinstance(company_id, bool) or company_id <= 0:
            continue
        attention.append({
            "company_id": company_id,
            "company_name": company.get("company_name"),
            "company_status": company.get("status"),
            "subscription_status": row.get("subscription_status"),
            "plan_code": row.get("plan_code"),
            "plan_name": row.get("plan_name"),
            "status_updated_at": row.get("status_updated_at"),
            "current_period_end": row.get("current_period_end"),
        })

    def _subscription_alert(row):
        company_id = row.get("company_id")
        if not isinstance(company_id, int) or isinstance(company_id, bool) or company_id <= 0:
            return None
        status = str(row.get("subscription_status") or "").strip().lower()
        if status == "past_due":
            alert_type = "subscription_past_due"
            severity = "warning"
            summary = "Subscription is past due"
        elif status == "expired":
            alert_type = "subscription_expired"
            severity = "critical"
            summary = "Subscription is expired"
        else:
            return None
        return {
            "type": alert_type,
            "severity": severity,
            "company_id": company_id,
            "company_name": row.get("company_name"),
            "company_status": row.get("company_status"),
            "summary": summary,
            "details": {
                "subscription_status": status,
                "plan_code": row.get("plan_code"),
                "plan_name": row.get("plan_name"),
                "current_period_end": row.get("current_period_end"),
                "status_updated_at": row.get("status_updated_at"),
            },
            "investigation_url": f"platform-admin-company.html?company_id={company_id}",
        }

    alerts = []
    for row in attention:
        alert = _subscription_alert(row)
        if alert:
            alerts.append(alert)
        if len(alerts) >= 10:
            break
    alert_summary = {"total": len(alerts), "critical": 0, "warning": 0, "info": 0}
    for alert in alerts:
        severity = alert.get("severity")
        if severity in ("critical", "warning", "info"):
            alert_summary[severity] += 1

    for alert in _phase6_operational_alerts(
        support_monitoring=support_monitoring,
        messaging_monitoring=messaging_monitoring,
        billing_attention=billing_attention,
        ai_usage=ai_usage,
    ):
        if len(alerts) >= 10:
            break
        alerts.append(alert)
        severity = alert.get("severity")
        if severity in ("critical", "warning", "info"):
            alert_summary[severity] += 1
    alert_summary["total"] = len(alerts)

    result = {
        "generated_at": generated_at,
        "companies": {
            "total": _safe_count(company_counts.get("total")),
            "active": _safe_count(company_counts.get("active")),
            "inactive": _safe_count(company_counts.get("inactive")),
            "active_users": active_user_count,
        },
        "subscriptions": {
            "by_status": {
                "trialing": _safe_count(by_status.get("trialing")),
                "active": _safe_count(by_status.get("active")),
                "past_due": _safe_count(by_status.get("past_due")),
                "expired": _safe_count(by_status.get("expired")),
                "cancelled": _safe_count(by_status.get("cancelled")),
            },
            "by_plan": [
                {
                    "code": str(plan.get("code") or ""),
                    "name": str(plan.get("name") or ""),
                    "count": _safe_count(plan.get("count")),
                }
                for plan in (subscription_overview.get("by_plan") or [])
                if plan.get("code")
            ],
        },
        "support": support_monitoring,
        "messaging": messaging_monitoring,
        "billing_attention": billing_attention,
        "ai_usage": ai_usage,
        "platform_admin_activity": platform_activity,
        "attention_companies": attention,
        "operational_alerts": {
            "alerts": alerts,
            "summary": alert_summary,
            "limits": {"max_alerts": 10},
        },
    }
    _audit(actor_id, "platform_admin.operations.overview.read", "platform_operations_overview", None, {
        "outcome": "success",
        "endpoint": platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["operations_overview"],
        "http_method": "GET",
        "attention_company_count": len(attention),
        "generated_at": generated_at,
    })
    return result


def get_billing_overview(actor_id):
    actor_id = _validated_actor_id(actor_id)
    endpoint = platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["billing_overview"]
    try:
        result = platform_billing_oversight_repository.get_billing_overview_for_platform_admin()
    except Exception:
        logger.error("Platform billing overview lookup failed")
        _data_unavailable()
    _audit(actor_id, "platform_admin.billing.overview.read", "platform_billing_overview", None, {
        "outcome": "success",
        "endpoint": endpoint,
        "http_method": "GET",
        "generated_at": result["generated_at"],
    })
    return result


def list_billing_companies(
    actor_id, *, limit=None, offset=None, subscription_status=None, plan=None, attention=None
):
    actor_id = _validated_actor_id(actor_id)
    endpoint = platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["billing_company_list"]
    limit = _integer_parameter(limit, name="limit", default=25, minimum=1, maximum=100)
    offset = _integer_parameter(offset, name="offset", default=0, minimum=0)
    normalized_status = subscription_status.strip().lower() if isinstance(subscription_status, str) else subscription_status
    if normalized_status not in platform_billing_oversight_repository.SUBSCRIPTION_STATUSES + (None,):
        _validation("invalid_status", "subscription_status is not supported.")
    normalized_plan = None
    if plan is not None:
        if not isinstance(plan, str):
            _validation("invalid_plan", "plan is not supported.")
        normalized_plan = plan.strip().lower()
        if not normalized_plan or len(normalized_plan) > 50:
            _validation("invalid_plan", "plan is not supported.")
    normalized_attention = None
    if attention is not None:
        if not isinstance(attention, str):
            _validation("invalid_attention", "attention must be true or false.")
        raw = attention.strip().lower()
        if raw in {"true", "1", "yes"}:
            normalized_attention = True
        elif raw in {"false", "0", "no"}:
            normalized_attention = False
        else:
            _validation("invalid_attention", "attention must be true or false.")
    try:
        rows, total = platform_billing_oversight_repository.list_billing_companies_for_platform_admin(
            limit=limit,
            offset=offset,
            subscription_status=normalized_status,
            plan=normalized_plan,
            attention=normalized_attention,
        )
    except Exception:
        logger.error("Platform billing company directory lookup failed")
        _data_unavailable()
    result = {
        "companies": rows,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(rows),
            "total": total,
            "has_more": offset + len(rows) < total,
        },
        "filters": {
            "subscription_status": normalized_status,
            "plan": normalized_plan,
            "attention": normalized_attention,
        },
        "ordering": {"by": "company_id", "order": "asc"},
    }
    _audit(actor_id, "platform_admin.billing.company_list", "platform_billing_companies", None, {
        "outcome": "success",
        "endpoint": endpoint,
        "http_method": "GET",
        "limit": limit,
        "offset": offset,
        "subscription_status_filter_applied": normalized_status is not None,
        "plan_filter_applied": normalized_plan is not None,
        "attention_filter_applied": normalized_attention is not None,
        "returned_count": len(rows),
    })
    return result


def _safe_support_monitoring(value, strict_count, strict_count_map):
    if not isinstance(value, dict):
        raise RuntimeError("Malformed support monitoring")
    return {
        "cases_by_status": strict_count_map(
            value.get("cases_by_status"),
            field_name="support.cases_by_status",
            allowed_keys=platform_monitoring_repository.SUPPORT_CASE_STATUSES,
        ),
        "cases_by_priority": strict_count_map(
            value.get("cases_by_priority"),
            field_name="support.cases_by_priority",
            allowed_keys=platform_monitoring_repository.SUPPORT_CASE_PRIORITIES,
        ),
        "open_case_count": strict_count(value.get("open_case_count"), field_name="support.open_case_count"),
        "tenant_requests_by_status": strict_count_map(
            value.get("tenant_requests_by_status"),
            field_name="support.tenant_requests_by_status",
            allowed_keys=platform_monitoring_repository.TENANT_SUPPORT_REQUEST_STATUSES,
        ),
        "unresolved_tenant_request_count": strict_count(
            value.get("unresolved_tenant_request_count"),
            field_name="support.unresolved_tenant_request_count",
        ),
    }


def _safe_messaging_monitoring(value, strict_count, strict_count_map):
    if not isinstance(value, dict):
        raise RuntimeError("Malformed messaging monitoring")
    channel_health = value.get("channel_health")
    if not isinstance(channel_health, dict):
        raise RuntimeError("Malformed channel health")
    safe_channels = {}
    for provider in ("telegram", "wasender", "meta_whatsapp"):
        row = channel_health.get(provider)
        if not isinstance(row, dict):
            raise RuntimeError("Malformed channel health")
        safe_channels[provider] = {
            "total": strict_count(row.get("total"), field_name=f"channel_health.{provider}.total"),
            "active": strict_count(row.get("active"), field_name=f"channel_health.{provider}.active"),
            "inactive": strict_count(row.get("inactive"), field_name=f"channel_health.{provider}.inactive"),
            "attention_required": strict_count(
                row.get("attention_required"),
                field_name=f"channel_health.{provider}.attention_required",
            ),
            "by_connection_status": strict_count_map(
                row.get("by_connection_status"),
                field_name=f"channel_health.{provider}.by_connection_status",
                allowed_keys=platform_monitoring_repository.CHANNEL_CONNECTION_STATUSES,
            ),
        }
    if set(channel_health) - {"telegram", "wasender", "meta_whatsapp"}:
        raise RuntimeError("Unexpected channel provider")
    return {
        "messages_by_delivery_status": strict_count_map(
            value.get("messages_by_delivery_status"),
            field_name="messaging.messages_by_delivery_status",
            allowed_keys=platform_monitoring_repository.MESSAGE_DELIVERY_STATUSES,
        ),
        "retry_backlog_count": strict_count(
            value.get("retry_backlog_count"), field_name="messaging.retry_backlog_count"
        ),
        "channel_health": safe_channels,
        "broadcast_campaigns_by_status": strict_count_map(
            value.get("broadcast_campaigns_by_status"),
            field_name="messaging.broadcast_campaigns_by_status",
            allowed_keys=platform_monitoring_repository.BROADCAST_CAMPAIGN_STATUSES,
        ),
        "broadcast_recipients_by_status": strict_count_map(
            value.get("broadcast_recipients_by_status"),
            field_name="messaging.broadcast_recipients_by_status",
            allowed_keys=platform_monitoring_repository.BROADCAST_RECIPIENT_STATUSES,
        ),
    }


def _safe_billing_attention(value, strict_count, strict_count_map):
    if not isinstance(value, dict):
        raise RuntimeError("Malformed billing monitoring")
    return {
        "orders_by_status": strict_count_map(
            value.get("orders_by_status"),
            field_name="billing_attention.orders_by_status",
            allowed_keys=platform_monitoring_repository.BILLING_ORDER_STATUSES,
        ),
        "pending_order_count": strict_count(
            value.get("pending_order_count"), field_name="billing_attention.pending_order_count"
        ),
        "failed_order_count": strict_count(
            value.get("failed_order_count"), field_name="billing_attention.failed_order_count"
        ),
        "reconciliation_required_count": strict_count(
            value.get("reconciliation_required_count"),
            field_name="billing_attention.reconciliation_required_count",
        ),
        "activation_statuses": strict_count_map(
            value.get("activation_statuses"),
            field_name="billing_attention.activation_statuses",
            allowed_keys=platform_monitoring_repository.BILLING_ACTIVATION_STATUSES,
        ),
        "activation_status_unset_count": strict_count(
            value.get("activation_status_unset_count"),
            field_name="billing_attention.activation_status_unset_count",
        ),
    }


def _safe_ai_usage_monitoring(value, strict_count, strict_count_map, strict_window):
    if not isinstance(value, dict):
        raise RuntimeError("Malformed AI monitoring")
    return {
        "window": strict_window(
            value.get("window"),
            days=platform_monitoring_repository.AI_USAGE_WINDOW_DAYS,
        ),
        "requests_by_status": strict_count_map(
            value.get("requests_by_status"),
            field_name="ai_usage.requests_by_status",
            allowed_keys=platform_monitoring_repository.AI_REQUEST_STATUSES,
        ),
        "recent_request_count": strict_count(
            value.get("recent_request_count"), field_name="ai_usage.recent_request_count"
        ),
        "recent_total_tokens": strict_count(
            value.get("recent_total_tokens"), field_name="ai_usage.recent_total_tokens"
        ),
        "credit_transactions_by_type": strict_count_map(
            value.get("credit_transactions_by_type"),
            field_name="ai_usage.credit_transactions_by_type",
            allowed_keys=platform_monitoring_repository.AI_CREDIT_TRANSACTION_TYPES,
        ),
        "depleted_balance_company_count": strict_count(
            value.get("depleted_balance_company_count"),
            field_name="ai_usage.depleted_balance_company_count",
        ),
    }


def _safe_platform_activity_monitoring(value, strict_count, strict_count_map, strict_window):
    if not isinstance(value, dict):
        raise RuntimeError("Malformed activity monitoring")
    return {
        "window": strict_window(
            value.get("window"),
            days=platform_monitoring_repository.AUDIT_ACTIVITY_WINDOW_DAYS,
        ),
        "recent_event_count": strict_count(
            value.get("recent_event_count"), field_name="platform_admin_activity.recent_event_count"
        ),
        "events_by_action": strict_count_map(
            value.get("events_by_action"),
            field_name="platform_admin_activity.events_by_action",
            allowed_keys=platform_admin_repository.AUDIT_EVENT_SCHEMAS.keys(),
        ),
        "events_by_resource_type": strict_count_map(
            value.get("events_by_resource_type"),
            field_name="platform_admin_activity.events_by_resource_type",
            allowed_keys=platform_admin_repository.ALLOWED_RESOURCE_TYPES,
        ),
    }


def _phase6_operational_alerts(*, support_monitoring, messaging_monitoring, billing_attention, ai_usage):
    candidates = [
        (
            support_monitoring["open_case_count"],
            {
                "type": "support_backlog",
                "severity": "info",
                "summary": "Open support cases require review",
                "details": {"count": support_monitoring["open_case_count"]},
                "investigation_url": "platform-admin-support.html",
            },
        ),
        (
            billing_attention["pending_order_count"],
            {
                "type": "billing_orders_pending",
                "severity": "warning",
                "summary": "Billing orders are pending",
                "details": {"count": billing_attention["pending_order_count"]},
                "investigation_url": "platform-admin-companies.html",
            },
        ),
        (
            billing_attention["reconciliation_required_count"],
            {
                "type": "billing_reconciliation_required",
                "severity": "critical",
                "summary": "Billing orders require reconciliation",
                "details": {"count": billing_attention["reconciliation_required_count"]},
                "investigation_url": "platform-admin-companies.html",
            },
        ),
        (
            ai_usage["depleted_balance_company_count"],
            {
                "type": "ai_credit_depleted",
                "severity": "warning",
                "summary": "Companies have depleted AI-credit balances",
                "details": {"count": ai_usage["depleted_balance_company_count"]},
                "investigation_url": "platform-admin-companies.html",
            },
        ),
        (
            messaging_monitoring["retry_backlog_count"],
            {
                "type": "messaging_retry_backlog",
                "severity": "warning",
                "summary": "Messages are waiting for retry",
                "details": {"count": messaging_monitoring["retry_backlog_count"]},
                "investigation_url": "platform-admin-companies.html",
            },
        ),
        (
            _inactive_or_disconnected_channel_count(messaging_monitoring["channel_health"]),
            {
                "type": "integration_channel_attention",
                "severity": "warning",
                "summary": "Configured channels are inactive or disconnected",
                "details": {
                    "count": _inactive_or_disconnected_channel_count(
                        messaging_monitoring["channel_health"]
                    )
                },
                "investigation_url": "platform-admin-companies.html",
            },
        ),
    ]
    return [alert for count, alert in candidates if count > 0]


def _inactive_or_disconnected_channel_count(channel_health):
    total = 0
    for provider in channel_health.values():
        total += provider.get("attention_required", 0)
    return total


def list_companies(actor_id, *, limit=None, offset=None, search=None, status=None,
                   sort_by=None, sort_order=None):
    actor_id = _validated_actor_id(actor_id)
    limit = _integer_parameter(limit, name="limit", default=25, minimum=1, maximum=100)
    offset = _integer_parameter(offset, name="offset", default=0, minimum=0)
    normalized_search = None
    if search is not None:
        if not isinstance(search, str):
            _validation("invalid_search", "search must be text.")
        normalized_search = search.strip()
        if not 1 <= len(normalized_search) <= 100:
            _validation("invalid_search", "search must contain 1 to 100 characters.")
    normalized_status = status.strip().lower() if isinstance(status, str) else status
    if normalized_status not in {None, "active", "inactive"}:
        _validation("invalid_status", "status must be active or inactive.")
    sort_by = "created_at" if sort_by is None else sort_by.strip().lower()
    sort_order = "desc" if sort_order is None else sort_order.strip().lower()
    if sort_by not in platform_company_repository.ALLOWED_SORT_FIELDS:
        _validation("invalid_sort_by", "Unsupported sort field.")
    if sort_order not in platform_company_repository.ALLOWED_SORT_ORDERS:
        _validation("invalid_sort_order", "Sort order must be asc or desc.")
    try:
        companies, total = platform_company_repository.list_companies_for_platform_admin(
            limit=limit, offset=offset, search=normalized_search, status=normalized_status,
            sort_by=sort_by, sort_order=sort_order,
        )
    except Exception:
        logger.error("Platform company listing failed")
        _data_unavailable()
    result = {
        "companies": companies,
        "pagination": {
            "limit": limit, "offset": offset, "returned": len(companies), "total": total,
            "has_more": offset + len(companies) < total,
        },
        "sort": {"by": sort_by, "order": sort_order},
        "filters": {"search": normalized_search, "status": normalized_status},
    }
    _audit(actor_id, "platform_admin.company.list", "company", None, {
        "outcome": "success",
        "endpoint": platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["company_list"],
        "http_method": "GET", "limit": limit, "offset": offset,
        "sort_by": sort_by, "sort_order": sort_order,
        "search_applied": normalized_search is not None,
        "status_filter": normalized_status, "returned_count": len(companies),
    })
    return result


def get_company_detail(company_id, actor_id):
    actor_id = _validated_actor_id(actor_id)
    endpoint = platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["company_detail"]
    company = _company_or_not_found(
        company_id, actor_id, "platform_admin.company.read", "company", endpoint
    )
    _audit(actor_id, "platform_admin.company.read", "company", str(company_id), {
        "outcome": "success", "endpoint": endpoint, "http_method": "GET",
    })
    return company


def get_company_subscription(company_id, actor_id):
    actor_id = _validated_actor_id(actor_id)
    endpoint = platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["company_subscription"]
    company = _company_or_not_found(
        company_id, actor_id, "platform_admin.company.subscription.read",
        "company_subscription", endpoint,
    )
    try:
        subscription = platform_billing_repository.get_subscription_summary_for_platform_admin(company_id)
    except Exception:
        logger.error("Platform subscription lookup failed")
        _data_unavailable()
    result = {"company": company, "subscription": subscription}
    _audit(actor_id, "platform_admin.company.subscription.read", "company_subscription", str(company_id), {
        "outcome": "success", "endpoint": endpoint, "http_method": "GET",
    })
    return result


def _parse_period(value):
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def get_company_ai_credit_usage(company_id, actor_id):
    actor_id = _validated_actor_id(actor_id)
    endpoint = platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["company_ai_credit_usage"]
    company = _company_or_not_found(
        company_id, actor_id, "platform_admin.company.ai_credit_usage.read",
        "company_ai_credit_usage", endpoint,
    )
    try:
        subscription = platform_billing_repository.get_subscription_summary_for_platform_admin(company_id)
        balance = platform_billing_repository.get_ai_credit_balance_for_platform_admin(company_id)
    except Exception:
        logger.error("Platform AI-credit summary lookup failed")
        _data_unavailable()
    balance_start = _parse_period((balance or {}).get("period_start"))
    balance_end = _parse_period((balance or {}).get("period_end"))
    subscription_start = _parse_period((subscription or {}).get("current_period_start"))
    subscription_end = _parse_period((subscription or {}).get("current_period_end"))
    if balance_start and balance_end and balance_start < balance_end:
        period_start, period_end = balance_start, balance_end
    elif subscription_start and subscription_end and subscription_start < subscription_end:
        period_start, period_end = subscription_start, subscription_end
    else:
        period_start, period_end = None, None
    usage = {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0,
             "total_tokens": 0, "provider_cost_micro_usd": 0}
    charges = {"transaction_count": 0, "customer_charge_micro_myr": 0,
               "uncovered_charge_micro_myr": 0, "provider_cost_micro_usd": 0}
    if period_start and period_end:
        try:
            usage = platform_billing_repository.get_ai_usage_summary_for_platform_admin(
                company_id, period_start, period_end
            )
            charges = platform_billing_repository.get_ai_credit_charge_summary_for_platform_admin(
                company_id, period_start, period_end
            )
        except Exception:
            logger.error("Platform AI usage aggregation failed")
            _data_unavailable()
    credit_balance = {
        "initialized": balance is not None,
        "included_balance_micro_myr": int((balance or {}).get("included_balance_micro_myr") or 0),
        "topup_balance_micro_myr": int((balance or {}).get("topup_balance_micro_myr") or 0),
    }
    credit_balance["total_balance_micro_myr"] = (
        credit_balance["included_balance_micro_myr"] + credit_balance["topup_balance_micro_myr"]
    )
    result = {
        "company": company,
        "period": {
            "start": period_start.isoformat() if period_start else None,
            "end": period_end.isoformat() if period_end else None,
        },
        "credit_balance": credit_balance,
        "usage": usage,
        "charges": charges,
    }
    _audit(actor_id, "platform_admin.company.ai_credit_usage.read", "company_ai_credit_usage", str(company_id), {
        "outcome": "success", "endpoint": endpoint, "http_method": "GET",
        "period_start": result["period"]["start"], "period_end": result["period"]["end"],
    })
    return result


def _list_search_parameter(search):
    if search is None:
        return None
    if not isinstance(search, str):
        _validation("invalid_search", "search must be text.")
    normalized_search = search.strip()
    if not 1 <= len(normalized_search) <= 100:
        _validation("invalid_search", "search must contain 1 to 100 characters.")
    return normalized_search


def get_company_users(company_id, actor_id, *, limit=None, offset=None,
                      search=None, sort_by=None, sort_order=None):
    actor_id = _validated_actor_id(actor_id)
    endpoint = platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["company_users"]
    _positive_id(company_id)
    limit = _integer_parameter(limit, name="limit", default=25, minimum=1, maximum=100)
    offset = _integer_parameter(offset, name="offset", default=0, minimum=0)
    normalized_search = _list_search_parameter(search)
    sort_by = "created_at" if sort_by is None else sort_by.strip().lower()
    sort_order = "desc" if sort_order is None else sort_order.strip().lower()
    if sort_by not in platform_company_user_repository.ALLOWED_SORT_FIELDS:
        _validation("invalid_sort_by", "Unsupported sort field.")
    if sort_order not in platform_company_user_repository.ALLOWED_SORT_ORDERS:
        _validation("invalid_sort_order", "Sort order must be asc or desc.")
    _company_or_not_found(
        company_id, actor_id, "platform_admin.company.users.read",
        "company_users", endpoint,
    )
    try:
        users, total = platform_company_user_repository.list_company_users_for_platform_admin(
            company_id=company_id, limit=limit, offset=offset,
            search=normalized_search, sort_by=sort_by, sort_order=sort_order,
        )
    except Exception:
        logger.error("Platform company-user listing failed")
        _data_unavailable()
    result = {
        "users": users,
        "pagination": {
            "limit": limit, "offset": offset, "returned": len(users), "total": total,
            "has_more": offset + len(users) < total,
        },
        "sort": {"by": sort_by, "order": sort_order},
        "filters": {"search_applied": normalized_search is not None},
    }
    _audit(actor_id, "platform_admin.company.users.read", "company_users", str(company_id), {
        "outcome": "success", "endpoint": endpoint, "http_method": "GET",
        "limit": limit, "offset": offset, "sort_by": sort_by,
        "sort_order": sort_order, "search_applied": normalized_search is not None,
        "returned_count": len(users),
    })
    return result


def get_company_chatbots(company_id, actor_id, *, limit=None, offset=None,
                         search=None, state=None, sort_by=None, sort_order=None):
    actor_id = _validated_actor_id(actor_id)
    endpoint = platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["company_chatbots"]
    _positive_id(company_id)
    limit = _integer_parameter(limit, name="limit", default=25, minimum=1, maximum=100)
    offset = _integer_parameter(offset, name="offset", default=0, minimum=0)
    normalized_search = _list_search_parameter(search)
    normalized_state = "current" if state is None else state.strip().lower() if isinstance(state, str) else state
    if normalized_state not in platform_chatbot_repository.ALLOWED_STATES:
        _validation("invalid_state", "state must be current, archived, or all.")
    sort_by = "created_at" if sort_by is None else sort_by.strip().lower()
    sort_order = "desc" if sort_order is None else sort_order.strip().lower()
    if sort_by not in platform_chatbot_repository.ALLOWED_SORT_FIELDS:
        _validation("invalid_sort_by", "Unsupported sort field.")
    if sort_order not in platform_chatbot_repository.ALLOWED_SORT_ORDERS:
        _validation("invalid_sort_order", "Sort order must be asc or desc.")
    _company_or_not_found(
        company_id, actor_id, "platform_admin.company.chatbots.read",
        "company_chatbots", endpoint,
    )
    try:
        chatbots, total = platform_chatbot_repository.list_company_chatbots_for_platform_admin(
            company_id=company_id, limit=limit, offset=offset,
            search=normalized_search, state=normalized_state,
            sort_by=sort_by, sort_order=sort_order,
        )
    except Exception:
        logger.error("Platform company-chatbot listing failed")
        _data_unavailable()
    result = {
        "chatbots": chatbots,
        "pagination": {
            "limit": limit, "offset": offset, "returned": len(chatbots), "total": total,
            "has_more": offset + len(chatbots) < total,
        },
        "sort": {"by": sort_by, "order": sort_order},
        "filters": {
            "search_applied": normalized_search is not None,
            "state": normalized_state,
        },
    }
    _audit(actor_id, "platform_admin.company.chatbots.read", "company_chatbots", str(company_id), {
        "outcome": "success", "endpoint": endpoint, "http_method": "GET",
        "limit": limit, "offset": offset, "sort_by": sort_by,
        "sort_order": sort_order, "search_applied": normalized_search is not None,
        "state_filter": normalized_state, "returned_count": len(chatbots),
    })
    return result


def _safe_subscription_history_response_row(row):
    if not isinstance(row, dict):
        row = {}

    def safe_plan(value):
        if not isinstance(value, dict):
            return None
        return {
            "code": value.get("code"),
            "name": value.get("name"),
        }

    return {
        "id": row.get("id"),
        "status": row.get("status"),
        "plan": safe_plan(row.get("plan")),
        "pending_plan": safe_plan(row.get("pending_plan")),
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


def get_company_subscription_history(company_id, actor_id, *, limit=None, offset=None,
                                     status=None):
    actor_id = _validated_actor_id(actor_id)
    endpoint = platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["company_subscription_history"]
    _positive_id(company_id)
    limit = _integer_parameter(limit, name="limit", default=25, minimum=1, maximum=100)
    offset = _integer_parameter(offset, name="offset", default=0, minimum=0)
    normalized_status = status.strip().lower() if isinstance(status, str) else status
    if normalized_status not in platform_billing_repository.SUBSCRIPTION_HISTORY_STATUSES | {None}:
        _validation("invalid_status", "status must be trialing, active, past_due, expired, or cancelled.")
    _company_or_not_found(
        company_id, actor_id, "platform_admin.company.subscription_history.read",
        "company_subscription_history", endpoint,
    )
    try:
        subscriptions, total = platform_billing_repository.list_subscription_history_for_platform_admin(
            company_id=company_id, limit=limit, offset=offset, status=normalized_status,
        )
    except Exception:
        logger.error("Platform subscription history lookup failed")
        _data_unavailable()
    result = {
        "subscriptions": [
            _safe_subscription_history_response_row(row) for row in (subscriptions or [])
        ],
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(subscriptions or []),
            "total": total,
            "has_more": offset + len(subscriptions or []) < total,
        },
        "filters": {
            "status": normalized_status,
            "status_applied": normalized_status is not None,
        },
        "ordering": {
            "by": "created_at",
            "order": "desc",
            "tie_breaker": "id desc",
        },
    }
    _audit(actor_id, "platform_admin.company.subscription_history.read",
           "company_subscription_history", str(company_id), {
               "outcome": "success",
               "endpoint": endpoint,
               "http_method": "GET",
               "limit": limit,
               "offset": offset,
               "status_filter": normalized_status,
               "returned_count": len(subscriptions or []),
           })
    return result


def _safe_ai_credit_transaction_response_row(row):
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


def get_company_ai_credit_transactions(
    company_id, actor_id, *, limit=None, offset=None, transaction_type=None
):
    actor_id = _validated_actor_id(actor_id)
    endpoint = platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["company_ai_credit_transactions"]
    _positive_id(company_id)
    limit = _integer_parameter(limit, name="limit", default=25, minimum=1, maximum=100)
    offset = _integer_parameter(offset, name="offset", default=0, minimum=0)
    normalized_type = transaction_type
    if isinstance(transaction_type, str):
        normalized_type = transaction_type.strip().lower()
        if normalized_type == "":
            _validation("invalid_transaction_type", "transaction_type is not supported.")
    if normalized_type not in platform_billing_repository.AI_CREDIT_TRANSACTION_TYPES | {None}:
        _validation("invalid_transaction_type", "transaction_type is not supported.")
    _company_or_not_found(
        company_id, actor_id, "platform_admin.company.ai_credit_transactions.read",
        "company_ai_credit_transactions", endpoint,
    )
    try:
        transactions, total = platform_billing_repository.list_ai_credit_transactions_for_platform_admin(
            company_id=company_id,
            limit=limit,
            offset=offset,
            transaction_type=normalized_type,
        )
    except Exception:
        logger.error("Platform AI-credit transaction history lookup failed")
        _data_unavailable()

    safe_transactions = [
        _safe_ai_credit_transaction_response_row(row) for row in (transactions or [])
    ]
    result = {
        "transactions": safe_transactions,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(safe_transactions),
            "total": int(total or 0),
            "has_more": offset + len(safe_transactions) < int(total or 0),
        },
        "filters": {
            "transaction_type": normalized_type,
        },
        "ordering": {
            "by": "created_at",
            "order": "desc",
            "tie_breaker": "id desc",
        },
    }
    _audit(actor_id, "platform_admin.company.ai_credit_transactions.read",
           "company_ai_credit_transactions", str(company_id), {
               "outcome": "success",
               "endpoint": endpoint,
               "http_method": "GET",
               "limit": limit,
               "offset": offset,
               "transaction_type_filter": normalized_type,
               "returned_count": len(safe_transactions),
           })
    return result


def _safe_billing_order_plan(plan):
    if not isinstance(plan, dict):
        return None
    return {
        "code": plan.get("code"),
        "name": plan.get("name"),
    }


def _safe_billing_order_response_row(row):
    if not isinstance(row, dict):
        row = {}
    return {
        "id": row.get("id"),
        "status": row.get("status"),
        "amount_sen": row.get("amount_sen"),
        "new_plan": _safe_billing_order_plan(row.get("new_plan")),
        "source_plan": _safe_billing_order_plan(row.get("source_plan")),
        "activation_status": row.get("activation_status"),
        "activation_type": row.get("activation_type"),
        "reconciliation_required": row.get("reconciliation_required"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "paid_at": row.get("paid_at"),
        "credited_at": row.get("credited_at"),
        "expires_at": row.get("expires_at"),
        "activation_claimed_at": row.get("activation_claimed_at"),
        "activation_completed_at": row.get("activation_completed_at"),
        "credit_granted_at": row.get("credit_granted_at"),
    }


def get_company_billing_orders(
    company_id, actor_id, *, limit=None, offset=None, status=None,
    created_after=None, created_before=None,
):
    actor_id = _validated_actor_id(actor_id)
    endpoint = platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["company_billing_orders"]
    _positive_id(company_id)
    limit = _integer_parameter(limit, name="limit", default=25, minimum=1, maximum=100)
    offset = _integer_parameter(offset, name="offset", default=0, minimum=0)
    normalized_status = _optional_billing_status_parameter(status)
    parsed_after = _optional_datetime_parameter(created_after, name="created_after")
    parsed_before = _optional_datetime_parameter(created_before, name="created_before")
    if parsed_after is not None and parsed_before is not None and parsed_after >= parsed_before:
        _validation("invalid_created_before", "created_after must be earlier than created_before.")

    _company_or_not_found(
        company_id, actor_id, "platform_admin.company.billing_orders.read",
        "company_billing_orders", endpoint,
    )
    try:
        orders, total = platform_billing_repository.list_billing_orders_for_platform_admin(
            company_id=company_id,
            limit=limit,
            offset=offset,
            status=normalized_status,
            created_after=parsed_after,
            created_before=parsed_before,
        )
    except Exception:
        logger.error("Platform billing order history lookup failed")
        _data_unavailable()

    safe_orders = [
        _safe_billing_order_response_row(row) for row in (orders or [])
    ]
    total = int(total or 0)
    result = {
        "billing_orders": safe_orders,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(safe_orders),
            "total": total,
            "has_more": offset + len(safe_orders) < total,
        },
        "filters": {
            "status": normalized_status,
            "status_applied": normalized_status is not None,
            "created_after": parsed_after.isoformat() if parsed_after else None,
            "created_after_applied": parsed_after is not None,
            "created_before": parsed_before.isoformat() if parsed_before else None,
            "created_before_applied": parsed_before is not None,
        },
        "ordering": {
            "by": "created_at",
            "order": "desc",
            "tie_breaker": "id desc",
        },
        "amount_units": {
            "amount_sen": "integer sen as stored; currency is not returned or inferred",
        },
    }
    _audit(actor_id, "platform_admin.company.billing_orders.read",
           "company_billing_orders", str(company_id), {
               "outcome": "success",
               "endpoint": endpoint,
               "http_method": "GET",
               "limit": limit,
               "offset": offset,
               "status_filter_applied": normalized_status is not None,
               "created_after_filter_applied": parsed_after is not None,
               "created_before_filter_applied": parsed_before is not None,
               "returned_count": len(safe_orders),
           })
    return result
