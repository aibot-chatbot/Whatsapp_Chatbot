"""Service-role persistence for staff grants and approval records.

Writes use transactional RPCs from migration 053. No approval executes a
payment, subscription, tenant-content or account operation.
"""

from app.database.db import supabase
from app.database.platform_billing_repository import BILLING_ORDER_HISTORY_FIELDS


REQUEST_FIELDS = (
    "id,type,company_id,summary,reason,status,requester_platform_admin_user_id,"
    "created_at,updated_at,reviewed_by_platform_admin_user_id,decision_reason,reviewed_at"
)


def list_requests(*, requester_id, limit, offset, status=None):
    query = supabase.table("platform_approval_requests").select(REQUEST_FIELDS, count="exact")
    if requester_id is not None:
        query = query.eq("requester_platform_admin_user_id", requester_id)
    if status is not None:
        query = query.eq("status", status)
    response = query.order("created_at", desc=True).order("id", desc=True).range(offset, offset + limit - 1).execute()
    return response.data or [], int(response.count or 0)


def get_request(approval_id, *, requester_id):
    query = supabase.table("platform_approval_requests").select(REQUEST_FIELDS).eq("id", approval_id)
    if requester_id is not None:
        query = query.eq("requester_platform_admin_user_id", requester_id)
    response = query.limit(1).execute()
    return (response.data or [None])[0]


def _rpc(name, params, *, key, expected_id=None):
    result = supabase.rpc(name, params).execute().data
    if not isinstance(result, dict) or not isinstance(result.get(key), dict):
        raise RuntimeError("Malformed platform staff transaction response")
    row = result[key]
    if isinstance(row.get("id"), bool) or not isinstance(row.get("id"), int) or row["id"] <= 0:
        raise RuntimeError("Malformed platform staff transaction identity")
    if expected_id is not None and row["id"] != expected_id:
        raise RuntimeError("Platform staff transaction identity mismatch")
    audit = result.get("audit_event")
    if (not isinstance(audit, dict) or type(audit.get("id")) is not int or audit["id"] <= 0
            or audit.get("platform_admin_user_id") != params["p_actor_platform_admin_user_id"]
            or audit.get("resource_id") != str(row["id"])):
        raise RuntimeError("Missing platform staff transaction audit")
    return row


def create_request(actor_id, *, request_type, company_id, summary, reason):
    return _rpc("create_platform_approval_request", {
        "p_actor_platform_admin_user_id": actor_id, "p_type": request_type,
        "p_company_id": company_id, "p_summary": summary, "p_reason": reason,
    }, key="request")


def decide_request(actor_id, approval_id, *, status, reason):
    return _rpc("decide_platform_approval_request", {
        "p_actor_platform_admin_user_id": actor_id, "p_request_id": approval_id,
        "p_status": status, "p_reason": reason,
    }, key="request", expected_id=approval_id)


def set_access(actor_id, mapping_id, *, platform_role, modules, reason):
    return _rpc("set_platform_staff_access", {
        "p_actor_platform_admin_user_id": actor_id,
        "p_target_platform_admin_user_id": mapping_id,
        "p_platform_role": platform_role, "p_modules": modules,
        "p_reason": reason, "p_is_active": None,
    }, key="platform_admin_user", expected_id=mapping_id)


def audit_read(actor_id, *, action, resource_type, resource_id, endpoint, method="GET", outcome="success"):
    # All values are selected by the service; no request bodies enter audit metadata.
    response = supabase.table("platform_admin_audit_events").insert({
        "platform_admin_user_id": actor_id, "action": action,
        "resource_type": resource_type, "resource_id": str(resource_id) if resource_id is not None else None,
        "metadata": {"outcome": outcome, "endpoint": endpoint, "http_method": method},
    }).execute()
    if not response.data:
        raise RuntimeError("Platform audit was not persisted")


def get_stored_billing_order(company_id, order_id):
    response = (supabase.table("company_subscription_orders").select(
                    BILLING_ORDER_HISTORY_FIELDS + ",company_id,order_reference,payment_gateway")
                .eq("company_id", company_id).eq("id", order_id).limit(1).execute())
    return (response.data or [None])[0]


def get_staff_mapping(mapping_id):
    response = (supabase.table("platform_admin_users")
                .select("id,user_id,is_active,platform_role,modules")
                .eq("id", mapping_id).limit(1).execute())
    rows = _active_user_mappings(response.data or [])
    return rows[0] if rows else None


def _active_user_mappings(rows):
    ids = sorted({row["user_id"] for row in rows if type(row.get("user_id")) is int and row["user_id"] > 0})
    if not ids:
        return []
    response = supabase.table("users").select("id").in_("id", ids).eq("status", "active").execute()
    active_ids = {row.get("id") for row in response.data or []}
    return [row for row in rows if row.get("user_id") in active_ids]


def support_staff_ids():
    # Bounded to staff mappings, never tenant users or tenant content.
    response = (supabase.table("platform_admin_users").select("id,user_id,is_active,platform_role,modules")
                .eq("is_active", True).execute())
    return _active_user_mappings(response.data or [])
