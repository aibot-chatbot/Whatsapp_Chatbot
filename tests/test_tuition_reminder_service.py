from contextlib import contextmanager
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from app.services import tuition_reminder_service as reminders
from app.services.billing_guard import BillingLimitError


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("TUITION_TRIALS_ENABLED","true")
    monkeypatch.setenv("TUITION_REMINDERS_ENABLED","true")
    token=str(uuid4())
    event={"id":8,"company_id":1,"chatbot_id":2,"event_type":"tuition_reminder","worker_kind":"tuition_reminder",
           "lease_token":token,"payload":{"conversation_id":3}}
    context={"status":"ready","company_id":1,"chatbot_id":2,"starts_at":"2026-09-30T02:00:00+00:00",
             "class_name":"Math trial","conversation":{"id":3,"chatbot_id":2,"source_channel":"telegram",
              "source_channel_id":4,"source_provider_id":"12","platform_user_id":"123"}}
    state={"locked":False,"calls":[]}
    @contextmanager
    def lock(identifier):
        assert identifier==3
        state["locked"]=True
        try:yield
        finally:state["locked"]=False
    def apply(**kwargs):
        assert state["locked"]
        state["calls"].append(kwargs["operation"])
        if kwargs["operation"]=="inspect":return context
        if kwargs["operation"]=="begin":return {**context,"started":True}
        return {"status":"needs_review" if kwargs["operation"]=="uncertain" else "completed"}
    def send(*_args,**_kwargs):
        assert state["locked"] and state["calls"][-1]=="begin"
        return {"ok":True,"result":{"message_id":41,"chat":{"id":123}}}
    with patch.object(reminders,"get_automation_event_by_id",return_value=event),patch.object(
        reminders,"conversation_delivery_lock",side_effect=lock),patch.object(reminders.repository,"apply_reminder",side_effect=apply) as rpc,patch.object(
        reminders,"ensure_company_operational") as company,patch.object(reminders,"can_use_plan_feature") as plan,patch.object(
        reminders,"get_bound_channel",return_value={"company_id":1,"bot_token":"synthetic-bot-token"}) as channel,patch(
        "app.utils.telegram_utils.send_telegram_message",side_effect=send) as sender:
        yield event,context,state,rpc,company,plan,channel,sender


def execute(setup):
    event=setup[0]
    return reminders.execute_tuition_reminder(event_id=event["id"],lease_token=event["lease_token"])


def test_telegram_reminder_is_fenced_then_sent_under_shared_lock(setup):
    assert execute(setup)["status"]=="completed"
    assert setup[2]["calls"]==["inspect","begin","finish"]
    setup[5].assert_called_once_with(1,"ai_generated_reports")
    assert setup[7].call_args.args[1]=="123"
    assert "30 Sep 2026, 10:00" in setup[7].call_args.args[2]
    assert setup[7].call_args.kwargs=={"parse_mode":None}
    assert setup[3].call_args.kwargs["output"]["provider_message_id"]=="41"


@pytest.mark.parametrize("result",[None,{"ok":False},{"ok":True,"result":{"message_id":41,"chat":{"id":999}}}])
def test_uncertain_or_wrong_provider_receipt_is_never_retried(setup,result):
    setup[7].side_effect=None
    setup[7].return_value=result
    assert execute(setup)["status"]=="needs_review"
    assert setup[2]["calls"]==["inspect","begin","uncertain"]
    setup[7].assert_called_once()


def test_transport_timeout_needs_review(setup):
    setup[7].side_effect=TimeoutError("provider request uncertain")
    assert execute(setup)["status"]=="needs_review"
    setup[7].assert_called_once()


def test_downgraded_plan_skips_before_durable_send_marker(setup):
    setup[5].side_effect=BillingLimitError("No access")
    assert execute(setup)["status"]=="completed"
    assert setup[2]["calls"]==["inspect","skip"]
    setup[7].assert_not_called()


def test_missing_tenant_binding_never_calls_provider(setup):
    setup[1]["company_id"]=99
    with pytest.raises(reminders.TuitionError):execute(setup)
    setup[7].assert_not_called()


@pytest.mark.parametrize("source",["web","whatsapp","wasender"])
def test_other_channels_are_explicitly_skipped(setup,source):
    setup[1]["conversation"]["source_channel"]=source
    assert execute(setup)["status"]=="completed"
    setup[7].assert_not_called()


def test_changed_booking_on_begin_does_not_send(setup):
    context=setup[1]
    setup[3].side_effect=[context,{"status":"completed","result":{"delivery_status":"skipped"}}]
    assert execute(setup)["status"]=="completed"
    setup[7].assert_not_called()


def test_disabled_reminders_do_not_read_or_send(setup,monkeypatch):
    monkeypatch.setenv("TUITION_REMINDERS_ENABLED","false")
    with pytest.raises(reminders.TuitionError):execute(setup)
    setup[3].assert_not_called()
    setup[7].assert_not_called()


def test_old_or_wrong_lease_never_reaches_database_send_admission(setup):
    with pytest.raises(reminders.TuitionError):
        reminders.execute_tuition_reminder(event_id=8,lease_token=str(uuid4()))
    setup[3].assert_not_called()
    setup[7].assert_not_called()


def test_worker_bridge_only_transmits_trusted_identifiers(setup,monkeypatch):
    monkeypatch.setenv("FLASK_AGENT_BASE_URL","https://approved.invalid")
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN","synthetic-token-for-test-only-123456")
    response=Mock(content=b"{}")
    response.json.return_value={"data":{"status":"completed"}}
    with patch.object(reminders.httpx,"Client") as transport:
        transport.return_value.__enter__.return_value.post.return_value=response
        assert reminders.process_tuition_reminder(setup[0])=={"status":"completed"}
    assert transport.return_value.__enter__.return_value.post.call_args.kwargs["json"]=={
        "event_id":8,"lease_token":setup[0]["lease_token"]}
    assert transport.call_args.kwargs["follow_redirects"] is False
