"""Tests for the shared AI provider credit monitor.

The job exists because one USD balance funds every pooled tenant, so the cases
that matter most are the ones where a naive implementation would either cry wolf
(an uncapped key, a network blip) or stay silent when it should not.
"""

import logging
from unittest.mock import Mock, patch

import pytest

from app.jobs import check_ai_provider_balance as job


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


def test_job_is_registered_on_the_scheduler():
    """A monitor nobody runs is not a monitor."""
    from app.services import billing_scheduler_service as scheduler

    names = {name for name, _fn, _interval in scheduler.JOBS}
    assert "check_ai_provider_balance" in names
