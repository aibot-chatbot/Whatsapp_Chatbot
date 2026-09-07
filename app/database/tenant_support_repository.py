"""Service-role repository for tenant support requests."""

from app.database.db import supabase


REQUEST_FIELDS = (
    "id,company_id,requester_user_id,category,status,priority,source,"
    "created_at,updated_at,closed_at"
)
REQUEST_DETAIL_FIELDS = REQUEST_FIELDS + ",title,redacted_description"
EVENT_FIELDS = "event_type,actor_type,created_at"
TENANT_REPLY_FIELDS = (
    "id,request_id,company_id,author_type,redacted_body,visibility_status,created_at"
)
ALLOWED_CATEGORIES = {
    "technical", "account", "chatbot", "integration", "billing_question",
    "ai_credits", "other",
}
ALLOWED_STATUSES = {"new", "reviewed", "converted", "closed"}
REVIEW_CONVERSION_STATUSES = {"reviewed", "closed", "converted"}


def _positive_id(value, field_name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _validate_page(limit, offset):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")


def create_tenant_support_request(
    *,
    company_id,
    requester_user_id,
    category,
    title,
    redacted_description,
    priority,
    source,
    escalation_context,
):
    """One RPC call, one transaction: request + event + audit row together.

    priority, source and escalation_context are carried by the RPC rather than
    written by a follow-up UPDATE, because a second statement can fail on its
    own and leave a ticket whose urgency and trail are silently missing. This
    requires migration 052; the pre-052 function has five parameters and will
    reject these three.
    """
    response = supabase.rpc(
        "create_tenant_support_request",
        {
            "p_company_id": company_id,
            "p_requester_user_id": requester_user_id,
            "p_category": category,
            "p_title": title,
            "p_redacted_description": redacted_description,
            "p_priority": priority,
            "p_source": source,
            "p_escalation_context": escalation_context,
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
        .select(REQUEST_DETAIL_FIELDS + ",escalation_context")
        .eq("id", request_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def get_tenant_support_request_by_converted_case_id_for_platform_admin(case_id):
    _positive_id(case_id, "case_id")
    response = (
        supabase.table("tenant_support_requests")
        .select(REQUEST_FIELDS + ",converted_platform_support_case_id,escalation_context")
        .eq("converted_platform_support_case_id", case_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def list_tenant_support_requests_for_tenant(*, company_id, requester_user_id, limit, offset):
    _positive_id(company_id, "company_id")
    _positive_id(requester_user_id, "requester_user_id")
    _validate_page(limit, offset)
    response = (
        supabase.table("tenant_support_requests")
        .select(REQUEST_FIELDS, count="exact")
        .eq("company_id", company_id)
        .eq("requester_user_id", requester_user_id)
        .order("created_at", desc=True)
        .order("id", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return response.data or [], int(response.count or 0)


def get_tenant_support_request_for_tenant(request_id, *, company_id, requester_user_id):
    _positive_id(request_id, "request_id")
    _positive_id(company_id, "company_id")
    _positive_id(requester_user_id, "requester_user_id")
    response = (
        supabase.table("tenant_support_requests")
        .select(REQUEST_DETAIL_FIELDS)
        .eq("id", request_id)
        .eq("company_id", company_id)
        .eq("requester_user_id", requester_user_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def list_tenant_support_replies_for_tenant(request_id, *, company_id):
    _positive_id(request_id, "request_id")
    _positive_id(company_id, "company_id")
    response = (
        supabase.table("tenant_support_replies")
        .select(TENANT_REPLY_FIELDS)
        .eq("request_id", request_id)
        .eq("company_id", company_id)
        .eq("visibility_status", "visible")
        .order("created_at", desc=False)
        .order("id", desc=False)
        .execute()
    )
    return response.data or []


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


def _rpc_object(response, function_name):
    value = response.data
    if isinstance(value, list):
        value = value[0] if len(value) == 1 else None
    if not isinstance(value, dict):
        raise RuntimeError(f"{function_name} RPC returned an invalid result")
    return value


def _validate_status_rpc_result(result, function_name):
    request_id = result.get("request_id")
    status = result.get("status")
    if isinstance(request_id, bool) or not isinstance(request_id, int) or request_id <= 0:
        raise RuntimeError(f"{function_name} RPC returned an invalid request ID")
    if status not in {"reviewed", "closed"}:
        raise RuntimeError(f"{function_name} RPC returned an invalid status")
    for key in ("old_status", "new_status"):
        if key in result and result[key] not in ALLOWED_STATUSES:
            raise RuntimeError(f"{function_name} RPC returned an invalid status field")
    return result


def set_tenant_support_request_status_for_platform_admin(
    request_id, platform_admin_user_id, status
):
    _positive_id(request_id, "request_id")
    _positive_id(platform_admin_user_id, "platform_admin_user_id")
    if status not in {"reviewed", "closed"}:
        raise ValueError("Unsupported tenant support request status")
    response = supabase.rpc(
        "set_tenant_support_request_status",
        {
            "p_request_id": request_id,
            "p_platform_admin_user_id": platform_admin_user_id,
            "p_status": status,
        },
    ).execute()
    return _validate_status_rpc_result(
        _rpc_object(response, "set_tenant_support_request_status"),
        "set_tenant_support_request_status",
    )


def convert_tenant_support_request_for_platform_admin(
    request_id, platform_admin_user_id
):
    _positive_id(request_id, "request_id")
    _positive_id(platform_admin_user_id, "platform_admin_user_id")
    result = _rpc_object(
        supabase.rpc(
            "convert_tenant_support_request",
            {
                "p_request_id": request_id,
                "p_platform_admin_user_id": platform_admin_user_id,
            },
        ).execute(),
        "convert_tenant_support_request",
    )
    returned_request_id = result.get("request_id")
    if (
        isinstance(returned_request_id, bool)
        or not isinstance(returned_request_id, int)
        or returned_request_id <= 0
        or returned_request_id != request_id
    ):
        raise RuntimeError("convert_tenant_support_request RPC returned an invalid request ID")
    if result.get("status") != "converted":
        raise RuntimeError("convert_tenant_support_request RPC returned an invalid status")
    case_id = result.get("converted_platform_support_case_id")
    if isinstance(case_id, bool) or not isinstance(case_id, int) or case_id <= 0:
        raise RuntimeError(
            "convert_tenant_support_request RPC returned an invalid case ID"
        )
    return result
