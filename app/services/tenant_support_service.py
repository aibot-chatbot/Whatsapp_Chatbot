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
