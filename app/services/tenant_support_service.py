"""Validation and orchestration for tenant support request submission."""

import logging

from app.database import tenant_support_repository


logger = logging.getLogger(__name__)


class TenantSupportServiceError(Exception):
    def __init__(self, status_code, code, message):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


ALLOWED_CATEGORIES = frozenset({
    "technical",
    "account",
    "chatbot",
    "integration",
    "billing_question",
    "ai_credits",
    "other",
})
ALLOWED_FIELDS = frozenset({"category", "title", "redacted_description"})
FORBIDDEN_TERMS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
    "provider payload",
    "payment reference",
    "payment_reference",
    "checkout",
    "gateway",
    "impersonat",
    "customer message",
    "conversation content",
)


def _validation(code, message):
    raise TenantSupportServiceError(400, code, message)


def _positive_context_id(value, field_name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TenantSupportServiceError(
            500,
            "authentication_context_invalid",
            f"Authenticated {field_name} context is invalid.",
        )
    return value


def _positive_request_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TenantSupportServiceError(
            400, "invalid_request_id", "Request ID must be a positive integer."
        )
    return value


def _integer_parameter(value, *, name, default, minimum, maximum=None):
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise TenantSupportServiceError(400, f"invalid_{name}", f"{name} must be an integer.")
    if parsed < minimum or (maximum is not None and parsed > maximum):
        bounds = f"between {minimum} and {maximum}" if maximum is not None else f"at least {minimum}"
        raise TenantSupportServiceError(400, f"invalid_{name}", f"{name} must be {bounds}.")
    return parsed


def _safe_text(value, *, field_name, maximum):
    if not isinstance(value, str):
        _validation(f"invalid_{field_name}", f"{field_name} must be text.")
    normalized = value.strip()
    if not 1 <= len(normalized) <= maximum:
        _validation(
            f"invalid_{field_name}",
            f"{field_name} must contain 1 to {maximum} characters.",
        )
    if any(term in normalized.casefold() for term in FORBIDDEN_TERMS):
        _validation(
            f"invalid_{field_name}",
            f"{field_name} contains unsupported sensitive content.",
        )
    return normalized


def submit_tenant_support_request(payload, *, company_id, requester_user_id):
    company_id = _positive_context_id(company_id, "company")
    requester_user_id = _positive_context_id(requester_user_id, "requester")
    if not isinstance(payload, dict):
        _validation("invalid_request", "Request body must be an object.")

    unsupported = set(payload) - ALLOWED_FIELDS
    if unsupported:
        _validation("unsupported_field", "Request contains unsupported fields.")

    category = payload.get("category")
    if not isinstance(category, str) or category.strip() not in ALLOWED_CATEGORIES:
        _validation("invalid_category", "Unsupported support category.")
    category = category.strip()
    title = _safe_text(payload.get("title"), field_name="title", maximum=160)
    description = _safe_text(
        payload.get("redacted_description"),
        field_name="redacted_description",
        maximum=2000,
    )

    try:
        request_id = tenant_support_repository.create_tenant_support_request(
            company_id=company_id,
            requester_user_id=requester_user_id,
            category=category,
            title=title,
            redacted_description=description,
        )
    except Exception:
        logger.error("Tenant support request RPC failed")
        raise TenantSupportServiceError(
            503,
            "tenant_support_unavailable",
            "Support request submission is temporarily unavailable.",
        )

    return {"request_id": request_id}


def _safe_tenant_request(row, *, include_content=False):
    if not isinstance(row, dict):
        row = {}
    safe = {
        "request_id": row.get("id"),
        "category": row.get("category"),
        "status": row.get("status"),
        "source": row.get("source"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "closed_at": row.get("closed_at"),
    }
    if include_content:
        safe["title"] = row.get("title")
        safe["redacted_description"] = row.get("redacted_description")
    return safe


def _safe_tenant_reply(row):
    if not isinstance(row, dict):
        row = {}
    return {
        "reply_id": row.get("id"),
        "request_id": row.get("request_id"),
        "author_type": row.get("author_type"),
        "redacted_body": row.get("redacted_body"),
        "created_at": row.get("created_at"),
    }


def list_tenant_support_requests(*, company_id, requester_user_id, limit=None, offset=None):
    company_id = _positive_context_id(company_id, "company")
    requester_user_id = _positive_context_id(requester_user_id, "requester")
    limit = _integer_parameter(limit, name="limit", default=25, minimum=1, maximum=100)
    offset = _integer_parameter(offset, name="offset", default=0, minimum=0)
    try:
        rows, total = tenant_support_repository.list_tenant_support_requests_for_tenant(
            company_id=company_id,
            requester_user_id=requester_user_id,
            limit=limit,
            offset=offset,
        )
    except Exception:
        logger.error("Tenant support request history lookup failed")
        raise TenantSupportServiceError(
            503,
            "tenant_support_unavailable",
            "Support request history is temporarily unavailable.",
        )
    return {
        "requests": [_safe_tenant_request(row) for row in rows],
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(rows),
            "total": total,
            "has_more": offset + len(rows) < total,
        },
    }


def get_tenant_support_request(request_id, *, company_id, requester_user_id):
    request_id = _positive_request_id(request_id)
    company_id = _positive_context_id(company_id, "company")
    requester_user_id = _positive_context_id(requester_user_id, "requester")
    try:
        row = tenant_support_repository.get_tenant_support_request_for_tenant(
            request_id,
            company_id=company_id,
            requester_user_id=requester_user_id,
        )
    except Exception:
        logger.error("Tenant support request detail lookup failed")
        raise TenantSupportServiceError(
            503,
            "tenant_support_unavailable",
            "Support request detail is temporarily unavailable.",
        )
    if not row:
        raise TenantSupportServiceError(
            404, "tenant_support_request_not_found", "Support request not found."
        )
    try:
        replies = tenant_support_repository.list_tenant_support_replies_for_tenant(
            request_id, company_id=company_id
        )
    except Exception:
        logger.error("Tenant support reply lookup failed")
        raise TenantSupportServiceError(
            503,
            "tenant_support_unavailable",
            "Support conversation is temporarily unavailable.",
        )
    return {
        "request": _safe_tenant_request(row, include_content=True),
        "replies": [_safe_tenant_reply(reply) for reply in replies],
    }
