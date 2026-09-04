from datetime import datetime, timezone

from app.database.db import supabase
from app.database.db_errors import is_unique_violation


AUTOMATION_EVENT_TYPES = {
    "knowledge_document_follow_up",
    "crm_stage_transition",
}
AUTOMATION_EVENT_STATUSES = {
    "queued",
    "running",
    "completed",
    "failed",
    "blocked",
}


def automation_events_table_available():
    """Return whether the optional automation event table can be queried."""
    try:
        supabase.table("automation_events").select("id").limit(1).execute()
    except Exception:
        return False
    return True


def _positive_int(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _validate_event(event_type, status):
    if event_type not in AUTOMATION_EVENT_TYPES:
        raise ValueError("Unsupported automation event type")
    if status not in AUTOMATION_EVENT_STATUSES:
        raise ValueError("Unsupported automation event status")


def _validate_status(status):
    if status not in AUTOMATION_EVENT_STATUSES:
        raise ValueError("Unsupported automation event status")


def get_automation_event_by_key(company_id, idempotency_key):
    _positive_int(company_id, "company_id")
    if not idempotency_key:
        raise ValueError("idempotency_key is required")

    result = (
        supabase.table("automation_events")
        .select("*")
        .eq("company_id", company_id)
        .eq("idempotency_key", str(idempotency_key))
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def create_automation_event(
    *,
    company_id,
    chatbot_id,
    event_type,
    idempotency_key,
    payload=None,
    status="queued",
):
    _positive_int(company_id, "company_id")
    _positive_int(chatbot_id, "chatbot_id")
    _validate_event(event_type, status)
    if not idempotency_key or len(str(idempotency_key)) > 200:
        raise ValueError("idempotency_key is required and must be <= 200 characters")
    if payload is not None and not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    existing = get_automation_event_by_key(company_id, idempotency_key)
    if existing:
        return existing

    data = {
        "company_id": company_id,
        "chatbot_id": chatbot_id,
        "event_type": event_type,
        "status": status,
        "idempotency_key": str(idempotency_key),
        "payload": payload or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        result = supabase.table("automation_events").insert(data).execute()
    except Exception as exc:
        if not is_unique_violation(exc):
            raise
        return get_automation_event_by_key(company_id, idempotency_key)

    rows = result.data or []
    return rows[0] if rows else None


def list_automation_events(company_id, chatbot_id=None, status=None, limit=50):
    _positive_int(company_id, "company_id")
    if chatbot_id is not None:
        _positive_int(chatbot_id, "chatbot_id")
    if status is not None and status not in AUTOMATION_EVENT_STATUSES:
        raise ValueError("Unsupported automation event status")

    safe_limit = min(max(int(limit or 50), 1), 100)
    query = (
        supabase.table("automation_events")
        .select("*")
        .eq("company_id", company_id)
    )
    if chatbot_id is not None:
        query = query.eq("chatbot_id", chatbot_id)
    if status is not None:
        query = query.eq("status", status)

    result = query.order("created_at", desc=True).limit(safe_limit).execute()
    return result.data or []


def update_automation_event_status(
    *, company_id, chatbot_id, event_id, status, result=None, error_message=None
):
    _positive_int(company_id, "company_id")
    _positive_int(chatbot_id, "chatbot_id")
    _positive_int(event_id, "event_id")
    _validate_status(status)
    if result is not None and not isinstance(result, dict):
        raise ValueError("result must be an object")

    data = {
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if result is not None:
        data["result"] = result
    if error_message is not None:
        data["error_message"] = str(error_message)[:500]

    response = (
        supabase.table("automation_events")
        .update(data)
        .eq("id", event_id)
        .eq("company_id", company_id)
        .eq("chatbot_id", chatbot_id)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None
