from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pytest
from app.services.analysis_request_service import (
    schedule_period, validate_request_spec, validate_schedule_choice,
)

MYT = ZoneInfo("Asia/Kuala_Lumpur")


def _at(text):
    return datetime.fromisoformat(text).replace(tzinfo=MYT)


def _period(frequency, now, **choice):
    return schedule_period(frequency, _at(now), **choice)


@pytest.mark.parametrize("frequency,choice,now,start,end,next_due", [
    # The old fixed slot (Monday / 1st, 09:00) is just one owner choice now.
    ("weekly", {"run_weekday": 0}, "2026-09-21T08:59:00", "2026-09-07", "2026-09-14", "2026-09-21T09:00:00+08:00"),
    ("weekly", {"run_weekday": 0}, "2026-09-22T10:00:00", "2026-09-14", "2026-09-21", "2026-09-28T09:00:00+08:00"),
    ("monthly", {"run_day": 1}, "2026-09-01T09:00:00", "2026-08-01", "2026-09-01", "2026-10-01T09:00:00+08:00"),
    ("monthly", {"run_day": 1}, "2026-01-01T08:00:00", "2025-11-01", "2025-12-01", "2026-01-01T09:00:00+08:00"),
])
def test_only_latest_complete_period(frequency, choice, now, start, end, next_due):
    result = _period(frequency, now, run_time="09:00", **choice)
    assert result["request_spec"]["period_start"] == start
    assert result["request_spec"]["period_end"] == end
    assert result["next_due_at"] == next_due


def test_weekly_thursday_quarter_past_six_covers_the_seven_days_before_the_run():
    before = _period("weekly", "2026-09-24T18:14:59", run_weekday=3, run_time="18:15")
    assert (before["request_spec"]["period_start"], before["request_spec"]["period_end"]) == ("2026-09-10", "2026-09-17")
    assert before["next_due_at"] == "2026-09-24T18:15:00+08:00"

    at_boundary = _period("weekly", "2026-09-24T18:15:00", run_weekday=3, run_time="18:15")
    assert at_boundary["period_key"] == "weekly:2026-09-17:2026-09-24"
    assert at_boundary["request_spec"] == {"kind": "business", "timezone": "Asia/Kuala_Lumpur",
                                           "period_start": "2026-09-17", "period_end": "2026-09-24"}
    assert at_boundary["next_due_at"] == "2026-10-01T18:15:00+08:00"


def test_boundary_is_judged_in_malaysia_time_whatever_zone_now_is_in():
    utc_now = datetime(2026, 9, 24, 10, 15, tzinfo=timezone.utc)  # 18:15 MYT
    result = schedule_period("weekly", utc_now, run_weekday=3, run_time="18:15")
    assert result["period_key"] == "weekly:2026-09-17:2026-09-24"


def test_monthly_day_15_is_a_rolling_month():
    # Run 15 Oct covers 15 Sep .. 14 Oct: period_end is exclusive.
    result = _period("monthly", "2026-10-15T18:15:00", run_day=15, run_time="18:15")
    assert result["period_key"] == "monthly:2026-09-15:2026-10-15"
    assert result["next_due_at"] == "2026-11-15T18:15:00+08:00"


@pytest.mark.parametrize("now,start,end,next_due", [
    ("2026-02-28T09:00:00", "2026-01-31", "2026-02-28", "2026-03-31T09:00:00+08:00"),  # February, 28 days
    ("2028-02-29T09:00:00", "2028-01-31", "2028-02-29", "2028-03-31T09:00:00+08:00"),  # February, leap year
    ("2026-04-30T09:00:00", "2026-03-31", "2026-04-30", "2026-05-31T09:00:00+08:00"),  # 30-day month
    ("2026-03-31T09:00:00", "2026-02-28", "2026-03-31", "2026-04-30T09:00:00+08:00"),  # 31-day month
    ("2026-03-30T23:59:00", "2026-01-31", "2026-02-28", "2026-03-31T09:00:00+08:00"),  # not yet the last day
])
def test_last_day_of_month_runs_from_the_previous_months_last_day(now, start, end, next_due):
    result = _period("monthly", now, run_day="last", run_time="09:00")
    assert (result["request_spec"]["period_start"], result["request_spec"]["period_end"]) == (start, end)
    assert result["next_due_at"] == next_due


def test_day_28_in_february():
    result = _period("monthly", "2026-02-28T09:00:00", run_day=28, run_time="09:00")
    assert result["period_key"] == "monthly:2026-01-28:2026-02-28"
    assert result["next_due_at"] == "2026-03-28T09:00:00+08:00"


def test_catch_up_after_three_missed_periods_yields_only_the_latest():
    # Last ran 3 Sep; 10, 17 and 24 Sep were all missed during downtime.
    result = _period("weekly", "2026-09-25T00:00:00", run_weekday=3, run_time="18:15")
    assert result["period_key"] == "weekly:2026-09-17:2026-09-24"
    assert result["next_due_at"] == "2026-10-01T18:15:00+08:00"


@pytest.mark.parametrize("frequency,choice", [
    ("weekly", {"run_weekday": 6, "run_time": "23:45"}),
    ("monthly", {"run_day": "last", "run_time": "00:00"}),
    ("monthly", {"run_day": 28, "run_time": "12:30"}),
])
def test_every_generated_period_is_accepted_by_the_report_validator(frequency, choice):
    spec = _period(frequency, "2026-03-01T00:00:00", **choice)["request_spec"]
    assert validate_request_spec(spec)["period_start"] == spec["period_start"]


@pytest.mark.parametrize("frequency,choice", [
    ("weekly", {}),
    ("weekly", {"run_weekday": 3}),
    ("weekly", {"run_time": "18:15"}),
    ("monthly", {"run_time": "18:15"}),
    ("monthly", {"run_day": 15}),
])
def test_no_fixed_default_slot(frequency, choice):
    with pytest.raises(ValueError, match="Choose a day and time first."):
        schedule_period(frequency, _at("2026-09-24T12:00:00"), **choice)


@pytest.mark.parametrize("frequency,choice", [
    ("weekly", {"run_time": "18:10"}),
    ("weekly", {"run_time": "18:15:00"}),
    ("weekly", {"run_time": "24:00"}),
    ("weekly", {"run_time": "7:15"}),
    ("weekly", {"run_time": 1815}),
    ("weekly", {"run_weekday": 7}),
    ("weekly", {"run_weekday": -1}),
    ("weekly", {"run_weekday": True}),
    ("weekly", {"run_weekday": "3"}),
    ("weekly", {"run_day": 15}),
    ("monthly", {"run_day": 0}),
    ("monthly", {"run_day": 29}),
    ("monthly", {"run_day": "first"}),
    ("monthly", {"run_day": True}),
    ("monthly", {"run_weekday": 3}),
    ("daily", {}),
])
def test_invalid_choices_rejected(frequency, choice):
    with pytest.raises(ValueError):
        validate_schedule_choice(frequency, **choice)


def test_partial_choice_is_valid_until_it_must_run():
    assert validate_schedule_choice("monthly", run_day="last") == {"run_weekday": None, "run_day": "last", "run_time": None}


@pytest.mark.parametrize("spec", [{"sql": "select"}, {"document_ids": [True]}, {"period_start": "2026-01-01"}, {"kind": "payment"}])
def test_untrusted_report_options_rejected(spec):
    with pytest.raises(ValueError):
        validate_request_spec(spec)
