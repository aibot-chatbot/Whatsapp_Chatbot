"""Safe Supabase projections for internal platform-admin support cases."""

from app.database.db import supabase


CASE_FIELDS = (
    "id,company_id,created_by_platform_admin_user_id,"
    "assigned_platform_admin_user_id,status,priority,title,redacted_summary,"
    "created_at,updated_at,closed_at"
)
EVENT_FIELDS = (
    "id,case_id,event_type,actor_platform_admin_user_id,old_status,new_status,"
    "old_priority,new_priority,old_assigned_platform_admin_user_id,"
    "new_assigned_platform_admin_user_id,redacted_note,created_at"
)
ALLOWED_STATUSES = {"open", "in_progress", "waiting_for_tenant", "resolved", "closed"}
ALLOWED_PRIORITIES = {"low", "normal", "high", "urgent"}
ALLOWED_LIST_SORT_FIELDS = {"created_at", "updated_at", "priority", "status", "id"}
ALLOWED_LIST_SORT_ORDERS = {"asc", "desc"}


def _positive_id(value, field_name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def list_support_cases_for_platform_admin(
    *, limit, offset, company_id=None, status=None, priority=None,
    sort_by="updated_at", sort_order="desc",
):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if company_id is not None:
        _positive_id(company_id, "company_id")
    if status is not None and status not in ALLOWED_STATUSES:
        raise ValueError("Unsupported support-case status")
    if priority is not None and priority not in ALLOWED_PRIORITIES:
        raise ValueError("Unsupported support-case priority")
    if sort_by not in ALLOWED_LIST_SORT_FIELDS or sort_order not in ALLOWED_LIST_SORT_ORDERS:
        raise ValueError("Unsupported support-case ordering")

    query = supabase.table("platform_support_cases").select(CASE_FIELDS, count="exact")
    if company_id is not None:
        query = query.eq("company_id", company_id)
    if status is not None:
        query = query.eq("status", status)
    if priority is not None:
        query = query.eq("priority", priority)
    query = query.order(sort_by, desc=sort_order == "desc").order("id", desc=True)
    response = query.range(offset, offset + limit - 1).execute()
    return response.data or [], int(response.count or 0)


def get_support_case_for_platform_admin(case_id):
    _positive_id(case_id, "case_id")
    response = (
        supabase.table("platform_support_cases")
        .select(CASE_FIELDS)
        .eq("id", case_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def list_support_case_events_for_platform_admin(case_id):
    _positive_id(case_id, "case_id")
    response = (
        supabase.table("platform_support_case_events")
        .select(EVENT_FIELDS)
        .eq("case_id", case_id)
        .order("created_at", desc=False)
        .order("id", desc=False)
        .execute()
    )
    return response.data or []


def create_support_case_for_platform_admin(payload):
    response = supabase.table("platform_support_cases").insert(payload).execute()
    rows = response.data or []
    if not rows:
        raise RuntimeError("Support-case insert returned no row")
    return rows[0]


def update_support_case_for_platform_admin(case_id, payload):
    _positive_id(case_id, "case_id")
    response = (
        supabase.table("platform_support_cases")
        .update(payload)
        .eq("id", case_id)
        .execute()
    )
    rows = response.data or []
    if not rows:
        return None
    return rows[0]


def create_support_case_event_for_platform_admin(payload):
    response = supabase.table("platform_support_case_events").insert(payload).execute()
    rows = response.data or []
    if not rows:
        raise RuntimeError("Support-case event insert returned no row")
    return rows[0]


def list_active_platform_admin_assignees_for_platform_admin():
    response = (
        supabase.table("platform_admin_users")
        .select("id,user_id,is_active")
        .eq("is_active", True)
        .order("id", desc=False)
        .execute()
    )
    return response.data or []


def get_active_platform_admin_assignee_for_platform_admin(platform_admin_user_id):
    _positive_id(platform_admin_user_id, "platform_admin_user_id")
    response = (
        supabase.table("platform_admin_users")
        .select("id,user_id,is_active")
        .eq("id", platform_admin_user_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def _rpc_object(response, function_name):
    value = response.data
    if isinstance(value, list):
        value = value[0] if len(value) == 1 else None
    if not isinstance(value, dict):
        raise RuntimeError(f"{function_name} RPC returned an invalid result")
    return value


def _validate_case_result(result, function_name):
    case = result.get("case")
    event = result.get("event")
    if not isinstance(case, dict) or not isinstance(event, dict):
        raise RuntimeError(f"{function_name} RPC returned an invalid result")
    case_id = case.get("id")
    event_case_id = event.get("case_id")
    if (
        isinstance(case_id, bool) or not isinstance(case_id, int) or case_id <= 0
        or event_case_id != case_id
    ):
        raise RuntimeError(f"{function_name} RPC returned an invalid case ID")
    if case.get("status") not in ALLOWED_STATUSES:
        raise RuntimeError(f"{function_name} RPC returned an invalid status")
    if case.get("priority") not in ALLOWED_PRIORITIES:
        raise RuntimeError(f"{function_name} RPC returned an invalid priority")
    return result


def assign_support_case_for_platform_admin(case_id, platform_admin_user_id, assignee_platform_admin_user_id):
    _positive_id(case_id, "case_id")
    _positive_id(platform_admin_user_id, "platform_admin_user_id")
    if assignee_platform_admin_user_id is not None:
        _positive_id(assignee_platform_admin_user_id, "assignee_platform_admin_user_id")
    return _validate_case_result(
        _rpc_object(
            supabase.rpc(
                "assign_platform_support_case",
                {
                    "p_case_id": case_id,
                    "p_platform_admin_user_id": platform_admin_user_id,
                    "p_assignee_platform_admin_user_id": assignee_platform_admin_user_id,
                },
            ).execute(),
            "assign_platform_support_case",
        ),
        "assign_platform_support_case",
    )


def set_support_case_status_for_platform_admin(case_id, platform_admin_user_id, status):
    _positive_id(case_id, "case_id")
    _positive_id(platform_admin_user_id, "platform_admin_user_id")
    if status not in ALLOWED_STATUSES:
        raise ValueError("Unsupported support-case status")
    return _validate_case_result(
        _rpc_object(
            supabase.rpc(
                "set_platform_support_case_status",
                {
                    "p_case_id": case_id,
                    "p_platform_admin_user_id": platform_admin_user_id,
                    "p_status": status,
                },
            ).execute(),
            "set_platform_support_case_status",
        ),
        "set_platform_support_case_status",
    )


def set_support_case_priority_for_platform_admin(case_id, platform_admin_user_id, priority):
    _positive_id(case_id, "case_id")
    _positive_id(platform_admin_user_id, "platform_admin_user_id")
    if priority not in ALLOWED_PRIORITIES:
        raise ValueError("Unsupported support-case priority")
    return _validate_case_result(
        _rpc_object(
            supabase.rpc(
                "set_platform_support_case_priority",
                {
                    "p_case_id": case_id,
                    "p_platform_admin_user_id": platform_admin_user_id,
                    "p_priority": priority,
                },
            ).execute(),
            "set_platform_support_case_priority",
        ),
        "set_platform_support_case_priority",
    )


def add_support_case_note_for_platform_admin(case_id, platform_admin_user_id, redacted_note):
    _positive_id(case_id, "case_id")
    _positive_id(platform_admin_user_id, "platform_admin_user_id")
    if not isinstance(redacted_note, str) or not redacted_note.strip():
        raise ValueError("redacted_note must be non-empty text")
    return _validate_case_result(
        _rpc_object(
            supabase.rpc(
                "add_platform_support_case_note",
                {
                    "p_case_id": case_id,
                    "p_platform_admin_user_id": platform_admin_user_id,
                    "p_redacted_note": redacted_note,
                },
            ).execute(),
            "add_platform_support_case_note",
        ),
        "add_platform_support_case_note",
    )
