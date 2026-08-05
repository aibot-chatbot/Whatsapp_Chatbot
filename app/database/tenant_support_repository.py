"""Service-role repository for tenant support requests."""

from app.database.db import supabase


REQUEST_FIELDS = (
    "id,company_id,requester_user_id,category,status,priority,source,"
    "created_at,updated_at,closed_at"
)
REQUEST_DETAIL_FIELDS = REQUEST_FIELDS + ",title,redacted_description"
EVENT_FIELDS = "event_type,actor_type,created_at"
ALLOWED_CATEGORIES = {
    "technical", "account", "chatbot", "integration", "billing_question",
    "ai_credits", "other",
}
ALLOWED_STATUSES = {"new", "reviewed", "converted", "closed"}


def _positive_id(value, field_name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _validate_page(limit, offset):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")


def create_tenant_support_request(
    *, company_id, requester_user_id, category, title, redacted_description
):
    response = supabase.rpc(
        "create_tenant_support_request",
        {
            "p_company_id": company_id,
            "p_requester_user_id": requester_user_id,
            "p_category": category,
            "p_title": title,
            "p_redacted_description": redacted_description,
        },
    ).execute()
    request_id = response.data
    if isinstance(request_id, list):
        request_id = request_id[0] if request_id else None
    if isinstance(request_id, bool) or not isinstance(request_id, int) or request_id <= 0:
        raise RuntimeError("Tenant support request RPC returned no request ID")
    return request_id


def list_tenant_support_requests_for_platform_admin(
    *, limit, offset, company_id=None, category=None, status=None
):
    _validate_page(limit, offset)
    if company_id is not None:
        _positive_id(company_id, "company_id")
    if category is not None and category not in ALLOWED_CATEGORIES:
        raise ValueError("Unsupported tenant support category")
    if status is not None and status not in ALLOWED_STATUSES:
        raise ValueError("Unsupported tenant support status")
    query = supabase.table("tenant_support_requests").select(REQUEST_FIELDS, count="exact")
    if company_id is not None:
        query = query.eq("company_id", company_id)
    if category is not None:
        query = query.eq("category", category)
    if status is not None:
        query = query.eq("status", status)
    response = query.order("created_at", desc=True).order("id", desc=True).range(
        offset, offset + limit - 1
    ).execute()
    return response.data or [], int(response.count or 0)


def get_tenant_support_request_for_platform_admin(request_id):
    _positive_id(request_id, "request_id")
    response = (
        supabase.table("tenant_support_requests")
        .select(REQUEST_DETAIL_FIELDS)
        .eq("id", request_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def list_tenant_support_request_events_for_platform_admin(request_id):
    _positive_id(request_id, "request_id")
    response = (
        supabase.table("tenant_support_request_events")
        .select(EVENT_FIELDS)
        .eq("request_id", request_id)
        .order("created_at", desc=False)
        .order("id", desc=False)
        .execute()
    )
    return response.data or []
