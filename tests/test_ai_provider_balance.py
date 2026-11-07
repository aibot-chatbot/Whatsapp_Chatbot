"""Tests for the shared AI provider credit monitor.

The job exists because one USD balance funds every pooled tenant, so the cases
that matter most are the ones where a naive implementation would either cry wolf
(an uncapped key, a network blip) or stay silent when it should not.
"""

import logging
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from app.jobs import check_ai_provider_balance as job


@pytest.fixture(autouse=True)
def quiet_owner_email(monkeypatch):
    email = Mock(return_value=True)
    monkeypatch.setattr("app.services.email_service.send_ai_balance_alert_email", email)
    monkeypatch.setattr(job, "_emailed_at", {})
    monkeypatch.delenv("OPENROUTER_MANAGEMENT_API_KEY", raising=False)
    return email


def _run(status, monkeypatch, warn="20", critical="5"):
    monkeypatch.setenv("AI_PROVIDER_BALANCE_WARN_USD", warn)
    monkeypatch.setenv("AI_PROVIDER_BALANCE_CRITICAL_USD", critical)
    with patch(
        "app.services.openrouter_service.get_key_status", return_value=status
    ) as reader:
        code = job.check_balance()
    return code, reader


def test_uncapped_key_is_healthy_not_empty(monkeypatch, caplog):
    """limit_remaining=None means 'no cap', not 'no credit'.

    Treating it as zero would fire a CRITICAL alert forever on a perfectly
    healthy pay-as-you-go account, which is how an alert gets ignored.
    """
    with caplog.at_level(logging.DEBUG):
        code, _ = _run({"limit_remaining": None, "usage": 12.5}, monkeypatch)

    assert code == 0
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_healthy_balance_reports_nothing_urgent(monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG):
        code, _ = _run({"limit_remaining": 100.0}, monkeypatch)

    assert code == 0
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_low_balance_warns_but_does_not_page(monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG):
        code, _ = _run({"limit_remaining": 12.0}, monkeypatch)

    assert code == 1
    levels = {r.levelno for r in caplog.records}
    assert logging.WARNING in levels
    # ERROR is promoted to a Sentry event; a merely-low balance is not an
    # incident yet.
    assert logging.ERROR not in levels


def test_critical_balance_logs_error_so_it_reaches_sentry(monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG):
        code, _ = _run({"limit_remaining": 1.25}, monkeypatch)

    assert code == 1
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors, "a critical balance must be an ERROR so Sentry sees it"
    assert "CRITICAL" in errors[0].getMessage()


def test_unreadable_balance_is_unknown_not_critical(monkeypatch, caplog):
    """A network blip must not look identical to an empty account."""
    with caplog.at_level(logging.DEBUG):
        code, _ = _run(None, monkeypatch)

    assert code == 1
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_non_numeric_balance_is_handled(monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG):
        code, _ = _run({"limit_remaining": "not-a-number"}, monkeypatch)

    assert code == 1
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize("bad", ["abc", "-5"])
def test_invalid_threshold_falls_back_to_default(monkeypatch, bad):
    """A negative or unparseable threshold must not disable the alert."""
    monkeypatch.setenv("AI_PROVIDER_BALANCE_CRITICAL_USD", bad)
    assert job._env_float("AI_PROVIDER_BALANCE_CRITICAL_USD", 5.0) == 5.0


def test_balance_reader_never_logs_the_api_key(caplog):
    """The key is a platform credential; a balance check must not leak it."""
    from app.services import openrouter_service

    secret = "sk-or-v1-SECRET-VALUE-DO-NOT-LOG"
    response = Mock(status_code=500)
    with patch.object(openrouter_service, "OPENROUTER_API_KEY", secret), patch.object(
        openrouter_service.requests, "get", return_value=response
    ), caplog.at_level(logging.DEBUG):
        assert openrouter_service.get_key_status() is None

    assert secret not in caplog.text
    assert not any(record.exc_info for record in caplog.records)


# Runway: how long the balance lasts at the recent rate of spending.

A_SUNDAY_THE_14TH = datetime(2026, 6, 14, tzinfo=timezone.utc)


def spending(monkeypatch, *keys):
    monkeypatch.setenv("OPENROUTER_MANAGEMENT_API_KEY", "synthetic-management-key")
    monkeypatch.setattr(job.openrouter_key_service, "list_openrouter_keys", Mock(return_value=list(keys)))
    monkeypatch.setattr(job, "_now", lambda: A_SUNDAY_THE_14TH)


def test_a_balance_that_lasts_under_a_week_warns_the_owner(monkeypatch, quiet_owner_email, caplog):
    spending(monkeypatch, {"usage_weekly": 60, "usage_monthly": 140})

    with caplog.at_level(logging.WARNING):
        code, _ = _run({"limit_remaining": 50}, monkeypatch)

    assert code == 1
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert quiet_owner_email.call_args.kwargs["remaining_usd"] == 50
    assert quiet_owner_email.call_args.kwargs["spend_per_day_usd"] == 10


def test_a_balance_that_lasts_under_two_days_is_critical(monkeypatch, quiet_owner_email, caplog):
    spending(monkeypatch, {"usage_weekly": 60, "usage_monthly": 140})

    with caplog.at_level(logging.ERROR):
        code, _ = _run({"limit_remaining": 15}, monkeypatch)

    assert code == 1
    assert "CRITICAL" in caplog.text
    quiet_owner_email.assert_called_once()


def test_a_long_runway_stays_quiet(monkeypatch, quiet_owner_email):
    spending(monkeypatch, {"usage_weekly": 7, "usage_monthly": 14})

    code, _ = _run({"limit_remaining": 100}, monkeypatch)

    assert code == 0
    quiet_owner_email.assert_not_called()


def test_a_small_balance_with_tiny_spending_does_not_nag(monkeypatch, quiet_owner_email):
    """The fixed warning line would email every day here, though the money lasts for years."""
    spending(monkeypatch, {"usage_weekly": 0.1, "usage_monthly": 0.1})

    code, _ = _run({"limit_remaining": 13.76}, monkeypatch)

    assert code == 0
    quiet_owner_email.assert_not_called()


def test_the_urgent_floor_holds_even_with_tiny_spending(monkeypatch, quiet_owner_email, caplog):
    spending(monkeypatch, {"usage_weekly": 0.1, "usage_monthly": 0.1})

    with caplog.at_level(logging.ERROR):
        code, _ = _run({"limit_remaining": 4}, monkeypatch)

    assert code == 1
    assert "CRITICAL" in caplog.text
    quiet_owner_email.assert_called_once()


def test_a_quiet_start_to_the_week_does_not_hide_real_spending(monkeypatch, quiet_owner_email):
    """usage_weekly restarts every Monday, so the month keeps the rate honest."""
    spending(monkeypatch, {"usage_weekly": 0, "usage_monthly": 140})

    code, _ = _run({"limit_remaining": 50}, monkeypatch)

    assert code == 1
    assert quiet_owner_email.call_args.kwargs["spend_per_day_usd"] == 10


def test_spending_is_added_across_every_key(monkeypatch, quiet_owner_email):
    spending(monkeypatch, {"usage_weekly": 35, "usage_monthly": 70}, {"usage_weekly": 35, "usage_monthly": 70})

    _run({"limit_remaining": 50}, monkeypatch)

    assert quiet_owner_email.call_args.kwargs["spend_per_day_usd"] == 10


def test_the_owner_is_emailed_once_a_day(monkeypatch, quiet_owner_email):
    spending(monkeypatch, {"usage_weekly": 60, "usage_monthly": 140})

    _run({"limit_remaining": 50}, monkeypatch)
    _run({"limit_remaining": 49}, monkeypatch)

    quiet_owner_email.assert_called_once()


def test_a_failed_email_is_tried_again(monkeypatch, quiet_owner_email):
    quiet_owner_email.return_value = False
    spending(monkeypatch, {"usage_weekly": 60, "usage_monthly": 140})

    _run({"limit_remaining": 50}, monkeypatch)
    _run({"limit_remaining": 49}, monkeypatch)

    assert quiet_owner_email.call_count == 2


def test_critical_is_emailed_even_after_a_warning_today(monkeypatch, quiet_owner_email):
    spending(monkeypatch, {"usage_weekly": 60, "usage_monthly": 140})

    _run({"limit_remaining": 50}, monkeypatch)
    _run({"limit_remaining": 15}, monkeypatch)

    assert quiet_owner_email.call_count == 2


def test_unreadable_spending_falls_back_to_the_fixed_lines_without_a_false_email(monkeypatch, quiet_owner_email):
    monkeypatch.setenv("OPENROUTER_MANAGEMENT_API_KEY", "synthetic-management-key")
    monkeypatch.setattr(job.openrouter_key_service, "list_openrouter_keys", Mock(side_effect=RuntimeError("down")))

    code, _ = _run({"limit_remaining": 13.76}, monkeypatch)

    assert code == 1
    quiet_owner_email.assert_not_called()


def test_unreadable_spending_still_emails_when_urgent(monkeypatch, quiet_owner_email):
    monkeypatch.setenv("OPENROUTER_MANAGEMENT_API_KEY", "synthetic-management-key")
    monkeypatch.setattr(job.openrouter_key_service, "list_openrouter_keys", Mock(side_effect=RuntimeError("down")))

    _run({"limit_remaining": 4}, monkeypatch)

    assert quiet_owner_email.call_args.kwargs["spend_per_day_usd"] is None


@pytest.mark.parametrize("listing", [[], [{"hash": "no-usage-fields"}], [{"usage_weekly": 9, "usage_monthly": 9, "disabled": True}]])
def test_a_listing_with_no_usable_spending_is_unreadable_not_zero(monkeypatch, listing):
    spending(monkeypatch, *listing)

    code, _ = _run({"limit_remaining": 13.76}, monkeypatch)

    assert code == 1


def test_disabled_keys_do_not_count_towards_the_rate(monkeypatch, quiet_owner_email):
    spending(monkeypatch, {"usage_weekly": 7000, "usage_monthly": 14000, "disabled": True},
             {"usage_weekly": 70, "usage_monthly": 140})

    _run({"limit_remaining": 50}, monkeypatch)

    assert quiet_owner_email.call_args.kwargs["spend_per_day_usd"] == 10


def test_the_balance_email_says_how_long_the_money_lasts(monkeypatch):
    from app.services import email_service

    monkeypatch.undo()
    monkeypatch.setenv("SMTP_SENDER_EMAIL", "noreply@example.test")
    monkeypatch.setenv("SMTP_APP_PASSWORD", "synthetic-password")
    monkeypatch.setenv("PLATFORM_ALERT_EMAIL", "owner@example.test")
    smtp = Mock()
    monkeypatch.setattr(email_service.smtplib, "SMTP", Mock(return_value=smtp))

    assert email_service.send_ai_balance_alert_email(remaining_usd=50, spend_per_day_usd=10) is True
    assert smtp.sendmail.call_args.args[1] == "owner@example.test"
    assert "about 5 days" in smtp.sendmail.call_args.args[2]


def test_job_is_registered_on_the_scheduler():
    """A monitor nobody runs is not a monitor."""
    from app.services import billing_scheduler_service as scheduler

    names = {name for name, _fn, _interval in scheduler.JOBS}
    assert "check_ai_provider_balance" in names
