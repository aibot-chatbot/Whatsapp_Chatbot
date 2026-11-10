"""Offline evidence, single-call billing and opt-in contracts for observations."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.database import business_observation_repository as repository
from app.database.analysis_repository import AnalysisScopeDenied, AnalysisUnavailable
from app.services import business_observation_service as service
from app.services.industry_template_catalog import TEMPLATE_VERSION


@pytest.fixture
def setup(monkeypatch):
    operational = Mock(return_value={"status": "active"})
    feature = Mock(return_value=True)
    monkeypatch.setattr(service, "ensure_company_operational", operational)
    monkeypatch.setattr(service, "can_use_plan_feature", feature)
    event = {"id": 100, "event_type": "business_observation", "worker_kind": "business_observation",
             "company_id": 10, "chatbot_id": 7, "lease_token": "00000000-0000-4000-8000-000000000001",
             "payload": {"message_id": 21}}
    source = {"status": "running", "company_id": 10, "chatbot_id": 7,
              "message": {"id": 21, "conversation_id": 11, "text": "Please book a table for two"}, "model_started": False}
    context = {"bot": {"id": 7, "company_id": 10, "industry_template_published": {
        "template_id": "restaurant", "template_version": TEMPLATE_VERSION,
        "confirmed_by": 3, "confirmed_at": "2026-09-01T00:00:00Z"}},
        "settings": {"business_description": "Unique family restaurant Bot"}}
    calls = []
    def apply(**kwargs):
        calls.append(kwargs["operation"])
        if kwargs["operation"] == "inspect":
            return deepcopy(source)
        if kwargs["operation"] == "start":
            return {"started": True}
        if kwargs["operation"] == "uncertain":
            return {"status": "needs_review"}
        return {"status": "completed", "result": {"model_state": "succeeded"}}
    apply_mock = Mock(side_effect=apply)
    monkeypatch.setattr(service.repository, "apply_observation", apply_mock)
    context_mock = Mock(side_effect=lambda *args: deepcopy(context))
    monkeypatch.setattr(service.analysis_repository, "get_report_context", context_mock)
    import app.services.ai_router as router
    def generate(**kwargs):
        assert calls[-1] == "start", "provider must never run before the durable start"
        calls.append("provider")
        return json.dumps({"action_type": "booking", "status": "requested", "evidence_quote": "book a table"})
    model = Mock(side_effect=generate)
    monkeypatch.setattr(router, "generate_system_response", model)
    return SimpleNamespace(event=event, source=source, context=context, calls=calls,
                           apply=apply_mock, model=model, context_mock=context_mock, operational=operational, feature=feature)


def test_durable_start_precedes_exactly_one_billed_call_and_no_raw_result(setup):
    assert service.process_business_observation(setup.event)["status"] == "completed"
    assert setup.calls == ["inspect", "start", "provider", "finish"]
    assert setup.model.call_count == 1
    kwargs = setup.model.call_args.kwargs
    assert kwargs["chatbot_id"] == 7 and kwargs["operation_type"] == "ai_report"
    assert kwargs["json_response"] is True
    assert "Unique family restaurant Bot" in kwargs["prompt"]
    assert '"id": "restaurant"' in kwargs["prompt"]
    result = setup.apply.call_args.kwargs["output"]
    assert result == {"action_type": "booking", "status": "requested", "industry_id": "restaurant", "context_truncated": False}
    assert "evidence_quote" not in result


@pytest.mark.parametrize("state", [{"status": "completed"}, {"status": "needs_review"}, {"status": "running", "model_started": True}])
def test_replays_never_call_provider(setup, state):
    setup.source.update(state)
    if state["status"] == "completed":
        assert service.process_business_observation(setup.event)["status"] == "completed"
    else:
        with pytest.raises(service.AnalysisNeedsReview):
            service.process_business_observation(setup.event)
    setup.model.assert_not_called()
    assert setup.calls == ["inspect"]


@pytest.mark.parametrize("mutate", [
    lambda f: f.event.update(worker_kind="n8n"),
    lambda f: f.event.update(company_id=20),
    lambda f: f.event.update(chatbot_id=8),
    lambda f: f.source["message"].update(id=22),
    lambda f: f.event.update(payload={"message_id": "21"}),
    lambda f: f.context["bot"].update(company_id=20),
])
def test_trusted_message_tenant_bot_must_match_before_model(setup, mutate):
    mutate(setup)
    with pytest.raises(service.AnalysisReportError):
        service.process_business_observation(setup.event)
    setup.model.assert_not_called()
    assert "start" not in setup.calls


@pytest.mark.parametrize("text", ["Hi!", "你好", "terima kasih", "谢谢。", "Okay"])
def test_only_exact_obvious_greetings_skip_cost(setup, text):
    setup.source["message"]["text"] = text
    assert service.process_business_observation(setup.event)["status"] == "completed"
    assert setup.calls == ["inspect", "skip"]
    setup.context_mock.assert_not_called()
    setup.model.assert_not_called()


@pytest.mark.parametrize("text,quote,action", [
    ("你好，我要预约晚餐", "预约晚餐", "booking"),
    ("Saya mahu daftar kelas", "daftar kelas", "registration"),
    ("Hello, please order lunch", "order lunch", "order"),
    ("Can I request cleaning services?", "request cleaning services", "service_request"),
])
def test_multilingual_grounded_requests_are_observations_only(setup, text, quote, action):
    setup.source["message"]["text"] = text
    setup.model.side_effect = None
    setup.model.return_value = json.dumps({"action_type": action, "status": "intent", "evidence_quote": quote})
    service.process_business_observation(setup.event)
    assert setup.apply.call_args.kwargs["output"]["status"] == "intent"


def test_negated_request_can_produce_no_record(setup):
    setup.source["message"]["text"] = "I do not want to book"
    setup.model.side_effect = None
    setup.model.return_value = '{"action_type":"none","status":"none","evidence_quote":""}'
    service.process_business_observation(setup.event)
    assert setup.apply.call_args.kwargs["output"]["action_type"] == "none"


@pytest.mark.parametrize("raw", [
    "not JSON", '{"action_type":"booking","status":"confirmed","evidence_quote":"book"}',
    '{"action_type":"registration","status":"completed","evidence_quote":"book"}',
    '{"action_type":"booking","status":"requested","evidence_quote":"not present"}',
    '{"action_type":"booking","status":"requested","evidence_quote":"book","company_id":20}',
    '{"action_type":"none","status":"requested","evidence_quote":""}',
])
def test_invalid_or_ungrounded_model_result_requires_review_without_retry(setup, raw):
    setup.model.side_effect = None
    setup.model.return_value = raw
    with pytest.raises(service.AnalysisNeedsReview):
        service.process_business_observation(setup.event)
    assert setup.model.call_count == 1
    assert setup.calls == ["inspect", "start", "uncertain"]


def test_timeout_keeps_ambiguous_paid_call_for_review(setup):
    setup.model.side_effect = TimeoutError("provider may already have charged")
    with pytest.raises(service.AnalysisNeedsReview):
        service.process_business_observation(setup.event)
    assert setup.model.call_count == 1 and setup.calls[-1] == "uncertain"


def test_lost_finish_ack_never_causes_another_provider_call(setup):
    normal = setup.apply.side_effect
    def apply(**kwargs):
        if kwargs["operation"] == "finish":
            raise TimeoutError("unknown database commit")
        return normal(**kwargs)
    setup.apply.side_effect = apply
    with pytest.raises(service.AnalysisNeedsReview):
        service.process_business_observation(setup.event)
    assert setup.model.call_count == 1 and setup.calls[-1] == "uncertain"


@pytest.mark.parametrize("operation", ["inspect", "start", "finish"])
def test_disabled_setting_can_settle_at_each_boundary(setup, operation):
    normal = setup.apply.side_effect
    def apply(**kwargs):
        if kwargs["operation"] == operation:
            setup.calls.append(operation)
            return {"status": "completed", "result": {"reason": "recording_disabled"}}
        return normal(**kwargs)
    setup.apply.side_effect = apply
    result = service.process_business_observation(setup.event)
    assert result["result"]["reason"] == "recording_disabled"
    assert setup.model.call_count == (1 if operation == "finish" else 0)


def test_clinic_only_administrative_cues_reach_classifier(setup):
    setup.context["bot"]["industry_template_published"]["template_id"] = "clinic"
    setup.context["settings"].update(additional_instructions="Patient Alice has cancer", custom_prompt="Secret record")
    setup.source["message"]["text"] = "My name is Alice, cancer diagnosis. Please book appointment. alice@test.example +60123456789"
    setup.model.side_effect = None
    setup.model.return_value = '{"action_type":"booking","status":"requested","evidence_quote":"book"}'
    service.process_business_observation(setup.event)
    prompt = setup.model.call_args.kwargs["prompt"]
    for hidden in ("Alice", "cancer", "diagnosis", "alice@test", "+60123456789", "Secret record"):
        assert hidden not in prompt
    assert "appointment" in prompt


def test_clinic_non_administrative_message_does_not_call_model(setup):
    setup.context["bot"]["industry_template_published"]["template_id"] = "clinic"
    setup.source["message"]["text"] = "My medical history contains sensitive information"
    service.process_business_observation(setup.event)
    assert setup.calls == ["inspect", "skip"]
    setup.model.assert_not_called()


@pytest.mark.parametrize("text", ["I don't want to book", "I do not need an appointment", "我不要预约", "我不想挂号", "Saya tidak mahu temujanji", "Jangan daftar", "My appointment was already confirmed"])
def test_clinic_negation_or_past_success_is_never_stripped_into_a_request(setup, text):
    setup.context["bot"]["industry_template_published"]["template_id"] = "clinic"
    setup.source["message"]["text"] = text
    service.process_business_observation(setup.event)
    assert setup.calls == ["inspect", "skip"]
    setup.model.assert_not_called()


@pytest.mark.parametrize("boundary", [1, 2, 3])
@pytest.mark.parametrize("guard", ["operational", "feature"])
def test_current_company_and_plan_checked_before_inspect_start_and_publication(setup, boundary, guard):
    from app.services.billing_guard import BillingLimitError
    from app.services.company_status_service import CompanyOperationalStatusError
    error = (BillingLimitError("Plan no longer allows reports") if guard == "feature"
             else CompanyOperationalStatusError("company_suspended", "Company suspended"))
    # _authorize makes one operational call and two plan calls (report data +
    # automation_workflows) per boundary; fail the boundary-th authorization.
    calls_per_boundary = 2 if guard == "feature" else 1
    getattr(setup, guard).side_effect = [True] * (calls_per_boundary * (boundary - 1)) + [error]
    expected = service.AnalysisNeedsReview if boundary == 3 else type(error)
    with pytest.raises(expected):
        service.process_business_observation(setup.event)
    assert setup.model.call_count == (1 if boundary == 3 else 0)
    assert "finish" not in setup.calls
    if boundary == 3:
        assert setup.calls[-1] == "uncertain"


def test_long_message_is_bounded_and_explicitly_marked(setup):
    setup.source["message"]["text"] += " abc" * 1500
    service.process_business_observation(setup.event)
    assert setup.apply.call_args.kwargs["output"]["context_truncated"] is True
    assert " abc" * 1500 not in setup.model.call_args.kwargs["prompt"]


def test_settings_tenant_filters_and_write_verified(monkeypatch):
    query = Mock()
    for method in ("select", "update", "eq", "is_", "neq", "limit"):
        getattr(query, method).return_value = query
    query.execute.return_value.data = [{"id": 7, "company_id": 10, "analysis_recording_enabled": True}]
    client = Mock()
    client.table.return_value = query
    monkeypatch.setattr(repository, "supabase", client)
    assert repository.get_recording_enabled(10, 7) is True
    assert repository.set_recording_enabled(10, 7, True) is True
    assert ("company_id", 10) in [call.args for call in query.eq.call_args_list]
    assert ("id", 7) in [call.args for call in query.eq.call_args_list]
    query.execute.return_value.data[0]["company_id"] = 20
    with pytest.raises(AnalysisUnavailable):
        repository.get_recording_enabled(10, 7)
    with pytest.raises(AnalysisUnavailable):
        repository.set_recording_enabled(10, 7, True)


@pytest.mark.parametrize("company,bot", [(None, 7), (10, None), (True, 7), (10, -1)])
def test_settings_require_explicit_tenant(company, bot):
    with pytest.raises(AnalysisScopeDenied):
        repository.get_recording_enabled(company, bot)


def test_settings_do_not_coerce_opt_in_values():
    with pytest.raises(ValueError):
        repository.set_recording_enabled(10, 7, "true")


def test_observation_requires_automation_workflows_before_inspect(setup):
    from app.services.billing_guard import BillingLimitError

    def gate(_company_id, key):
        if key == "automation_workflows":
            raise BillingLimitError("Not on this plan", code="feature_not_available")
        return True

    setup.feature.side_effect = gate
    with pytest.raises(BillingLimitError):
        service.process_business_observation(setup.event)
    assert setup.calls == []
    setup.model.assert_not_called()


def test_prompt_names_every_industry_booking_and_order_example(setup):
    service.process_business_observation(setup.event)
    prompt = setup.model.call_args.kwargs["prompt"]
    for example in ("salon appointments", "property viewings", "workshop service appointments",
                    "travel package bookings", "retail product orders"):
        assert example in prompt


def test_new_industry_bot_records_its_catalog_industry(setup):
    setup.context["bot"]["industry_template_published"]["template_id"] = "beauty_salon"
    assert service.process_business_observation(setup.event)["status"] == "completed"
    assert setup.apply.call_args.kwargs["output"]["industry_id"] == "beauty_salon"
    assert '"id": "beauty_salon"' in setup.model.call_args.kwargs["prompt"]


def test_unknown_industry_is_recorded_as_general(setup):
    # An older worker image, or a retired ID, must degrade to general and still record.
    setup.context["bot"]["industry_template_published"]["template_id"] = "hotel"
    assert service.process_business_observation(setup.event)["status"] == "completed"
    assert setup.apply.call_args.kwargs["output"]["industry_id"] == "general"


@pytest.mark.parametrize("text", ["where to buy syabu", "saya nak bunuh diri"])
def test_text_the_safety_check_stops_is_skipped_before_any_classifier_call(setup, monkeypatch, text):
    # Filter 1 (plan A3): the classifier is an AI call, so flagged customer text never reaches it.
    from app.services import content_filter
    monkeypatch.setattr(content_filter, "industry_for_bot", Mock(return_value="restaurant"))
    setup.source["message"]["text"] = text
    assert service.process_business_observation(setup.event)["status"] == "completed"
    assert setup.calls == ["inspect", "skip"]
    setup.model.assert_not_called()
