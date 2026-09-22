"""Server validation for merchant report commands and schedule periods."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.services.analysis_report_service import validate_request_spec as validate_report_spec


def validate_request_spec(value):
    result = validate_report_spec(value, allow_incomplete=True)
    if result["timezone"] != "Asia/Kuala_Lumpur":
        raise ValueError("Reports currently use Asia/Kuala_Lumpur.")
    if bool(result["period_start"]) != bool(result["period_end"]):
        raise ValueError("Provide both report dates.")
    return result


def schedule_period(frequency, now=None):
    """Latest complete period only, including after downtime; Monday/1st at 09:00."""
    local = (now or datetime.now(ZoneInfo("Asia/Kuala_Lumpur"))).astimezone(ZoneInfo("Asia/Kuala_Lumpur"))
    if frequency == "weekly":
        due = local.replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=local.weekday())
        if local < due:
            due -= timedelta(days=7)
        end = due.date()
        start = end - timedelta(days=7)
        next_due = due + timedelta(days=7)
    elif frequency == "monthly":
        due = local.replace(day=1, hour=9, minute=0, second=0, microsecond=0)
        if local < due:
            due = (due - timedelta(days=1)).replace(day=1)
        end = due.date()
        start = (end - timedelta(days=1)).replace(day=1)
        next_due = (due + timedelta(days=32)).replace(day=1)
    else:
        raise ValueError("Choose weekly or monthly.")
    return {"period_key": f"{frequency}:{start.isoformat()}",
            "request_spec": {"kind": "business", "timezone": "Asia/Kuala_Lumpur", "period_start": start.isoformat(), "period_end": end.isoformat()},
            "next_due_at": next_due.isoformat()}
