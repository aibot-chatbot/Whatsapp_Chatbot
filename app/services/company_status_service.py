"""Authoritative company operational-status checks."""

from functools import wraps
import logging

from flask import g, jsonify

from app.database.company_repository import get_company_status_by_id


logger = logging.getLogger(__name__)


# Exact non-operational exceptions; new authenticated writes default to guarded.
NON_OPERATIONAL_ENDPOINTS = frozenset({
    "support.submit_support_request",
    "help.record_help_article_feedback",
    "billing.mark_billing_notification_read",
    "billing.mark_all_billing_notifications_read",
})


def requires_company_operational_state(method, blueprint, endpoint):
    """Keep platform authority separate; preserve tenant help while suspended."""
    return (
        method not in ("GET", "HEAD", "OPTIONS")
        and blueprint != "platform_admin"
        and endpoint not in NON_OPERATIONAL_ENDPOINTS
    )


class CompanyOperationalStatusError(Exception):
    def __init__(self, code, message, status_code=403):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _positive_company_id(company_id):
    if isinstance(company_id, bool) or not isinstance(company_id, int) or company_id <= 0:
        raise CompanyOperationalStatusError(
            "company_context_invalid",
            "Unable to validate company access.",
            status_code=503,
        )
    return company_id


def ensure_company_operational(company_id):
    """Require the server-resolved company to be active for tenant operations."""
    company_id = _positive_company_id(company_id)
    try:
        row = get_company_status_by_id(company_id)
    except Exception:
        logger.error("Company status lookup failed")
        raise CompanyOperationalStatusError(
            "company_status_unavailable",
            "Company access is temporarily unavailable.",
            status_code=503,
        )

    status = (row or {}).get("status")
    if not row:
        raise CompanyOperationalStatusError(
            "company_not_found",
            "Company access could not be verified.",
            status_code=403,
        )
    if status != "active":
        raise CompanyOperationalStatusError(
            "company_suspended",
            "Company access is suspended. Support remains available.",
            status_code=403,
        )
    return row


def company_operational_required(view_function):
    @wraps(view_function)
    def decorated(*args, **kwargs):
        try:
            ensure_company_operational(getattr(g, "company_id", None))
        except CompanyOperationalStatusError as exc:
            return jsonify({
                "status": "error",
                "code": exc.code,
                "message": exc.message,
            }), exc.status_code
        return view_function(*args, **kwargs)

    return decorated
