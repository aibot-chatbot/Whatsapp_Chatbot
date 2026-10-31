"""Durable persistence and fenced claims for GEO monitoring schedules."""
from datetime import datetime, timezone
from uuid import UUID

from app.database.db import supabase
from app.database.geo_repository import GeoStorageUnavailable


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _uuid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("A valid schedule ID is required") from None


def _rows(query):
    try:
        rows = query.execute().data
    except Exception:
        raise GeoStorageUnavailable("GEO monitoring storage is unavailable") from None
    if not isinstance(rows, list):
        raise GeoStorageUnavailable("GEO monitoring storage returned an invalid response")
    return rows


def get_schedule(company_id):
    rows = _rows(supabase.table("geo_monitoring_schedules").select("*")
                 .eq("company_id", _positive(company_id, "company_id")).limit(1))
    return rows[0] if rows else None


def upsert_schedule(company_id, actor_user_id, schedule):
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "company_id": _positive(company_id, "company_id"),
        "actor_user_id": _positive(actor_user_id, "actor_user_id"),
        "frequency": schedule["frequency"],
        "run_weekday": schedule.get("run_weekday"),
        "run_day": schedule.get("run_day"),
        "run_time": schedule["run_time"],
        "timezone": schedule["timezone"],
        "enabled": schedule["enabled"],
        "spec": schedule["spec"],
        "next_run_at": schedule.get("next_run_at"),
        "updated_at": now,
    }
    rows = _rows(supabase.table("geo_monitoring_schedules")
                 .upsert(payload, on_conflict="company_id"))
    if len(rows) != 1:
        raise GeoStorageUnavailable("GEO monitoring schedule was not confirmed")
    return rows[0]


def claim_due(limit=1, lease_seconds=600):
    return _rows(supabase.rpc("claim_geo_monitoring_schedules", {
        "p_limit": max(1, min(int(limit), 10)),
        "p_lease_seconds": max(60, min(int(lease_seconds), 1800)),
    }))


def begin_claim(schedule_id, lease_token, claimed_updated_at, *, next_run_at):
    """Advance a claimed occurrence before any billable provider work starts.

    The version fence makes a concurrent user edit win. Advancing ``next_run_at``
    here means a worker crash cannot make the same scheduled slot claimable and
    billable for a second time after its lease expires.
    """
    rows = _rows(supabase.table("geo_monitoring_schedules").update({
        "next_run_at": next_run_at,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", _uuid(schedule_id)).eq("lease_token", _uuid(lease_token))
       .eq("updated_at", str(claimed_updated_at)))
    if len(rows) != 1:
        raise GeoStorageUnavailable("GEO monitoring lease no longer belongs to this worker")
    return rows[0]


def finish_claim(schedule_id, lease_token, claimed_updated_at, *, next_run_at, last_status,
                 analysis_id=None, error_code=None):
    rows = _rows(supabase.table("geo_monitoring_schedules").update({
        "next_run_at": next_run_at,
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        "last_analysis_id": analysis_id,
        "last_status": last_status,
        "last_error_code": error_code,
        "lease_token": None,
        "lease_expires_at": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", _uuid(schedule_id)).eq("lease_token", _uuid(lease_token))
       .eq("updated_at", str(claimed_updated_at)))
    if len(rows) != 1:
        raise GeoStorageUnavailable("GEO monitoring lease no longer belongs to this worker")
    return rows[0]
