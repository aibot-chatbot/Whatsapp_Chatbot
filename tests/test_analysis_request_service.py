from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from app.services.analysis_request_service import schedule_period, validate_request_spec


@pytest.mark.parametrize("frequency,now,start,end,next_due", [
    ("weekly", "2026-09-21T08:59:00", "2026-09-07", "2026-09-14", "2026-09-21"),
    ("weekly", "2026-09-22T10:00:00", "2026-09-14", "2026-09-21", "2026-09-28"),
    ("monthly", "2026-09-01T09:00:00", "2026-08-01", "2026-09-01", "2026-10-01"),
    ("monthly", "2026-01-01T08:00:00", "2025-11-01", "2025-12-01", "2026-01-01"),
])
def test_only_latest_complete_period(frequency, now, start, end, next_due):
    result = schedule_period(frequency, datetime.fromisoformat(now).replace(tzinfo=ZoneInfo("Asia/Kuala_Lumpur")))
    assert result["request_spec"]["period_start"] == start
    assert result["request_spec"]["period_end"] == end
    assert result["next_due_at"].startswith(next_due)


@pytest.mark.parametrize("spec", [{"sql": "select"}, {"document_ids": [True]}, {"period_start": "2026-01-01"}, {"kind": "payment"}])
def test_untrusted_report_options_rejected(spec):
    with pytest.raises(ValueError):
        validate_request_spec(spec)
