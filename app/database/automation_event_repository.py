from datetime import datetime, timezone
from uuid import UUID

from app.database.db import supabase
from app.database.db_errors import is_unique_violation


AUTOMATION_EVENT_TYPES = {
    "knowledge_document_follow_up",
    "crm_stage_transition",
    "agent_report",
    "business_observation",
    "tuition_reminder",
    "agent_notification",
    "schedule_tick",
}
AUTOMATION_EVENT_STATUSES = {
    "queued",
    "running",
    "completed",
    "failed",
    "blocked",
    "needs_review",
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
        .eq("event_type", "crm_stage_transition")
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


WORKER_TERMINAL_STATUSES = {"completed", "failed", "needs_review"}
WORKER_EVENT_TYPES = {
    "agent_report": frozenset({"agent_report"}),
    "business_observation": frozenset({"business_observation"}),
    "tuition_reminder": frozenset({"tuition_reminder"}),
    "n8n": frozenset({"knowledge_document_follow_up", "agent_notification", "schedule_tick"}),
}
DEFAULT_CLAIM_LIMIT = 10
MAX_CLAIM_LIMIT = 50
MIN_CLAIM_LEASE_SECONDS = 30
MAX_CLAIM_LEASE_SECONDS = 3600


def get_automation_event_by_id(event_id):
    """Fetch one event without a tenant filter, for the platform worker path.

    Every other read here is company-scoped. This one is not, because the
    outbox worker reports on events it was handed across tenants; callers must
    take company_id and chatbot_id from the returned row rather than from the
    request, so a worker can never redirect an update at another tenant's row.
    """
    _positive_int(event_id, "event_id")

    result = (
        supabase.table("automation_events")
        .select("*")
        .eq("id", event_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def _worker_kind(value):
    if value not in WORKER_EVENT_TYPES:
        raise ValueError("Unsupported worker kind")
    return value


def _lease_token(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("A valid lease_token is required") from exc


def claim_queued_automation_events(*, limit=DEFAULT_CLAIM_LIMIT, lease_seconds=300, worker_kind="n8n"):
    """Atomically claim only the server-assigned worker's job types.

    Migration 064 owns locking, expiry, fencing and the retry budget. A missing
    RPC fails closed; never fall back to a read-then-write claim.
    """
    _worker_kind(worker_kind)
    _positive_int(limit, "limit")
    _positive_int(lease_seconds, "lease_seconds")
    response = supabase.rpc("claim_automation_events_v1", {
        "p_worker_kind": worker_kind,
        "p_limit": min(limit, MAX_CLAIM_LIMIT),
        "p_lease_seconds": min(max(lease_seconds, MIN_CLAIM_LEASE_SECONDS), MAX_CLAIM_LEASE_SECONDS),
    }).execute()
    return response.data or []


def renew_automation_event_lease(*, event_id, lease_token, worker_kind, lease_seconds=300):
    _positive_int(event_id, "event_id")
    _positive_int(lease_seconds, "lease_seconds")
    response = supabase.rpc("renew_automation_event_lease_v1", {
        "p_event_id": event_id, "p_lease_token": _lease_token(lease_token),
        "p_worker_kind": _worker_kind(worker_kind),
        "p_lease_seconds": min(max(lease_seconds, MIN_CLAIM_LEASE_SECONDS), MAX_CLAIM_LEASE_SECONDS),
    }).execute()
    return next(iter(response.data or []), None)


def finish_automation_event(*, event_id, lease_token, worker_kind, status, result=None,
                            error_message=None, retryable=False):
    _positive_int(event_id, "event_id")
    if not isinstance(status, str) or status not in WORKER_TERMINAL_STATUSES:
        raise ValueError("Unsupported worker outcome")
    if result is not None and not isinstance(result, dict):
        raise ValueError("result must be an object")
    if not isinstance(retryable, bool):
        raise ValueError("retryable must be a boolean")
    response = supabase.rpc("finish_automation_event_v1", {
        "p_event_id": event_id, "p_lease_token": _lease_token(lease_token),
        "p_worker_kind": _worker_kind(worker_kind), "p_status": status,
        "p_result": result, "p_error_message": str(error_message)[:500] if error_message else None,
        "p_retryable": retryable,
    }).execute()
    return next(iter(response.data or []), None)
