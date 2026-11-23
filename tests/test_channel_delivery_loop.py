"""Mocked checks for immutable channel routing and truthful delivery."""
import inspect
from unittest.mock import Mock

import pytest
from flask import Flask

from app.routes import agent_routes
from app.services import channel_delivery_service as delivery
from app.utils import telegram_utils, whatsapp_utils
from app.services import ai_router


@pytest.mark.usefixtures("handed_over_staff_chat")
@pytest.mark.parametrize("source,identity", [("telegram", "telegram_bot_id"), ("whatsapp", "phone_number_id"), ("whatsapp_link", "phone_number")])
@pytest.mark.parametrize("fault,code", [("unbound", "CHANNEL_IDENTITY_UNVERIFIED"), ("replaced", "CHANNEL_REPLACED"), ("disconnected", "CHANNEL_NOT_CONNECTED"), ("unverified", "CHANNEL_IDENTITY_UNVERIFIED")])
def test_staff_reply_never_uses_replacement_or_unverified_channel(monkeypatch, source, identity, fault, code):
    conversation = {"id": 2, "chatbot_id": 3, "source_channel": source, "source_channel_id": 4, "source_provider_id": "old", "customer_phone": "123", "platform_user_id": "123"}
    row = {"id": 4, "chatbot_id": 3, identity: "old", "is_active": True, "connection_status": "connected", "verified_at": "2026-09-14T00:00:00Z"}
    if fault == "unbound":
        conversation["source_channel_id"] = None
    elif fault == "replaced":
        row[identity] = "new"
    elif fault == "disconnected":
        row["connection_status"] = "disconnected"
    else:
        row["verified_at"] = None
    monkeypatch.setattr(delivery, ("get_linked_channel" if source == "whatsapp_link" else f"get_{source}_channel_by_id"), Mock(return_value=row))
    monkeypatch.setattr(agent_routes, "get_conversation_by_id_and_chatbot", Mock(return_value=conversation))
    monkeypatch.setattr(agent_routes, "verify_chatbot_access", Mock(return_value={"company_id": 1}))
    senders = [Mock() for _ in range(3)]
    for name, sender in zip(("send_telegram_message", "send_whatsapp_message"), senders):
        monkeypatch.setattr(agent_routes, name, sender)
    monkeypatch.setattr("app.services.channel_server_service.send_text", senders[-1])
    save = Mock()
    monkeypatch.setattr(agent_routes, "save_message", save)
    with Flask(__name__).test_request_context(json={"chatbot_id": 3, "text": "Reply"}):
        response, status = inspect.unwrap(agent_routes.agent_reply)(2)
    assert status == 409
    assert response.json["code"] == code
    assert not any(sender.called for sender in senders)
    save.assert_not_called()


@pytest.mark.parametrize("source,result", [("telegram", None), ("telegram", {"ok": False}), ("whatsapp", (None, 408)), ("whatsapp", Mock(status_code=200, json=Mock(return_value={"error": {}})))])
def test_delivery_requires_provider_acceptance(source, result):
    assert delivery.delivery_accepted(source, result) is False


@pytest.mark.parametrize("source", ["telegram", "whatsapp", "whatsapp_link"])
@pytest.mark.parametrize("replaced", [True, False])
def test_inactive_original_reports_replacement_without_returning_new_channel(monkeypatch, source, replaced):
    row = {"id": 4, "chatbot_id": 3, delivery.PROVIDER_FIELDS[source]: "old", "is_active": False,
           "connection_status": "disconnected", "verified_at": "2026-09-14"}
    monkeypatch.setattr(delivery, ("get_linked_channel" if source == "whatsapp_link" else f"get_{source}_channel_by_id"), Mock(return_value=row))
    current = [{**row, "id": 5, delivery.PROVIDER_FIELDS[source]: "new", "is_active": True, "connection_status": "connected"}] if replaced else []
    monkeypatch.setattr(delivery, ("list_linked_channels" if source == "whatsapp_link" else f"get_{source}_channels_by_chatbot"), Mock(return_value=current))
    with pytest.raises(delivery.ChannelDeliveryError) as error:
        delivery.get_bound_channel({"chatbot_id": 3, "source_channel": source, "source_channel_id": 4, "source_provider_id": "old"})
    assert error.value.code == ("CHANNEL_REPLACED" if replaced else "CHANNEL_NOT_CONNECTED")


def _inbound(monkeypatch, source, *, send_result=None, paused=False, text="Hello"):
    row = {"id": 4, "chatbot_id": 3, "company_id": 1, "telegram_bot_id": "55", "phone_number_id": "55",
           "provider_user_id": "55", "is_active": True, "connection_status": "connected", "verified_at": "2026-09-14T00:00:00Z",
           "bot_token": "synthetic-token", "access_token": "synthetic-token", "api_key": "synthetic-key"}
    conversation = {"id": 8, "chatbot_id": 3, "source_channel": source, "source_channel_id": 4, "source_provider_id": "55", "customer_phone": "12345"}
    modules = {"telegram": telegram_utils, "whatsapp": whatsapp_utils}
    module = modules[source]
    monkeypatch.setattr(delivery, ("get_linked_channel" if source == "whatsapp_link" else f"get_{source}_channel_by_id"), Mock(return_value=row))
    lookup = "get_whatsapp_channel_by_phone_number_id" if source == "whatsapp" else f"get_{source}_channel_by_secret"
    monkeypatch.setattr(module, lookup, Mock(return_value=row))
    create = "get_or_create_platform_conversation" if source == "telegram" else "get_or_create_conversation"
    monkeypatch.setattr(module, create, Mock(return_value=conversation))
    monkeypatch.setattr(module, "is_conversation_escalated", Mock(return_value=paused))
    monkeypatch.setattr(module, "dispatch_media_after_reply", Mock())
    monkeypatch.setattr(module, "get_bot_by_id", Mock(return_value={}))
    if source == "whatsapp":
        monkeypatch.setattr(module, "update_workflow_state", Mock())
    claim_name = {"telegram": "claim_telegram_update", "whatsapp": "claim_processed_message"}[source]
    release_name = {"telegram": "release_telegram_update_claim", "whatsapp": "release_processed_message_claim"}[source]
    claim = Mock(side_effect=[True, False])
    release = Mock()
    monkeypatch.setattr(module, claim_name, claim)
    monkeypatch.setattr(module, release_name, release)
    generate = Mock(return_value="A reply")
    save = Mock()
    send = Mock(return_value=send_result)
    monkeypatch.setattr(module, "generate_response", generate)
    monkeypatch.setattr(module, "save_message", save)
    monkeypatch.setattr(module, {"telegram": "send_telegram_message", "whatsapp": "send_message"}[source], send)
    if source == "telegram":
        payload = {"update_id": 9, "message": {"message_id": 10, "chat": {"id": 12345, "type": "private"}, "from": {"id": 12345}, "text": text}}
        run = lambda: module.process_telegram_update(payload, "synthetic-secret")
    else:
        payload = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "55"}, "contacts": [{"wa_id": "12345"}], "messages": [{"id": "10", "type": "text" if text else "image", "text": {"body": text}}]}}]}]}
        run = lambda: module.process_whatsapp_message(payload)
    return run, generate, save, send, release


@pytest.mark.parametrize("source", ["telegram", "whatsapp"])
def test_duplicate_inbound_does_not_repeat_ai_or_failed_delivery(monkeypatch, source):
    run, generate, save, send, release = _inbound(monkeypatch, source)
    run()
    run()
    generate.assert_called_once()
    assert generate.call_args.kwargs["conversation_id"] == 8
    send.assert_called_once()
    bot_rows = [call.kwargs for call in save.call_args_list if call.kwargs["sender_type"] == "bot"]
    assert len(bot_rows) == 1
    assert bot_rows[0]["delivery_status"] in {"failed", "permanent_failed"}
    release.assert_not_called()


@pytest.mark.parametrize("text", ["hello", None])
def test_whatsapp_automatic_reply_retains_graph_message_id_for_receipts(monkeypatch, text):
    result = Mock(status_code=200, json=Mock(return_value={"messages": [{"id": "wamid.outgoing"}]}))
    run, _, save, _, _ = _inbound(monkeypatch, "whatsapp", text=text, send_result=result)
    run()
    assert save.call_args.kwargs["platform_message_id"] == "wamid.outgoing"


def test_whatsapp_inbox_reply_retains_graph_message_id_for_receipts(monkeypatch):
    monkeypatch.setattr(agent_routes.content_filter, "check_bot_text", Mock(return_value=None))
    monkeypatch.setattr(delivery, "get_bound_channel", Mock(return_value={"phone_number_id": "55"}))
    sent = Mock(status_code=200, json=Mock(return_value={"messages": [{"id": "wamid.staff"}]}))
    monkeypatch.setattr(agent_routes, "send_whatsapp_message", Mock(return_value=sent))
    save = Mock()
    monkeypatch.setattr(agent_routes, "save_message", save)
    chat = {"id": 2, "chatbot_id": 3, "source_channel": "whatsapp", "customer_phone": "12345"}
    with Flask(__name__).test_request_context():
        _, status = agent_routes._deliver_staff_reply(2, 3, {"id": 3, "company_id": 1}, chat, "Hello")
    assert status == 200
    assert save.call_args.kwargs["platform_message_id"] == "wamid.staff"


@pytest.mark.parametrize("source", ["telegram", "whatsapp"])
@pytest.mark.parametrize("text", ["Hello", None])
def test_handoff_pauses_text_and_attachment_autoreplies(monkeypatch, source, text):
    run, generate, save, send, release = _inbound(monkeypatch, source, paused=True, text=text)
    run()
    generate.assert_not_called()
    send.assert_not_called()
    assert len(save.call_args_list) == 1
    assert save.call_args.kwargs["sender_type"] == "customer"


@pytest.mark.parametrize("source", ["telegram", "whatsapp"])
@pytest.mark.parametrize("acknowledgement", ["ordinary", "persisted", "resolved", "wrong_conversation", "untrusted_text"])
def test_handoff_started_during_generation_suppresses_ordinary_reply(monkeypatch, source, acknowledgement):
    accepted = {"ok": True, "success": True} if source != "whatsapp" else Mock(status_code=200, json=Mock(return_value={"messages": [{"id": "11"}]}))
    run, generate, save, send, release = _inbound(monkeypatch, source, send_result=accepted)
    module = {"telegram": telegram_utils, "whatsapp": whatsapp_utils}[source]
    pending = Mock(return_value=acknowledgement != "resolved")
    monkeypatch.setattr(delivery, "is_pending_handoff_action", pending)
    def begin_handoff(*_, **__):
        module.is_conversation_escalated.return_value = True
        if acknowledgement in {"persisted", "resolved", "wrong_conversation"}:
            return delivery.HandoffAcknowledgement("I'm transferring you to our Customer Service team now.",
                action_id=9, conversation_id=88 if acknowledgement == "wrong_conversation" else 8, chatbot_id=3, company_id=1)
        return "I'm transferring you to our Customer Service team now." if acknowledgement == "untrusted_text" else "Ordinary generated reply"
    generate.side_effect = begin_handoff
    run()
    assert send.call_count == (1 if acknowledgement == "persisted" else 0)
    assert len([call for call in save.call_args_list if call.kwargs["sender_type"] == "bot"]) == send.call_count
    module.dispatch_media_after_reply.assert_not_called()
    release.assert_not_called()


@pytest.mark.parametrize("source", ["telegram"])
def test_handoff_between_reply_chunks_stops_remaining_chunks(monkeypatch, source):
    run, generate, save, send, release = _inbound(monkeypatch, source)
    module = telegram_utils
    monkeypatch.setattr(module, f"split_{source}_reply", Mock(return_value=["First part", "Second part"]))
    def send_first(*_, **__):
        module.is_conversation_escalated.return_value = True
        return {"ok": True, "success": True}
    send.side_effect = send_first
    run()
    send.assert_called_once()
    assert save.call_args.kwargs["delivery_status"] in {"failed", "permanent_failed"}
    module.dispatch_media_after_reply.assert_not_called()


@pytest.mark.parametrize("source", ["telegram", "meta"])
def test_handoff_started_during_media_selection_blocks_attachment(monkeypatch, source):
    from app.services import media_send_service as media
    monkeypatch.setattr(media, "get_active_attachments", Mock(return_value=[{"label": "catalogue", "keywords": ["catalogue"]}]))
    monkeypatch.setattr(media, "get_bound_channel", Mock(return_value={"api_key": "synthetic", "bot_token": "synthetic"}))
    pause = Mock(return_value=False)
    monkeypatch.setattr(media, "is_conversation_escalated", pause)
    def select(*_):
        pause.return_value = True
        return {"label": "catalogue"}
    monkeypatch.setattr(media, "find_matching_attachment", select)
    senders = []
    for name in ("send_telegram_media", "send_meta_media_template"):
        sender = Mock()
        monkeypatch.setattr(media, name, sender)
        senders.append(sender)
    assert media.dispatch_media_after_reply("catalogue", 3, source, {}, "123", conversation={"id": 8, "chatbot_id": 3}) is False
    assert not any(sender.called for sender in senders)


def test_telegram_releases_pretranscript_failure_but_retains_post_ai_claim(monkeypatch):
    run, generate, save, send, release = _inbound(monkeypatch, "telegram")
    telegram_utils.get_or_create_platform_conversation.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError):
        run()
    release.assert_called_once_with(4, 9)
    run, generate, save, send, release = _inbound(monkeypatch, "telegram")
    generate.side_effect = RuntimeError("provider response uncertain")
    with pytest.raises(RuntimeError):
        run()
    release.assert_not_called()


def test_router_handoff_blocks_flow_before_ai_or_billing(monkeypatch):
    from app.database import conversation_repository, agent_action_repository
    monkeypatch.setattr(ai_router, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1}))
    monkeypatch.setattr(conversation_repository, "get_conversation_by_id_and_chatbot", Mock(return_value={"id": 8, "chatbot_id": 3, "source_channel": "telegram"}))
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated", Mock(return_value=True))
    flow = Mock()
    provider = Mock()
    monkeypatch.setattr(ai_router, "_try_process_flow_message", flow)
    monkeypatch.setattr(ai_router, "call_provider", provider)
    assert ai_router.generate_response("Hello", "123", 3, source_channel="telegram", conversation_id=8) == "<SILENT_BOT_RESPONSE>"
    flow.assert_not_called()
    provider.assert_not_called()


@pytest.mark.parametrize("boundary", ["bot_lookup", "company_check"])
def test_router_early_lookup_failure_keeps_safe_fallback(monkeypatch, boundary):
    from app.services import company_status_service
    monkeypatch.setattr(ai_router, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1},
        side_effect=RuntimeError("unavailable") if boundary == "bot_lookup" else None))
    monkeypatch.setattr(company_status_service, "ensure_company_operational", Mock(
        side_effect=RuntimeError("unavailable") if boundary == "company_check" else None))
    assert ai_router.generate_response("Hello", "123", 3, conversation_id=8) == "Sorry, I'm having trouble replying right now. Please try again later."


@pytest.mark.parametrize("flow_handled", [True, False])
def test_router_suppresses_web_reply_when_handoff_starts_during_generation(monkeypatch, flow_handled):
    from types import SimpleNamespace
    from app.database import conversation_repository, agent_action_repository
    from app.services import company_status_service
    monkeypatch.setattr(company_status_service, "ensure_company_operational", Mock())
    monkeypatch.setattr(ai_router, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1}))
    monkeypatch.setattr(conversation_repository, "get_conversation_by_id_and_chatbot", Mock(return_value={"id": 8, "chatbot_id": 3, "source_channel": "test"}))
    pause = Mock(return_value=False)
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated", pause)
    def start_handoff(*_, **__):
        pause.return_value = True
        return SimpleNamespace(handled=flow_handled, should_handoff_to_ai=True, reply="Flow reply")
    monkeypatch.setattr(ai_router, "_try_process_flow_message", start_handoff)
    monkeypatch.setattr(ai_router, "normalize_model_selection", Mock(return_value=("deepseek", "synthetic-model")))
    monkeypatch.setattr(ai_router, "_route_for_enforcement", Mock(return_value=("deepseek", "synthetic-model")))
    monkeypatch.setattr(ai_router, "call_provider", Mock(return_value=ai_router._make_result_from_text("Generated reply")))
    assert ai_router.generate_response("Hello", "123", 3, source_channel="test", conversation_id=8) == "<SILENT_BOT_RESPONSE>"


@pytest.mark.parametrize("provider", ["deepseek", "openai"])
def test_router_preserves_persisted_handoff_marker_through_provider(monkeypatch, provider):
    from types import SimpleNamespace
    from app.services import company_status_service, deepseek_service
    from app.database import conversation_repository, agent_action_repository
    acknowledgement = delivery.HandoffAcknowledgement("I'm transferring you to our Customer Service team now.",
        action_id=9, conversation_id=8, chatbot_id=3, company_id=1)
    monkeypatch.setattr(ai_router, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1, "ai_provider": provider}))
    monkeypatch.setattr(company_status_service, "ensure_company_operational", Mock())
    monkeypatch.setattr(conversation_repository, "get_conversation_by_id_and_chatbot", Mock(return_value={"id": 8, "chatbot_id": 3, "source_channel": "test"}))
    pause = Mock(return_value=False)
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated", pause)
    monkeypatch.setattr(delivery, "is_pending_handoff_action", Mock(return_value=True))
    def prepare(*_, **__):
        pause.return_value = True
        return {"direct_reply": acknowledgement}
    monkeypatch.setattr(ai_router, "prepare_chat_prompt", prepare)
    monkeypatch.setattr(deepseek_service, "prepare_chat_prompt", prepare)
    monkeypatch.setattr(ai_router, "_try_process_flow_message", Mock(return_value=SimpleNamespace(handled=False, should_handoff_to_ai=True)))
    monkeypatch.setattr(ai_router, "normalize_model_selection", Mock(return_value=(provider, "synthetic-model")))
    monkeypatch.setattr(ai_router, "_route_for_enforcement", Mock(return_value=(provider, "synthetic-model")))
    monkeypatch.setattr(ai_router, "_check_ai_credit_before_provider", Mock())
    result = ai_router.generate_response("Hello", "123", 3, source_channel="test", conversation_id=8)
    assert result is acknowledgement
    delivery.is_pending_handoff_action.assert_called_once_with(9, 8, 3, 1)


@pytest.mark.parametrize("pending", [True, False])
def test_unbound_legacy_handoff_pauses_new_bound_conversation(monkeypatch, pending):
    from types import SimpleNamespace
    from app.database import agent_action_repository as actions
    query = Mock()
    for method in ("table", "select", "eq", "in_", "limit", "is_"):
        getattr(query, method).return_value = query
    query.execute.side_effect = [SimpleNamespace(data=[]), SimpleNamespace(data=[{"id": 7}]),
                                 SimpleNamespace(data=[{"id": 9}] if pending else [])]
    monkeypatch.setattr(actions, "supabase", query)
    conv = {"id": 8, "chatbot_id": 3, "source_channel": "whatsapp", "source_channel_id": 4,
            "source_provider_id": "55", "customer_phone": "123"}
    assert actions.is_conversation_escalated(8, 3, conversation=conv) is pending
    query.is_.assert_called_once_with("source_channel_id", "null")
    assert any(call.args == ("conversation_id", [7]) for call in query.in_.call_args_list)


@pytest.mark.parametrize("platform", [False, True])
def test_new_conversation_queries_and_insert_keep_origin(monkeypatch, platform):
    from types import SimpleNamespace
    from app.database import conversation_repository as repository
    query = Mock()
    for method in ("table", "select", "eq", "limit", "insert"):
        getattr(query, method).return_value = query
    query.execute.side_effect = [SimpleNamespace(data=[]), SimpleNamespace(data=[{"id": 8}])]
    monkeypatch.setattr(repository, "supabase", query)
    if platform:
        result = repository.get_or_create_platform_conversation(3, "123", source_channel_id=4, source_provider_id="55")
    else:
        result = repository.get_or_create_conversation(3, "123", source_channel_id=4, source_provider_id="55")
    assert result == {"id": 8}
    payload = query.insert.call_args.args[0]
    assert payload["source_channel_id"] == 4 and payload["source_provider_id"] == "55"
    assert any(call.args == ("source_channel_id", 4) for call in query.eq.call_args_list)
    assert any(call.args == ("source_provider_id", "55") for call in query.eq.call_args_list)
    if platform:
        assert not any(call.args[0] == "customer_phone" for call in query.eq.call_args_list)


@pytest.mark.parametrize("changed_field", [None, "status", "intent", "company_id", "chatbot_id", "conversation_id"])
def test_acknowledgement_requires_exact_pending_action_scope(monkeypatch, changed_field):
    from types import SimpleNamespace
    from app.database import agent_action_repository as repository
    row = {"id": 9, "company_id": 1, "chatbot_id": 3, "conversation_id": 8,
           "intent": "handoff_request", "status": "detected"}
    if changed_field:
        row[changed_field] = "resolved" if changed_field == "status" else "other"
    filters = {}
    query = Mock()
    for method in ("table", "select", "limit"):
        getattr(query, method).return_value = query
    query.eq.side_effect = lambda key, value: filters.update({key: value}) or query
    query.execute.side_effect = lambda: SimpleNamespace(data=[row] if all(row.get(key) == value for key, value in filters.items()) else [])
    monkeypatch.setattr(repository, "supabase", query)
    assert repository.is_pending_handoff_action(9, 8, 3, 1) is (changed_field is None)


@pytest.mark.parametrize("channel_id,provider_id", [(4, None), (None, "55"), (0, "55"), (True, "55"), (4, "")])
def test_conversation_origin_requires_complete_valid_pair(channel_id, provider_id):
    from app.database.conversation_repository import _scope_origin
    query = Mock()
    with pytest.raises(ValueError):
        _scope_origin(query, channel_id, provider_id)
    query.execute.assert_not_called()


def test_legacy_caller_cannot_select_bound_history():
    from app.database.conversation_repository import _scope_origin
    query = Mock()
    assert _scope_origin(query, None, None) is query.is_.return_value
    query.is_.assert_called_once_with("source_channel_id", "null")
    query.eq.assert_not_called()
