"""Server validation for merchant report commands and schedule periods."""
import calendar
from datetime import date, datetime, time, timedelta
import re
from zoneinfo import ZoneInfo
from app.services.analysis_report_service import validate_request_spec as validate_report_spec


# analysis_enqueue_schedule (data/063) keys scheduled reports as
# 'schedule:<schedule id>:<period>'. Manual requests may not use this prefix,
# so the prefix alone tells a scheduled (automatic) report from a manual one.
SCHEDULED_KEY_PREFIX = "schedule:"


def is_scheduled_report(report):
    return str((report or {}).get("client_message_id") or "").startswith(SCHEDULED_KEY_PREFIX)


def schedule_owner_durably_unentitled(company_id):
    """True only when billing was READ and shows no entitled subscription.

    can_use_plan_feature reports both "cancelled/expired" and "lookup failed"
    as no_subscription. The schedule tick must skip the first (or churned rows
    pile up at the head of the due queue) but keep the second. A failed read
    returns False, so a billing blip never costs a Pro tenant a period.
    """
    from app.services.billing_service import get_current_subscription
    from app.services.free_trial_status_service import resolve_subscription_entitlement

    try:
        subscription = get_current_subscription(company_id)
        if not subscription:
            return True
        return not resolve_subscription_entitlement(subscription, subscription.get("plan"))["entitled"]
    except Exception:
        return False


def validate_request_spec(value):
    result = validate_report_spec(value, allow_incomplete=True)
    if result["timezone"] != "Asia/Kuala_Lumpur":
        raise ValueError("Reports currently use Asia/Kuala_Lumpur.")
    if bool(result["period_start"]) != bool(result["period_end"]):
        raise ValueError("Provide both report dates.")
    return result


REPORT_TZ = ZoneInfo("Asia/Kuala_Lumpur")
MISSING_SLOT = "Choose a day and time first."
_QUARTER_HOUR = re.compile(r"([01]\d|2[0-3]):(00|15|30|45)")


def _whole(value, low, high):
    return type(value) is int and low <= value <= high


def validate_schedule_choice(frequency, run_weekday=None, run_day=None, run_time=None):
    """Check the owner's slot; None means "not given" (disabling keeps the stored one).

    weekly: run_weekday 0 (Monday) .. 6 (Sunday); monthly: run_day 1..28 or
    "last". run_time is Malaysia time in 15-minute steps, "HH:MM".
    """
    if frequency not in {"weekly", "monthly"}:
        raise ValueError("Choose weekly or monthly.")
    if run_weekday is not None and (frequency != "weekly" or not _whole(run_weekday, 0, 6)):
        raise ValueError("Weekly reports need a weekday from Monday to Sunday.")
    if run_day is not None and (frequency != "monthly" or not (run_day == "last" or _whole(run_day, 1, 28))):
        raise ValueError("Monthly reports need a day from 1 to 28, or the last day of the month.")
    if run_time is not None and not (isinstance(run_time, str) and _QUARTER_HOUR.fullmatch(run_time)):
        raise ValueError("Choose a time on the quarter hour, such as 09:00 or 18:15.")
    return {"run_weekday": run_weekday, "run_day": run_day, "run_time": run_time}


def _run_date(year, month, run_day):
    # "last" is the 31st clamped to the month, so February gives the 28th/29th.
    day = 31 if run_day == "last" else run_day
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _months_from(year, month, delta):
    index = year * 12 + month - 1 + delta
    return index // 12, index % 12 + 1


def schedule_period(frequency, now=None, run_weekday=None, run_day=None, run_time=None):
    """Latest due period only, including after downtime, for the owner's slot.

    Periods roll back from the run date: weekly covers the 7 days before it,
    monthly the month before it (run 15 Oct: 15 Sep .. 14 Oct; "last": the
    previous month's last day .. the day before this run). period_end is
    exclusive, as analysis_report_service reads it. next_due_at is the next
    slot strictly after the returned one.
    """
    choice = validate_schedule_choice(frequency, run_weekday, run_day, run_time)
    slot_day = choice["run_weekday"] if frequency == "weekly" else choice["run_day"]
    if slot_day is None or choice["run_time"] is None:
        raise ValueError(MISSING_SLOT)
    at = time(int(run_time[:2]), int(run_time[3:]))
    local = (now or datetime.now(REPORT_TZ)).astimezone(REPORT_TZ)
    if frequency == "weekly":
        run = local.date() - timedelta(days=(local.weekday() - run_weekday) % 7)
        if local < datetime.combine(run, at, REPORT_TZ):
            run -= timedelta(days=7)
        start, next_run = run - timedelta(days=7), run + timedelta(days=7)
    else:
        year, month = local.year, local.month
        if local < datetime.combine(_run_date(year, month, run_day), at, REPORT_TZ):
            year, month = _months_from(year, month, -1)
        run = _run_date(year, month, run_day)
        start = _run_date(*_months_from(year, month, -1), run_day)
        next_run = _run_date(*_months_from(year, month, 1), run_day)
    return {"period_key": f"{frequency}:{start.isoformat()}:{run.isoformat()}",
            "request_spec": {"kind": "business", "timezone": "Asia/Kuala_Lumpur",
                             "period_start": start.isoformat(), "period_end": run.isoformat()},
            "next_due_at": datetime.combine(next_run, at, REPORT_TZ).isoformat()}
