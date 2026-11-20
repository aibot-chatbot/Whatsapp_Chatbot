"""Telegram chat boundaries, contact ownership, and staff reply destinations."""

import inspect
import logging
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from flask import Flask, g

from app.database import agent_action_repository, conversation_repository
from app.routes import agent_routes
from app.services import ai_router, channel_delivery_service, chat_pipeline_service, rag_service
from app.utils import telegram_utils

# Captured at import: conftest swaps the module attribute for a no-op in every test.
REAL_SHOW_TYPING = getattr(telegram_utils, "show_telegram_typing", None)


CHANNEL = {
    "id": 4, "chatbot_id": 3, "company_id": 1, "telegram_bot_id": "55",
    "bot_token": "synthetic-bot-token", "is_active": True,
    "connection_status": "connected", "verified_at": "2026-09-14T00:00:00Z",
}


def telegram_update(chat_id=501, sender_id=501, chat_type="private", *, update_id=1,
                    title=None, text="Question", contact=None, callback=False):
    chat = {"id": chat_id, "type": chat_type}
    if title is not None:
        chat["title"] = title
    author = {"id": sender_id, "first_name": "Member", "username": "member"}
    message = {"message_id": update_id + 10, "chat": chat, "from": author, "text": text}
    if contact is not None:
        message["contact"] = contact
        message.pop("text")
    if callback:
        return {"update_id": update_id, "callback_query": {
            "id": f"callback-{update_id}", "from": author,
            "message": message, "data": text,
        }}
    return {"update_id": update_id, "message": message}


@pytest.fixture
def telegram_harness(monkeypatch):
    conversations = {}
    messages = []

    def seed(platform_user_id, *, customer_phone=None, customer_name=None):
        key = str(platform_user_id)
        conversations[key] = {
            "id": 100 + len(conversations), "chatbot_id": 3,
            "source_channel": "telegram", "source_channel_id": 4, "source_provider_id": "55",
            "platform_user_id": key, "customer_phone": customer_phone, "customer_name": customer_name,
        }
        return conversations[key]

    def get_or_create(**kwargs):
        key = kwargs["platform_user_id"]
        if key not in conversations:
            seed(key, customer_phone=kwargs.get("customer_phone"), customer_name=kwargs.get("customer_name"))
        return conversations[key]

    def set_phone(**kwargs):
        row = conversations[kwargs["platform_user_id"]]
        row.update(customer_phone=kwargs["customer_phone"], customer_name=kwargs["customer_name"])
        return row

    lookup = Mock(side_effect=get_or_create)
    phone_update = Mock(side_effect=set_phone)
    generate = Mock(return_value="A reply")
    send = Mock(return_value={"ok": True, "result": {"message_id": 50}})
    contact_request = Mock(return_value={"ok": True})
    callback_post = Mock(return_value=Mock(json=Mock(return_value={"ok": True})))
    monkeypatch.setattr(telegram_utils, "get_telegram_channel_by_secret", Mock(return_value=CHANNEL))
    monkeypatch.setattr(telegram_utils, "claim_telegram_update", Mock(return_value=True))
    monkeypatch.setattr(telegram_utils, "release_telegram_update_claim", Mock())
    monkeypatch.setattr(telegram_utils, "get_or_create_platform_conversation", lookup)
    monkeypatch.setattr(telegram_utils, "update_conversation_phone_by_platform", phone_update)
    monkeypatch.setattr(telegram_utils, "is_conversation_escalated", Mock(return_value=False))
    monkeypatch.setattr(channel_delivery_service, "get_telegram_channel_by_id", Mock(return_value=CHANNEL))
    monkeypatch.setattr(telegram_utils, "get_bot_by_id", Mock(return_value={"telegram_markdown_enabled": False}))
    monkeypatch.setattr(telegram_utils, "generate_response", generate)
    monkeypatch.setattr(telegram_utils, "send_telegram_message", send)
    monkeypatch.setattr(telegram_utils, "send_telegram_contact_request", contact_request)
    monkeypatch.setattr(telegram_utils, "dispatch_media_after_reply", Mock())
    monkeypatch.setattr(telegram_utils, "save_message", Mock(side_effect=lambda **kwargs: messages.append(kwargs)))
    monkeypatch.setattr(telegram_utils.requests, "post", callback_post)
    return SimpleNamespace(
        conversations=conversations, messages=messages, seed=seed, lookup=lookup,
        phone_update=phone_update, generate=generate, send=send, contact_request=contact_request,
        callback_post=callback_post,
        run=lambda update: telegram_utils.process_telegram_update(update, "synthetic-webhook-secret"),
    )


def test_same_sender_private_and_two_groups_have_separate_conversations(telegram_harness):
    h = telegram_harness
    h.seed(501, customer_phone="+60123456789", customer_name="Member")
    contexts = [(501, "private", None), (-1001, "group", "First group"), (-1002, "supergroup", "Second group")]
    for index, (chat_id, chat_type, title) in enumerate(contexts, 1):
        h.run(telegram_update(chat_id, 501, chat_type, update_id=index, title=title))
    assert set(h.conversations) == {"501", "-1001", "-1002"}
    conversation_ids = {row["id"] for row in h.conversations.values()}
    assert len(conversation_ids) == 3
    assert {call.kwargs["conversation_id"] for call in h.generate.call_args_list} == conversation_ids
    assert [call.args[1] for call in h.send.call_args_list] == ["501", "-1001", "-1002"]
    assert h.conversations["501"]["customer_phone"] == "+60123456789"
    for chat_id, title in (("-1001", "First group"), ("-1002", "Second group")):
        assert h.conversations[chat_id]["customer_phone"] is None
        assert h.conversations[chat_id]["customer_name"] == title
    h.contact_request.assert_not_called()


@pytest.mark.parametrize("chat_type", ["group", "supergroup"])
def test_two_senders_in_one_group_share_chat_history(telegram_harness, chat_type):
    h = telegram_harness
    for update_id, sender in enumerate((501, 502), 1):
        h.run(telegram_update(-1001, sender, chat_type, update_id=update_id, title="Support room"))
    assert set(h.conversations) == {"-1001"}
    assert h.generate.call_count == 2
    assert len({call.kwargs["conversation_id"] for call in h.generate.call_args_list}) == 1
    assert h.conversations["-1001"]["customer_name"] == "Support room"
    assert all(call.args[1] == "-1001" for call in h.send.call_args_list)


def test_group_callback_routes_by_message_chat_not_clicking_member(telegram_harness):
    h = telegram_harness
    h.run(telegram_update(-1001, 501, "supergroup", title="Support room", callback=True))
    h.lookup.assert_called_once()
    assert h.lookup.call_args.kwargs["platform_user_id"] == "-1001"
    assert h.lookup.call_args.kwargs["customer_name"] == "Support room"
    assert h.generate.call_args.args[1] == "-1001"
    assert h.send.call_args.args[1] == "-1001"
    assert any(call.kwargs["json"] == {"callback_query_id": "callback-1"} for call in h.callback_post.call_args_list)
    typing = [call for call in h.callback_post.call_args_list if call.args[0].endswith("/sendChatAction")]
    assert len(typing) == 1
    assert str(typing[0].kwargs["json"]["chat_id"]) == "-1001"


@pytest.mark.parametrize("chat_type,title", [("group", "Support room"), ("supergroup", None)])
def test_group_contact_never_replaces_group_profile_with_member_details(telegram_harness, chat_type, title):
    h = telegram_harness
    contact = {"user_id": 501, "phone_number": "+60123456789", "first_name": "Private person"}
    h.run(telegram_update(-1001, 501, chat_type, title=title, contact=contact))
    row = h.conversations["-1001"]
    assert row["customer_phone"] is None
    assert row["customer_name"] == (title or "Telegram group")
    h.phone_update.assert_not_called()
    h.generate.assert_not_called()
    h.contact_request.assert_not_called()
    assert len(h.messages) == 1
    assert h.messages[0]["message_text"] == "[Contact shared in group]"


def test_anonymous_group_author_keeps_group_chat_identity(telegram_harness):
    h = telegram_harness
    update = telegram_update(-1001, 501, "supergroup", title="Anonymous room")
    update["message"].pop("from")
    update["message"]["sender_chat"] = {"id": -1001, "type": "supergroup"}
    h.run(update)
    assert set(h.conversations) == {"-1001"}
    assert h.conversations["-1001"]["customer_name"] == "Anonymous room"
    h.generate.assert_called_once()


@pytest.mark.parametrize("contact_owner", [501, 502, None, True, "501"])
def test_private_contact_requires_own_integer_user_id(telegram_harness, contact_owner):
    h = telegram_harness
    h.run(telegram_update(contact={"user_id": contact_owner, "phone_number": "+60123456789"}))
    row = h.conversations["501"]
    if contact_owner == 501 and isinstance(contact_owner, int):
        h.phone_update.assert_called_once()
        assert row["customer_phone"] == "+60123456789"
        assert h.phone_update.call_args.kwargs["platform_user_id"] == "501"
        assert row["customer_name"] == "Member (@member)"
    else:
        h.phone_update.assert_not_called()
        assert row["customer_phone"] is None
    h.generate.assert_not_called()


@pytest.mark.parametrize("callback", [False, True])
@pytest.mark.parametrize("invalid", ["missing_type", "unknown_type", "channel_type", "bool_chat", "string_chat", "zero_chat",
                                     "missing_sender", "bool_sender", "string_sender", "zero_sender", "mismatched_private"])
def test_invalid_private_context_is_ignored_before_side_effects(telegram_harness, callback, invalid):
    h = telegram_harness
    update = telegram_update(callback=callback)
    message = update["callback_query"]["message"] if callback else update["message"]
    author = update["callback_query"]["from"] if callback else message["from"]
    if invalid == "missing_type":
        message["chat"].pop("type")
    elif invalid in {"unknown_type", "channel_type"}:
        message["chat"]["type"] = "channel" if invalid == "channel_type" else "unknown"
    elif invalid in {"bool_chat", "string_chat", "zero_chat"}:
        message["chat"]["id"] = {"bool_chat": True, "string_chat": "501", "zero_chat": 0}[invalid]
    elif invalid == "missing_sender":
        author.pop("id")
    elif invalid in {"bool_sender", "string_sender", "zero_sender"}:
        author["id"] = {"bool_sender": True, "string_sender": "501", "zero_sender": 0}[invalid]
    else:
        message["chat"]["id"] = 502
    h.run(update)
    h.lookup.assert_not_called()
    h.phone_update.assert_not_called()
    h.callback_post.assert_not_called()
    h.generate.assert_not_called()
    h.send.assert_not_called()
    h.contact_request.assert_not_called()
    assert h.messages == []


@pytest.mark.parametrize("operation", ["staff_reply", "resolve"])
@pytest.mark.parametrize("chat_id", ["501", "-1001"])
def test_staff_and_resolve_send_to_persisted_chat_id(monkeypatch, operation, chat_id):
    conversation = {
        "id": 100, "chatbot_id": 3, "source_channel": "telegram", "source_channel_id": 4,
        "source_provider_id": "55", "platform_user_id": chat_id, "customer_phone": "+60123456789",
    }
    monkeypatch.setattr(agent_routes, "verify_chatbot_access", Mock(return_value={"company_id": 1}))
    monkeypatch.setattr(agent_routes, "get_conversation_by_id_and_chatbot", Mock(return_value=conversation))
    monkeypatch.setattr(channel_delivery_service, "get_telegram_channel_by_id", Mock(return_value=CHANNEL))
    sender = Mock(return_value={"ok": True})
    monkeypatch.setattr(agent_routes, "send_telegram_message", sender)
    monkeypatch.setattr(agent_routes, "save_message", Mock())
    monkeypatch.setattr(agent_routes, "resolve_escalation", Mock(return_value=({"id": 9, "conversation_id": 100, "_ai_resumed": True}, True)))
    monkeypatch.setattr(agent_routes, "is_conversation_escalated", Mock(return_value=False))
    with Flask(__name__).test_request_context(json={"chatbot_id": 3, "text": "Staff reply"}):
        g.role = "admin"  # authentication is unwrapped here; members need a handoff (Phase 6)
        response, status = (inspect.unwrap(agent_routes.agent_reply)(100) if operation == "staff_reply"
                            else inspect.unwrap(agent_routes.resolve_esc)(9))
    assert status == 200
    sender.assert_called_once()
    assert sender.call_args.args[1] == chat_id
    if operation == "resolve":
        assert response.json["data"]["notification_status"] == "sent"


def test_group_prompt_uses_exact_group_conversation_without_private_history(monkeypatch, telegram_harness):
    h = telegram_harness
    private = h.seed(501, customer_phone="+60123456789", customer_name="Member")
    group = h.seed(-1001, customer_name="Support room")
    h.messages.extend([
        {"conversation_id": private["id"], "sender_type": "customer", "message_text": "PRIVATE HISTORY MUST STAY PRIVATE"},
        {"conversation_id": group["id"], "sender_type": "customer", "message_text": "Earlier group discussion"},
    ])
    monkeypatch.setattr(telegram_utils, "generate_response", ai_router.generate_response)
    monkeypatch.setattr(ai_router, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1, "ai_provider": "openai"}))
    lookup = Mock(side_effect=lambda conversation_id, chatbot_id: next(
        row for row in h.conversations.values() if row["id"] == conversation_id and row["chatbot_id"] == chatbot_id))
    monkeypatch.setattr(conversation_repository, "get_conversation_by_id_and_chatbot", lookup)
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated", Mock(return_value=False))
    flow = Mock(return_value=SimpleNamespace(handled=False, should_handoff_to_ai=True))
    monkeypatch.setattr(ai_router, "_try_process_flow_message", flow)
    monkeypatch.setattr(ai_router, "normalize_model_selection", Mock(return_value=("openai", "synthetic-model")))
    monkeypatch.setattr(ai_router, "_route_for_enforcement", Mock(return_value=("openai", "synthetic-model")))
    monkeypatch.setattr(ai_router, "_check_ai_credit_before_provider", Mock())
    monkeypatch.setattr(ai_router, "_make_usage_log", Mock())
    monkeypatch.setattr(chat_pipeline_service, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1}))
    fallback = Mock(side_effect=AssertionError("Do not look up an unbound conversation"))
    monkeypatch.setattr(chat_pipeline_service, "get_or_create_conversation", fallback)
    history = Mock(side_effect=lambda conversation_id, limit: [
        {"role": "user", "content": row["message_text"]} for row in h.messages
        if row["conversation_id"] == conversation_id][-limit:])
    monkeypatch.setattr(chat_pipeline_service, "get_recent_chat_history", history)
    monkeypatch.setattr(chat_pipeline_service, "analyze_agent_intent", Mock(return_value={"intent": "unknown"}))
    monkeypatch.setattr(chat_pipeline_service, "build_safe_agent_action_payload", Mock(return_value={}))
    monkeypatch.setattr(chat_pipeline_service, "save_agent_action", Mock(return_value={"id": 9}))
    monkeypatch.setattr(chat_pipeline_service, "create_crm_lead_from_agent_signal", Mock())
    monkeypatch.setattr("app.services.conversation_memory_service.conversation_memory_denial", lambda _: "not_under_test")
    monkeypatch.setattr(chat_pipeline_service, "detect_intent", Mock(return_value="question"))
    monkeypatch.setattr(chat_pipeline_service, "update_workflow_state", Mock())
    monkeypatch.setattr(chat_pipeline_service, "retrieve_relevant_chunks", Mock(return_value=[]))
    monkeypatch.setattr(rag_service, "get_deployed_settings", Mock(return_value={}))
    provider = Mock(return_value=(True, {"choices": [{"message": {"content": "Group answer"}}]}))
    monkeypatch.setattr(ai_router.openrouter_service, "_request", provider)

    h.run(telegram_update(-1001, 501, "supergroup", title="Support room", text="Please explain the group topic"))

    lookup.assert_called_once_with(group["id"], 3)
    assert flow.call_args.kwargs["conversation"] is group
    history.assert_called_once_with(group["id"], limit=chat_pipeline_service.MAX_HISTORY)
    fallback.assert_not_called()
    prompt = provider.call_args.kwargs["prompt"]
    assert "Earlier group discussion" in prompt
    assert "Please explain the group topic" in prompt
    assert "PRIVATE HISTORY MUST STAY PRIVATE" not in prompt
    assert h.send.call_args.args[1] == "-1001"


def test_text_message_shows_typing_before_the_reply_is_generated(telegram_harness, monkeypatch):
    h = telegram_harness
    h.seed(501, customer_phone="+60123456789")
    events = []
    h.callback_post.side_effect = lambda url, **kwargs: events.append((url.rsplit("/", 1)[-1], kwargs["json"]))
    h.generate.side_effect = lambda *args, **kwargs: events.append(("generate", None)) or "A reply"
    monkeypatch.setattr(telegram_utils, "show_telegram_typing", telegram_utils.post_telegram_typing)

    h.run(telegram_update(501, 501))

    assert [name for name, _ in events] == ["sendChatAction", "generate"]
    assert str(events[0][1]["chat_id"]) == "501"
    assert events[0][1]["action"] == "typing"
    h.send.assert_called_once()


def test_paused_conversation_shows_no_typing(telegram_harness, monkeypatch):
    h = telegram_harness
    h.seed(501, customer_phone="+60123456789")
    show = Mock()
    monkeypatch.setattr(telegram_utils, "show_telegram_typing", show)
    monkeypatch.setattr(telegram_utils, "is_conversation_escalated", Mock(return_value=True))

    h.run(telegram_update(501, 501))

    show.assert_not_called()
    h.generate.assert_not_called()


def test_typing_failure_is_swallowed_and_never_logs_the_bot_token(monkeypatch, caplog):
    def fail(url, **kwargs):
        raise requests.ConnectionError(f"Failed request to {url}")

    monkeypatch.setattr(telegram_utils.requests, "post", fail)
    with caplog.at_level(logging.INFO):
        telegram_utils.post_telegram_typing("synthetic-bot-token", 501)

    assert "ConnectionError" in caplog.text
    assert "synthetic-bot-token" not in caplog.text


def test_typing_is_sent_off_the_reply_thread(monkeypatch):
    sent = threading.Event()
    seen = {}

    def post(bot_token, chat_id):
        seen.update(thread=threading.current_thread(), args=(bot_token, chat_id))
        sent.set()

    monkeypatch.setattr(telegram_utils, "post_telegram_typing", post)
    REAL_SHOW_TYPING("synthetic-bot-token", 501)

    assert sent.wait(2)
    assert seen["thread"] is not threading.current_thread()
    assert seen["thread"].daemon
    assert seen["args"] == ("synthetic-bot-token", 501)
