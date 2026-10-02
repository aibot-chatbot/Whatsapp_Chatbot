"""Trusted queue IDs select reminder state; all writes are fenced RPCs."""
from app.database.tuition_repository import _rpc, positive, uuid


def enqueue_due(*, limit=100):
    positive(limit)
    if limit > 100:
        raise ValueError("Reminder limit must not exceed 100")
    return _rpc("tuition_enqueue_reminders", {"p_limit": limit})


def apply_reminder(*, event_id, lease_token, operation, output=None):
    if operation not in {"inspect", "begin", "finish", "uncertain", "skip"}:
        raise ValueError("Invalid reminder operation")
    return _rpc("tuition_apply_reminder", {"p_event_id": positive(event_id), "p_lease_token": uuid(lease_token),
        "p_operation": operation, "p_output": output})
