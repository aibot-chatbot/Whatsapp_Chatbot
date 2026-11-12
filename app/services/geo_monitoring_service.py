"""Validation and background execution for durable GEO monitoring schedules."""
from datetime import datetime, time as clock_time, timedelta, timezone
import logging
import os
import threading
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.database import geo_monitoring_repository, user_repository
from app.database.geo_repository import GeoMonthlyLimitExceeded, GeoStorageUnavailable
from app.services.billing_guard import BillingLimitError, get_company_geo_entitlement
from app.services.company_status_service import CompanyOperationalStatusError, ensure_company_operational
from app.services.geo_analysis_service import run_analysis, validate_spec


logger = logging.getLogger(__name__)
_scheduler_started = False
WEEKLY_RUNS_PER_MONTH_BUDGET = 5


def _parse_time(value):
    try:
        parsed = clock_time.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError("Monitoring time must use HH:MM format.") from None
    if parsed.second or parsed.microsecond or parsed.minute % 15:
        raise ValueError("Choose a monitoring time in 15-minute intervals.")
    return parsed


def _zone(value):
    name = str(value or "Asia/Kuala_Lumpur").strip()
    try:
        return name, ZoneInfo(name)
    except ZoneInfoNotFoundError:
        raise ValueError("Choose a valid IANA timezone.") from None


def next_run_at(frequency, *, run_time, timezone_name, run_weekday=None, run_day=None, now=None):
    """Return the next future monitoring slot as UTC ISO text."""
    slot = _parse_time(run_time)
    _, zone = _zone(timezone_name)
    local_now = (now or datetime.now(timezone.utc)).astimezone(zone)
    if frequency == "weekly":
        if isinstance(run_weekday, bool) or not isinstance(run_weekday, int) or not 0 <= run_weekday <= 6:
            raise ValueError("Choose a weekday for weekly monitoring.")
        days = (run_weekday - local_now.weekday()) % 7
        candidate = datetime.combine((local_now + timedelta(days=days)).date(), slot, zone)
        if candidate <= local_now:
            candidate += timedelta(days=7)
    elif frequency == "monthly":
        if isinstance(run_day, bool) or not isinstance(run_day, int) or not 1 <= run_day <= 28:
            raise ValueError("Choose a day from 1 to 28 for monthly monitoring.")
        year, month = local_now.year, local_now.month
        candidate = datetime(year, month, run_day, slot.hour, slot.minute, tzinfo=zone)
        if candidate <= local_now:
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
            candidate = datetime(year, month, run_day, slot.hour, slot.minute, tzinfo=zone)
    else:
        raise ValueError("Monitoring frequency must be weekly or monthly.")
    return candidate.astimezone(timezone.utc).isoformat()


def validate_monitoring_request(value, entitlement, *, now=None):
    if not isinstance(value, dict):
        raise ValueError("A monitoring schedule is required.")
    allowed = {"enabled", "frequency", "run_weekday", "run_day", "run_time", "timezone", "spec"}
    if set(value) - allowed:
        raise ValueError("Invalid GEO monitoring fields.")
    if not isinstance(value.get("enabled"), bool):
        raise ValueError("Choose whether monitoring is enabled.")
    frequency = str(value.get("frequency") or "").strip().lower()
    if frequency not in set(entitlement.get("monitoring_frequencies") or []):
        raise ValueError("This monitoring frequency is not included in your plan.")
    timezone_name, _ = _zone(value.get("timezone"))
    run_time = _parse_time(value.get("run_time"))
    run_weekday = value.get("run_weekday") if frequency == "weekly" else None
    run_day = value.get("run_day") if frequency == "monthly" else None
    spec = validate_spec(value.get("spec"), entitlement)
    executions = len(spec["prompts"]) * len(spec["platforms"])
    projected = executions * (WEEKLY_RUNS_PER_MONTH_BUDGET if frequency == "weekly" else 1)
    if projected > entitlement["monthly_executions"]:
        raise ValueError(
            f"This schedule may use {projected} checks in a month, above your "
            f"{entitlement['monthly_executions']}-check allowance. Reduce keywords or platforms."
        )
    return {
        "enabled": value["enabled"], "frequency": frequency,
        "run_weekday": run_weekday, "run_day": run_day,
        "run_time": run_time.strftime("%H:%M:00"), "timezone": timezone_name,
        "spec": spec,
        "next_run_at": next_run_at(frequency, run_time=run_time, timezone_name=timezone_name,
                                   run_weekday=run_weekday, run_day=run_day, now=now)
                       if value["enabled"] else None,
    }


def save_schedule(company_id, actor_user_id, value, entitlement):
    return geo_monitoring_repository.upsert_schedule(
        company_id, actor_user_id, validate_monitoring_request(value, entitlement)
    )


def _run_payload(spec):
    return {key: spec[key] for key in (
        "brand_name", "aliases", "competitors", "owned_domains", "country", "language",
        "platforms", "prompts", "samples_per_prompt"
    )}


def execute_claimed_schedule(schedule, *, now=None):
    current = now or datetime.now(timezone.utc)
    next_at = next_run_at(
        schedule["frequency"], run_time=schedule["run_time"], timezone_name=schedule["timezone"],
        run_weekday=schedule.get("run_weekday"), run_day=schedule.get("run_day"), now=current,
    )
    analysis_id = None
    error_code = None
    status = "failed"
    try:
        ensure_company_operational(schedule["company_id"])
        actor = user_repository.get_user_by_id_for_company(schedule["actor_user_id"], schedule["company_id"])
        if not actor or actor.get("status") != "active":
            raise BillingLimitError("The schedule owner is no longer active.", code="feature_not_available")
        entitlement = get_company_geo_entitlement(schedule["company_id"])
        spec = validate_spec(_run_payload(schedule["spec"]), entitlement)
        schedule = geo_monitoring_repository.begin_claim(
            schedule["id"], schedule["lease_token"], schedule["updated_at"], next_run_at=next_at,
        )
        result = run_analysis(schedule["company_id"], schedule["actor_user_id"], spec, entitlement)
        analysis_id = result.get("id")
        status = result.get("status") if result.get("status") in {"complete", "partial", "failed"} else "failed"
        error_code = result.get("error_code")
    except GeoMonthlyLimitExceeded:
        status, error_code = "quota_blocked", "geo_monthly_limit"
    except (BillingLimitError, CompanyOperationalStatusError):
        status, error_code = "entitlement_blocked", "feature_not_available"
    except (GeoStorageUnavailable, ValueError):
        status, error_code = "failed", "geo_monitoring_failed"

    return geo_monitoring_repository.finish_claim(
        schedule["id"], schedule["lease_token"], schedule["updated_at"], next_run_at=next_at,
        last_status=status, analysis_id=analysis_id, error_code=error_code,
    )


def run_due_schedules(limit=1):
    rows = geo_monitoring_repository.claim_due(limit=limit)
    for schedule in rows:
        execute_claimed_schedule(schedule)
    return len(rows)


def _env_int(name, default):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def monitoring_scheduler_loop():
    logger.info("GEO monitoring scheduler started")
    time.sleep(_env_int("GEO_MONITORING_STARTUP_DELAY_SECONDS", 120))
    while True:
        try:
            run_due_schedules(limit=1)
        except Exception as exc:
            logger.error("GEO monitoring scheduler failed (%s)", type(exc).__name__)
        time.sleep(_env_int("GEO_MONITORING_TICK_SECONDS", 60))


def start_geo_monitoring_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return
    threading.Thread(target=monitoring_scheduler_loop, daemon=True,
                     name="geo-monitoring-scheduler").start()
    _scheduler_started = True
