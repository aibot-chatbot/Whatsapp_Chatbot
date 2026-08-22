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
    "new_assigned_platform_admin_user_id,tenant_support_reply_id,"
    "redacted_note,created_at"
)
REPLY_FIELDS = (
    "id,request_id,platform_support_case_id,company_id,author_type,"
    "redacted_body,visibility_status,created_at"
)
REPLY_NOTIFICATION_FIELDS = (
    "id,reply_id,request_id,platform_support_case_id,company_id,channel,status,"
    "attempt_count,last_attempt_at,delivered_at,failure_code,created_at,updated_at"
)
ASSIGNEE_USER_IDENTITY_FIELDS = "id,email,full_name"
ALLOWED_STATUSES = {"open", "in_progress", "waiting_for_tenant", "resolved", "closed"}
ALLOWED_PRIORITIES = {"low", "normal", "high", "urgent"}
ALLOWED_LIST_SORT_FIELDS = {"created_at", "updated_at", "priority", "status", "id"}
ALLOWED_LIST_SORT_ORDERS = {"asc", "desc"}


def _positive_id(value, field_name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _load_assignee_users_by_id(user_ids):
    ids = sorted({
        value for value in user_ids
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    })
    if not ids:
        return {}
    response = (
        supabase.table("users")
        .select(ASSIGNEE_USER_IDENTITY_FIELDS)
        .in_("id", ids)
        .execute()
    )
    return {
        row.get("id"): row
        for row in (response.data or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }


def _project_platform_admin_assignee(row, users_by_id):
    user = users_by_id.get(row.get("user_id")) or {}
    return {
        "id": row.get("id"),
        "user_id": row.get("user_id"),
        "is_active": row.get("is_active"),
        "user_full_name": user.get("full_name"),
        "user_email": user.get("email"),
    }


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


def list_support_case_events_for_platform_admin(case_id, *, limit, offset):
    _positive_id(case_id, "case_id")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    response = (
        supabase.table("platform_support_case_events")
        .select(EVENT_FIELDS, count="exact")
        .eq("case_id", case_id)
        .order("created_at", desc=False)
        .order("id", desc=False)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return response.data or [], int(response.count or 0)


def list_support_case_replies_for_platform_admin(case_id, *, limit, offset):
    _positive_id(case_id, "case_id")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    response = (
        supabase.table("tenant_support_replies")
        .select(REPLY_FIELDS, count="exact")
        .eq("platform_support_case_id", case_id)
        .order("created_at", desc=False)
        .order("id", desc=False)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return response.data or [], int(response.count or 0)


def list_support_case_reply_notifications_for_platform_admin(case_id, reply_ids):
    _positive_id(case_id, "case_id")
    ids = sorted({
        value for value in reply_ids
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    })
    if not ids:
        return []
    response = (
        supabase.table("tenant_support_reply_notifications")
        .select(REPLY_NOTIFICATION_FIELDS)
        .eq("platform_support_case_id", case_id)
        .in_("reply_id", ids)
        .order("created_at", desc=False)
        .order("id", desc=False)
        .execute()
    )
    return response.data or []


def create_support_case_for_platform_admin(
    *, company_id, platform_admin_user_id, title, redacted_summary, status, priority
):
    _positive_id(company_id, "company_id")
    _positive_id(platform_admin_user_id, "platform_admin_user_id")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be non-empty text")
    if not isinstance(redacted_summary, str) or not redacted_summary.strip():
        raise ValueError("redacted_summary must be non-empty text")
    if status not in ALLOWED_STATUSES:
        raise ValueError("Unsupported support-case status")
    if priority not in ALLOWED_PRIORITIES:
        raise ValueError("Unsupported support-case priority")
    return _validate_creation_result(
        _rpc_object(
            supabase.rpc(
                "create_platform_support_case",
                {
                    "p_company_id": company_id,
                    "p_platform_admin_user_id": platform_admin_user_id,
                    "p_title": title,
                    "p_redacted_summary": redacted_summary,
                    "p_status": status,
                    "p_priority": priority,
                },
            ).execute(),
            "create_platform_support_case",
        ),
        company_id,
        platform_admin_user_id,
        title,
        redacted_summary,
        status,
        priority,
        "create_platform_support_case",
    )


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


def list_active_platform_admin_assignees_for_platform_admin():
    response = (
        supabase.table("platform_admin_users")
        .select("id,user_id,is_active")
        .eq("is_active", True)
        .order("id", desc=False)
        .execute()
    )
    rows = response.data or []
    users_by_id = _load_assignee_users_by_id([row.get("user_id") for row in rows])
    return [_project_platform_admin_assignee(row, users_by_id) for row in rows]


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


def _validate_creation_result(
    result, requested_company_id, platform_admin_user_id, title, redacted_summary,
    status, priority, function_name,
):
    result = _validate_case_result(result, function_name)
    case = result["case"]
    event = result["event"]
    audit = result.get("audit")
    if not isinstance(audit, dict):
        raise RuntimeError(f"{function_name} RPC returned an invalid audit event")
    case_id = case.get("id")
    event_id = event.get("id")
    audit_id = audit.get("id")
    if (
        not _positive_rpc_int(event_id)
        or not _positive_rpc_int(audit_id)
        or case.get("company_id") != requested_company_id
        or case.get("created_by_platform_admin_user_id") != platform_admin_user_id
        or case.get("title") != title
        or case.get("redacted_summary") != redacted_summary
        or case.get("status") != status
        or case.get("priority") != priority
        or event.get("event_type") != "created"
        or event.get("actor_platform_admin_user_id") != platform_admin_user_id
        or event.get("new_status") != status
        or event.get("new_priority") != priority
        or audit.get("platform_admin_user_id") != platform_admin_user_id
        or audit.get("action") != "platform_admin.support_case.create"
        or audit.get("resource_type") != "platform_support_cases"
        or audit.get("resource_id") != str(case_id)
    ):
        raise RuntimeError(f"{function_name} RPC returned invalid creation linkage")
    metadata = audit.get("metadata")
    if not isinstance(metadata, dict):
        raise RuntimeError(f"{function_name} RPC returned invalid audit metadata")
    expected_metadata = {
        "outcome": "success",
        "endpoint": "/api/platform-admin/support-cases",
        "http_method": "POST",
        "company_id": requested_company_id,
        "status": status,
        "priority": priority,
    }
    for key, value in expected_metadata.items():
        if metadata.get(key) != value:
            raise RuntimeError(f"{function_name} RPC returned invalid audit metadata")
    return result


def _positive_rpc_int(value):
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _validate_reply_result(result, requested_case_id, function_name):
    if not isinstance(result, dict):
        raise RuntimeError(f"{function_name} RPC returned an invalid result")

    case = result.get("case")
    event = result.get("event")
    reply = result.get("reply")
    notification = result.get("notification")
    if not all(isinstance(item, dict) for item in (case, event, reply, notification)):
        raise RuntimeError(f"{function_name} RPC returned an invalid result")

    case_id = case.get("id")
    case_company_id = case.get("company_id")
    event_id = event.get("id")
    event_case_id = event.get("case_id")
    event_reply_id = event.get("tenant_support_reply_id")
    reply_id = reply.get("id")
    reply_request_id = reply.get("request_id")
    reply_company_id = reply.get("company_id")
    notification_id = notification.get("id")
    notification_attempt_count = notification.get("attempt_count")

    if (
        not _positive_rpc_int(case_id)
        or case_id != requested_case_id
        or not _positive_rpc_int(case_company_id)
        or not _positive_rpc_int(event_id)
        or not _positive_rpc_int(event_case_id)
        or not _positive_rpc_int(event_reply_id)
        or not _positive_rpc_int(reply_id)
        or not _positive_rpc_int(reply_request_id)
        or not _positive_rpc_int(reply_company_id)
        or not _positive_rpc_int(notification_id)
    ):
        raise RuntimeError(f"{function_name} RPC returned an invalid linkage")
    if case.get("status") not in ALLOWED_STATUSES:
        raise RuntimeError(f"{function_name} RPC returned an invalid status")
    if case.get("priority") not in ALLOWED_PRIORITIES:
        raise RuntimeError(f"{function_name} RPC returned an invalid priority")
    if event_case_id != case_id or event.get("event_type") != "tenant_reply_created":
        raise RuntimeError(f"{function_name} RPC returned an invalid event")
    if event_reply_id != reply_id:
        raise RuntimeError(f"{function_name} RPC returned an invalid event linkage")
    if (
        reply.get("platform_support_case_id") != case_id
        or reply_company_id != case_company_id
        or reply.get("author_type") != "platform_admin"
        or reply.get("visibility_status") != "visible"
    ):
        raise RuntimeError(f"{function_name} RPC returned an invalid reply")

    body = reply.get("redacted_body")
    if not isinstance(body, str) or not body.strip() or len(body) > 4000:
        raise RuntimeError(f"{function_name} RPC returned an invalid reply body")
    if (
        notification.get("reply_id") != reply_id
        or notification.get("request_id") != reply_request_id
        or notification.get("platform_support_case_id") != case_id
        or notification.get("company_id") != case_company_id
        or notification.get("channel") != "in_app"
        or notification.get("status") != "pending"
        or isinstance(notification_attempt_count, bool)
        or not isinstance(notification_attempt_count, int)
        or notification_attempt_count < 0
    ):
        raise RuntimeError(f"{function_name} RPC returned an invalid notification")
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


def create_support_case_reply_for_platform_admin(case_id, platform_admin_user_id, redacted_body):
    _positive_id(case_id, "case_id")
    _positive_id(platform_admin_user_id, "platform_admin_user_id")
    if not isinstance(redacted_body, str) or not redacted_body.strip():
        raise ValueError("redacted_body must be non-empty text")
    return _validate_reply_result(
        _rpc_object(
            supabase.rpc(
                "create_platform_support_case_reply",
                {
                    "p_case_id": case_id,
                    "p_platform_admin_user_id": platform_admin_user_id,
                    "p_redacted_body": redacted_body,
                },
            ).execute(),
            "create_platform_support_case_reply",
        ),
        case_id,
        "create_platform_support_case_reply",
    )
