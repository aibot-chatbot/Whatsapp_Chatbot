"""Service-role repository for tenant support request submission."""

from app.database.db import supabase


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
