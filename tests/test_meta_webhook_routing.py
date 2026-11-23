import hashlib
import hmac
import json
import logging
from unittest.mock import Mock, call

import pytest
from flask import Flask

from app import views
from app.database import (agent_action_repository, conversation_repository, message_repository,
                          processed_message_repository, whatsapp_channel_repository)


@pytest.fixture
def post():
    app = Flask(__name__)
    app.config["APP_SECRET"] = "synthetic-meta-test-secret"
    app.register_blueprint(views.webhook_blueprint)
    client = app.test_client()

    def deliver(payload, *, signed=True):
        raw = json.dumps(payload).encode()
        digest = hmac.new(app.config["APP_SECRET"].encode(), raw, hashlib.sha256).hexdigest()
        headers = {"X-Hub-Signature-256": "sha256=" + digest} if signed else {}
        return client.post("/webhook", data=raw, headers=headers, content_type="application/json")

    return deliver


def change(field, **value):
    return {"field": field, "value": value}


def entry(*changes):
    return {"id": "222", "changes": list(changes)}


def event(*entries):
    return {"object": "whatsapp_business_account", "entry": list(entries)}


def incoming(*customers):
    return change("messages", metadata={"phone_number_id": "111"},
                  contacts=[{"wa_id": customer} for customer in reversed(customers)],
                  messages=[{"from": customer, "id": "m-" + customer, "type": "text",
                             "text": {"body": "hello"}} for customer in customers])


def test_signed_batch_routes_every_message_with_its_customer_and_ignores_malformed(post, monkeypatch):
    process = Mock()
    monkeypatch.setattr(views, "process_whatsapp_message", process)
    payload = event(None, entry(None, incoming("301", "302")), {"changes": {}},
                    entry(change("messages", metadata=[]), incoming("303")))
    assert post(payload, signed=False).status_code == 403
    process.assert_not_called()
    assert post(payload).status_code == 200
    values = [call.args[0]["entry"][0]["changes"][0]["value"] for call in process.call_args_list]
    assert [(v["contacts"][0]["wa_id"], v["messages"][0]["id"]) for v in values] == [
        ("301", "m-301"), ("302", "m-302"), ("303", "m-303")]


@pytest.mark.parametrize("field", ["history", "smb_app_state_sync", "message_template_status_update", "future_field"])
def test_ignored_fields_acknowledged_and_only_field_logged(post, monkeypatch, caplog, field):
    process = Mock()
    monkeypatch.setattr(views, "process_whatsapp_message", process)
    with caplog.at_level(logging.INFO):
        response = post(event(entry(change(field, private_data="never-log-this"))))
    assert response.status_code == 200
    process.assert_not_called()
    assert sum(field in record.getMessage() for record in caplog.records) == 1
    assert "never-log-this" not in caplog.text


CHANNEL = {"id": 7, "chatbot_id": 8, "company_id": 9, "phone_number_id": "111",
           "whatsapp_business_account_id": "222", "is_active": True,
           "connection_status": "connected", "verified_at": "2026-01-01", "onboarding_type": "coexistence"}


def test_phone_echo_records_staff_transcript_and_handoff_once_without_dispatch(post, monkeypatch):
    from app.utils import whatsapp_utils

    lookup = Mock(return_value=CHANNEL)
    monkeypatch.setattr(whatsapp_channel_repository, "get_whatsapp_channel_by_phone_number_id", lookup)
    conversation = Mock(return_value={"id": 10, "chatbot_id": 8})
    monkeypatch.setattr(conversation_repository, "get_or_create_conversation", conversation)
    monkeypatch.setattr(processed_message_repository, "claim_processed_message", Mock(side_effect=[True, False]))
    monkeypatch.setattr(agent_action_repository, "get_open_conversation_escalations", Mock(return_value=[]))
    pause = Mock(return_value={"id": 16})
    monkeypatch.setattr(agent_action_repository, "save_agent_action", pause)
    save = Mock(return_value={"id": 17})
    monkeypatch.setattr(message_repository, "save_message", save)
    existing = Mock(return_value=None)
    monkeypatch.setattr(message_repository, "get_whatsapp_outbound_message", existing, raising=False)
    send = Mock()
    monkeypatch.setattr(whatsapp_utils, "send_message", send)
    inbound = Mock()
    monkeypatch.setattr(views, "process_whatsapp_message", inbound)
    echo = change("smb_message_echoes", metadata={"phone_number_id": "111"},
                  message_echoes=[{"from": "111", "to": "333", "id": "wamid.echo", "type": "text",
                                   "text": {"body": "A staff reply"}}])
    assert post(event(entry(echo, echo))).status_code == 200
    conversation.assert_called_once_with(chatbot_id=8, customer_phone="333", source_channel="whatsapp",
                                         source_channel_id=7, source_provider_id="111")
    pause.assert_called_once()
    assert pause.call_args.kwargs["intent"] == "handoff_request"
    assert pause.call_args.kwargs["conversation_id"] == 10
    assert pause.call_args.kwargs["company_id"] == 9
    save.assert_called_once_with(conversation_id=10, sender_type="bot", message_text="A staff reply",
                                 message_type="smb_message_echo", platform_message_id="wamid.echo",
                                 delivery_status="sent", ai_generated=False)
    inbound.assert_not_called()
    send.assert_not_called()


def test_partner_removed_routes_number_or_waba_and_checks_ownership(post, monkeypatch):
    lookup = Mock(return_value=CHANNEL)
    monkeypatch.setattr(whatsapp_channel_repository, "get_whatsapp_channel_by_phone_number_id", lookup)
    by_waba = Mock(return_value=[CHANNEL, {**CHANNEL, "id": 11}])
    monkeypatch.setattr(whatsapp_channel_repository, "get_connected_whatsapp_channels_by_waba_id", by_waba, raising=False)
    disconnect = Mock(return_value={"id": 7})
    monkeypatch.setattr(whatsapp_channel_repository, "disconnect_whatsapp_channel", disconnect)
    removed = change("account_update", metadata={"phone_number_id": "111"}, event="PARTNER_REMOVED")
    assert post(event(entry(removed), {**entry(removed), "id": "wrong-waba"},
                      entry(change("account_update", event="PARTNER_REMOVED")),
                      entry(change("account_update", event="PARTNER_ADDED")))).status_code == 200
    by_waba.assert_called_once_with("222")
    assert disconnect.call_args_list == [call(7), call(7), call(11)]


def test_a_late_partner_removed_event_never_ends_a_newer_connection(post, monkeypatch):
    reconnected = {**CHANNEL, "verified_at": "2026-11-23T12:00:00+00:00"}
    monkeypatch.setattr(whatsapp_channel_repository, "get_whatsapp_channel_by_phone_number_id",
                        Mock(return_value=reconnected))
    disconnect = Mock(return_value={"id": 7})
    monkeypatch.setattr(whatsapp_channel_repository, "disconnect_whatsapp_channel", disconnect)
    removed = change("account_update", metadata={"phone_number_id": "111"}, event="PARTNER_REMOVED")
    before_reconnect = 1795431600  # 2026-11-23T11:00:00Z, an hour before the new connection was verified
    after_reconnect = 1795438800   # 2026-11-23T13:00:00Z
    assert post(event({**entry(removed), "time": before_reconnect})).status_code == 200
    disconnect.assert_not_called()
    assert post(event({**entry(removed), "time": after_reconnect})).status_code == 200
    disconnect.assert_called_once_with(7)


def test_delivery_statuses_are_scoped_and_do_not_trigger_inbound_processing(post, monkeypatch):
    monkeypatch.setattr(whatsapp_channel_repository, "get_whatsapp_channel_by_phone_number_id",
                        Mock(return_value=CHANNEL))
    update = Mock()
    monkeypatch.setattr(message_repository, "advance_whatsapp_delivery_status", update, raising=False)
    process = Mock()
    monkeypatch.setattr(views, "process_whatsapp_message", process)
    receipts = change("messages", metadata={"phone_number_id": "111"}, statuses=[
        {"id": "outbound-id", "status": "delivered"}, {"id": "outbound-id", "status": "read"},
        {"id": "outbound-id", "status": "future"}, None])
    assert post(event(entry(receipts), {**entry(receipts), "id": "wrong-waba"})).status_code == 200
    assert update.call_args_list == [call(CHANNEL, "outbound-id", "delivered"), call(CHANNEL, "outbound-id", "read")]
    process.assert_not_called()


@pytest.mark.parametrize("existing", [None, {"id": 10, "platform_user_id": None}])
def test_whatsapp_conversation_writes_wa_id_for_new_and_existing(monkeypatch, existing):
    monkeypatch.setattr(conversation_repository, "find_open_conversation", Mock(return_value=existing))
    table = Mock()
    monkeypatch.setattr(conversation_repository.supabase, "table", Mock(return_value=table))
    if existing:
        table.update.return_value.eq.return_value.execute.return_value.data = [existing]
    else:
        table.insert.return_value.execute.return_value.data = [{"id": 10}]
    conversation_repository.get_or_create_conversation(
        chatbot_id=8, customer_phone="333", source_channel="whatsapp", source_channel_id=7, source_provider_id="111")
    persisted = (table.update if existing else table.insert).call_args.args[0]
    assert persisted["platform_user_id"] == "333"


def test_echo_transcript_failure_releases_claim_and_reuses_handoff_on_retry(post, monkeypatch):
    monkeypatch.setattr(whatsapp_channel_repository, "get_whatsapp_channel_by_phone_number_id", lambda _: CHANNEL)
    monkeypatch.setattr(conversation_repository, "get_or_create_conversation", lambda **_: {"id": 10})
    monkeypatch.setattr(processed_message_repository, "claim_processed_message", lambda *_: True)
    release = Mock()
    monkeypatch.setattr(processed_message_repository, "release_processed_message_claim", release)
    monkeypatch.setattr(agent_action_repository, "get_open_conversation_escalations",
                        Mock(side_effect=[[], [{"id": 16}]]))
    pause = Mock(return_value={"id": 16})
    monkeypatch.setattr(agent_action_repository, "save_agent_action", pause)
    monkeypatch.setattr(message_repository, "get_whatsapp_outbound_message", lambda *_: None)
    save = Mock(side_effect=[RuntimeError("transient"), {"id": 17}])
    monkeypatch.setattr(message_repository, "save_message", save)
    payload = event(entry(change("smb_message_echoes", metadata={"phone_number_id": "111"},
                                 message_echoes=[{"id": "m-2", "type": "image", "to": "333"}])))
    assert post(payload).status_code == 500
    release.assert_called_once_with(8, "m-2")
    assert post(payload).status_code == 200
    pause.assert_called_once()
    assert save.call_count == 2


@pytest.mark.parametrize("status,allowed", [("read", ["sent", "delivered"]), ("delivered", ["sent"]), ("failed", ["sent"])])
def test_status_storage_checks_channel_tenant_and_prior_delivery_status(monkeypatch, status, allowed):
    table = Mock()
    for method in ("eq", "in_", "limit", "select", "update"):
        getattr(table, method).return_value = table
    table.execute.return_value.data = [{"id": 45, "conversation_id": 46}]
    monkeypatch.setattr(message_repository.supabase, "table", Mock(return_value=table))
    message_repository.advance_whatsapp_delivery_status(CHANNEL, "m-3", status)
    assert call("conversations.chatbots.company_id", 9) in table.eq.call_args_list
    assert call("conversations.source_channel_id", 7) in table.eq.call_args_list
    assert call("conversations.source_provider_id", "111") in table.eq.call_args_list
    assert call("conversations.chatbot_id", 8) in table.eq.call_args_list
    assert call("sender_type", "bot") in table.eq.call_args_list
    assert call("id", 45) in table.eq.call_args_list
    assert call("conversation_id", 46) in table.eq.call_args_list
    table.update.assert_called_once_with({"delivery_status": status})
    table.in_.assert_called_once_with("delivery_status", allowed)
