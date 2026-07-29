"""Application service for the read-only platform-admin API."""

import logging
from datetime import datetime, timezone

from app.database import platform_admin_repository
from app.database import platform_billing_repository
from app.database import platform_chatbot_repository
from app.database import platform_company_repository
from app.database import platform_company_user_repository


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
        _validation(code, "Company ID must be a positive integer.")
    return value


def _validated_actor_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PlatformAdminServiceError(
            500, "platform_admin_context_invalid", "Platform context is invalid."
        )
    return value


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


def _audit(actor_id, action, resource_type, resource_id, metadata):
    try:
        platform_admin_repository.insert_platform_admin_audit_event(
            actor_id, action, resource_type, resource_id, metadata
        )
    except Exception:
        logger.error("Platform-admin audit insertion failed")
        _audit_unavailable()


def _now_utc_iso():
    return datetime.now(timezone.utc).isoformat()


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
    except Exception:
        logger.error("Platform operations overview lookup failed")
        _data_unavailable()

    def _safe_count(value):
        return int(value) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

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

    result = {
        "generated_at": generated_at,
        "companies": {
            "total": _safe_count(company_counts.get("total")),
            "active": _safe_count(company_counts.get("active")),
            "inactive": _safe_count(company_counts.get("inactive")),
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
        "attention_companies": attention,
    }
    _audit(actor_id, "platform_admin.operations.overview.read", "platform_operations_overview", None, {
        "outcome": "success",
        "endpoint": platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS["operations_overview"],
        "http_method": "GET",
        "attention_company_count": len(attention),
        "generated_at": generated_at,
    })
    return result


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
