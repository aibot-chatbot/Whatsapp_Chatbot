from datetime import datetime, timedelta, timezone

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


WORKER_TERMINAL_STATUSES = {"completed", "failed"}
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


def claim_queued_automation_events(*, limit=DEFAULT_CLAIM_LIMIT, lease_seconds=300):
    """Claim outbox events for the out-of-process worker.

    Deliberately crosses tenants: the outbox worker is a platform actor, and
    the token that reaches this path is a platform credential.

    Each row is claimed with a conditional update on the status it was read
    with, so two workers racing the same row leave exactly one winner instead
    of both believing they own it.

    ``running`` rows older than the lease are re-offered. Without that, a
    worker that dies mid-event strands its row at ``running`` forever - the
    same claim-check ordering failure that previously left payment orders
    stuck at claimed.
    """
    safe_limit = min(max(int(limit or DEFAULT_CLAIM_LIMIT), 1), MAX_CLAIM_LIMIT)
    safe_lease = min(
        max(int(lease_seconds or 300), MIN_CLAIM_LEASE_SECONDS), MAX_CLAIM_LEASE_SECONDS
    )
    now = datetime.now(timezone.utc)
    stale_before = (now - timedelta(seconds=safe_lease)).isoformat()

    candidates = list(
        (
            supabase.table("automation_events")
            .select("*")
            .eq("status", "queued")
            .order("created_at", desc=False)
            .limit(safe_limit)
            .execute()
        ).data
        or []
    )

    remaining = safe_limit - len(candidates)
    if remaining > 0:
        candidates.extend(
            (
                supabase.table("automation_events")
                .select("*")
                .eq("status", "running")
                .lt("updated_at", stale_before)
                .order("updated_at", desc=False)
                .limit(remaining)
                .execute()
            ).data
            or []
        )

    claimed = []
    for row in candidates:
        previous = row.get("status")
        won = (
            supabase.table("automation_events")
            .update({"status": "running", "updated_at": now.isoformat()})
            .eq("id", row["id"])
            .eq("status", previous)
            .execute()
        )
        rows = won.data or []
        if rows:
            claimed.append(rows[0])
    return claimed
