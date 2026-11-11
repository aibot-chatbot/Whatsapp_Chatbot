"""Nightly review per Client (plan A5): one email to the platform owner with each Client's flags.

The database and email are mocked. The report carries counts only, never customer text.
"""
from unittest.mock import Mock

import pytest

from app.database import agent_action_repository
from app.jobs import review_content_flags as job
from app.services import billing_scheduler_service, email_service


def row(company_id, category, *, mode=None, filter=1, source="customer"):
    flag = {"filter": filter, "category": category, "rule": "x", "source": source, **({"mode": mode} if mode else {})}
    return {"company_id": company_id, "payload": {"content_flag": flag}}


@pytest.fixture
def mail(monkeypatch):
    sent = Mock(return_value=True)
    monkeypatch.setattr(email_service, "_send_platform_alert", sent)
    return sent


def test_one_email_lists_each_client_with_stopped_and_review_only_counts(monkeypatch, mail):
    rows = [row(1, "drugs"), row(1, "drugs"), row(1, "threat", filter=2, mode="log"),
            row(2, "self_harm"), row(2, "adult", source="document")]
    lookup = Mock(return_value=rows)
    monkeypatch.setattr(agent_action_repository, "get_content_flags_since", lookup, raising=False)

    assert job.main([]) == 0

    subject, lines = mail.call_args.args
    text = "\n".join(lines)
    assert "2 Clients" in subject
    assert "Company 1: stopped 2 (drugs 2); review only 1 (threat 1)" in text
    assert "Company 2: stopped 1 (adult 1); self-harm 1" in text
    assert lookup.call_args.kwargs["since"].endswith("+00:00")


def test_a_quiet_day_sends_nothing(monkeypatch, mail):
    monkeypatch.setattr(agent_action_repository, "get_content_flags_since", Mock(return_value=[]), raising=False)

    assert job.main([]) == 0
    mail.assert_not_called()


def test_a_failed_lookup_reports_failure_without_raising(monkeypatch, mail):
    monkeypatch.setattr(agent_action_repository, "get_content_flags_since",
                        Mock(side_effect=RuntimeError("database down")), raising=False)

    assert job.main([]) == 1
    mail.assert_not_called()


def test_the_review_runs_once_a_day_on_the_billing_scheduler():
    jobs = {name: interval for name, _job, interval in billing_scheduler_service.JOBS}

    assert jobs.get("review_content_flags") == 24 * 3600
