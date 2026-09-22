from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import tuition_service as service
from app.database import tuition_repository as repository


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("TUITION_TRIALS_ENABLED", "true")
    monkeypatch.setattr(service, "get_report_context", lambda company, bot: {"bot": {
        "company_id": company, "id": bot,
        "industry_template_published": {"template_id": "tuition_center", "confirmed_at": "2026-09-22"}}})


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("TUITION_TRIALS_ENABLED", raising=False)
    with pytest.raises(service.TuitionError) as error:
        service.list_courses(company_id=10, chatbot_id=7)
    assert error.value.code == "tuition_disabled"


def test_other_industry_cannot_use_booking(enabled, monkeypatch):
    monkeypatch.setattr(service, "get_report_context", lambda *a: {"bot": {"company_id": 10,
        "id": 7, "industry_template_published": {"template_id": "clinic", "confirmed_at": "today"}}})
    with pytest.raises(service.TuitionError) as error:
        service.list_courses(company_id=10, chatbot_id=7)
    assert error.value.status_code == 403


@pytest.mark.parametrize("exception,status", [
    (service.AnalysisScopeDenied("not found"), 404),
    (service.AnalysisUnavailable("private storage failure"), 503),
])
def test_context_failure_is_safe_tuition_error(enabled, monkeypatch, exception, status):
    monkeypatch.setattr(service, "get_report_context", Mock(side_effect=exception))
    with pytest.raises(service.TuitionError) as error:
        service.list_courses(company_id=10, chatbot_id=7)
    assert error.value.status_code == status
    assert "private storage failure" not in str(error.value)


@pytest.mark.parametrize("start,end", [("2026-99-99", "2099-01-02T00:00:00Z"),
    ("2099-01-01T00:00:00", "2099-01-02T00:00:00Z"),
    ("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z"),
    ("2099-01-02T00:00:00Z", "2099-01-01T00:00:00Z")])
def test_session_requires_real_future_aware_dates(enabled, monkeypatch, start, end):
    write = Mock()
    monkeypatch.setattr(repository, "write_catalog", write)
    with pytest.raises(ValueError):
        service.create_session(company_id=10, chatbot_id=7, actor_user_id=3,
            class_id="00000000-0000-4000-8000-000000000001", starts_at=start, ends_at=end,
            total_capacity=5, trial_limit=2)
    write.assert_not_called()


@pytest.mark.parametrize("capacity,enrolled,limit", [(True, 0, 1), (0, 0, 0), (2, 3, 1), (2, 0, 3)])
def test_capacity_validation(enabled, capacity, enrolled, limit):
    with pytest.raises(ValueError):
        service.update_session_capacity(company_id=10, chatbot_id=7, actor_user_id=3,
            session_id="00000000-0000-4000-8000-000000000001", expected_version=1,
            total_capacity=capacity, enrolled_seats=enrolled, trial_limit=limit)


def test_confirmation_requires_token_not_model_boolean(enabled):
    with pytest.raises(TypeError):
        service.confirm_trial(company_id=10, chatbot_id=7, conversation_id=11, confirmed=True)


def test_public_confirmation_hides_identity_hash(enabled, monkeypatch):
    confirm = Mock(return_value={"booking": {"id": "b", "contact_key": "private", "confirmation_id": "private"}, "session": {"id": "s"}})
    monkeypatch.setattr(repository, "confirm_trial", confirm)
    result = service.confirm_trial(company_id=10, chatbot_id=7, conversation_id=11, confirmation_token="server-token")
    assert result == {"booking": {"id": "b"}, "session": {"id": "s"}}
    assert confirm.call_args.kwargs["conversation_id"] == 11


def test_repository_uses_one_rpc_for_confirm_and_does_not_fake_empty_success(monkeypatch):
    db = Mock()
    db.rpc.return_value.execute.return_value = SimpleNamespace(data=None)
    monkeypatch.setattr(repository, "supabase", db)
    with pytest.raises(repository.TuitionError):
        repository.confirm_trial(company_id=10, chatbot_id=7, conversation_id=11, confirmation_token="token")
    db.table.assert_not_called()
    assert db.rpc.call_args.args[0] == "tuition_confirm_trial"
    assert db.rpc.call_args.args[1]["p_actor_user_id"] is None


def test_reminder_consent_is_not_coerced_from_strings(enabled):
    with pytest.raises(ValueError):
        service.prepare_trial(company_id=10, chatbot_id=7, conversation_id=11,
            participant_id="p", session_id="s", reminder_consent="yes")
