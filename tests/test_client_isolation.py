"""Phase 5 items 12-16: when one Client fails, every other Client is still answered.

Each test breaks Client A one way and sends Client B an ordinary customer message through the
real reply path (ai_router.generate_response; in the flood test also the real Telegram webhook
route and worker lanes). Only what leaves this process is faked: OpenRouter's HTTP endpoint,
database rows and email. Each Client's OpenRouter key is a real Fernet-encrypted key in a fake
key table, so the key a request carries is chosen by the real openrouter_key_service.
"""
import json
import logging
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
import requests
from cryptography.fernet import Fernet
from flask import Flask

from app.database import openrouter_key_repository
from app.routes import telegram_routes
from app.services import (ai_gateway, ai_router, chat_pipeline_service, company_status_service,
                          content_review_service, email_service, message_limits, openrouter_key_service,
                          openrouter_service)
from app.services import channel_delivery_service as delivery
from app.services.channel_delivery_service import HandoffAcknowledgement
from app.services.webhook_worker import drain

A, B = 101, 202  # company ids
BOTS = {3: {"id": 3, "company_id": A}, 5: {"id": 5, "company_id": B}}
BOT_A, BOT_B = 3, 5
KEY_A, KEY_B, SHARED = "sk-client-a-synthetic", "sk-client-b-synthetic", "sk-shared-synthetic"
KEY_NAMES = {KEY_A: "key A", KEY_B: "key B", SHARED: "shared key"}  # asserts name keys, never show them
LUNA = "openai/gpt-6-luna"
ANSWER_TEXT = "We open at 9am."
TROUBLE_REPLY = "Sorry, I'm having trouble replying right now. Please try again later."
WAIT = 5  # seconds; a hung worker fails the test instead of hanging the suite


def http_response(status, body):
    response = MagicMock(status_code=status, ok=status < 400, text=json.dumps(body))
    response.json.return_value = body
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} error", response=response)
    return response


def answer():
    return http_response(200, {"id": "gen-1", "choices": [{"message": {"content": ANSWER_TEXT}, "finish_reason": "stop"}],
                               "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})


@pytest.fixture
def world(monkeypatch):
    from app.database import agent_action_repository, conversation_repository

    master_key = Fernet.generate_key()
    fernet = Fernet(master_key)
    world = SimpleNamespace(
        keys={company: {"id": key_id, "label": f"pool-{key_id}", "status": "active",
                        "encrypted_key": fernet.encrypt(key.encode()).decode()}
              for company, key_id, key in ((A, 1, KEY_A), (B, 2, KEY_B))},
        status={A: "active", B: "active"},
        refuse={},  # key -> the response OpenRouter gives that key instead of an answer
        calls=[], saved=[], lock=threading.Lock(),
        staff=Mock(return_value=True), owner=Mock(return_value=True))

    def openrouter_post(url, headers=None, **_):
        key = headers["Authorization"].removeprefix("Bearer ")
        with world.lock:
            world.calls.append((url, key))
        return world.refuse.get(key) or answer()

    def mark_disabled(key_id, reason=None, culprit_company_id=None):
        row = next(row for row in world.keys.values() if row["id"] == key_id)
        row.update(status="disabled", disabled_reason=reason, culprit_company_id=culprit_company_id)

    def save(**fields):
        with world.lock:
            world.saved.append(fields)
            return {"id": 40 + len(world.saved)}

    # The key table: A and B are already on their own keys, so no key is created or assigned.
    monkeypatch.setattr(openrouter_key_repository, "get_company_key", world.keys.get)
    monkeypatch.setattr(openrouter_key_repository, "assign_company", Mock(side_effect=AssertionError("reassigned")))
    monkeypatch.setattr(openrouter_key_repository, "mark_disabled", mark_disabled)
    monkeypatch.setattr(openrouter_key_repository, "list_disable_reasons", lambda: {
        row["id"]: row for row in world.keys.values() if row["status"] == "disabled"})
    monkeypatch.setattr(openrouter_key_service, "_cache", {})
    monkeypatch.setenv("OPENROUTER_CLIENT_KEYS_ENABLED", "true")
    monkeypatch.setenv("AI_KEY_ENCRYPTION_KEY", master_key.decode())
    # Phase 5 limits on, with empty windows.
    monkeypatch.setenv("RATELIMIT_ENABLED", "true")
    monkeypatch.setattr(message_limits, "_customers", {})
    monkeypatch.setattr(message_limits, "_clients", {})
    # Database rows: company status (read by the real ensure_company_operational), bots, conversations.
    monkeypatch.setattr(company_status_service, "get_company_status_by_id",
                        lambda company_id: {"id": company_id, "status": world.status[company_id]})
    monkeypatch.setattr(ai_router, "get_bot_by_id", BOTS.get)
    monkeypatch.setattr(chat_pipeline_service, "get_bot_by_id", BOTS.get)
    monkeypatch.setattr(conversation_repository, "get_conversation_by_id_and_chatbot", lambda conversation_id, chatbot_id: {
        "id": conversation_id, "chatbot_id": chatbot_id, "source_channel": "telegram"})
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated",
                        lambda conversation_id, *_, **__: any(r["conversation_id"] == conversation_id for r in world.saved))
    monkeypatch.setattr(delivery, "is_pending_handoff_action", lambda *_: True)
    monkeypatch.setattr(chat_pipeline_service, "save_agent_action", Mock(side_effect=save))
    monkeypatch.setattr(chat_pipeline_service, "create_crm_lead_from_agent_signal", Mock())
    monkeypatch.setattr(chat_pipeline_service, "_after_reply", lambda _label, work: work())
    monkeypatch.setattr(chat_pipeline_service, "_outage_email_sent_at", {})
    monkeypatch.setattr(email_service, "send_handoff_notification_email", world.staff)
    monkeypatch.setattr(email_service, "send_openrouter_key_alert_email", world.owner)
    # Filter 2 off, so no Cloudflare call; plan routing, credit, usage rows and retrieval are database work.
    monkeypatch.setenv("CONTENT_REVIEW_MODE", "off")
    monkeypatch.setattr(content_review_service, "review_text", Mock(side_effect=AssertionError("Cloudflare called")))
    monkeypatch.setattr(ai_router, "_try_process_flow_message", Mock(return_value=SimpleNamespace(
        handled=False, should_handoff_to_ai=True, reply=None)))
    monkeypatch.setattr(ai_router, "_route_for_enforcement", Mock(return_value=("openai", LUNA)))
    monkeypatch.setattr(ai_router, "_check_ai_credit_before_provider", Mock())
    monkeypatch.setattr(ai_router, "_make_usage_log", Mock())
    monkeypatch.setattr(ai_router, "prepare_chat_prompt", Mock(return_value={
        "direct_reply": None, "prompt": "built prompt", "intent": "question"}))
    # OpenRouter itself.
    monkeypatch.setattr(openrouter_service, "OPENROUTER_API_KEY", SHARED)
    monkeypatch.setattr(openrouter_service.requests, "post", openrouter_post)
    monkeypatch.setattr(openrouter_service, "_moderation_alert_sent_at", {})
    monkeypatch.setattr(openrouter_service, "_in_background", lambda work: work())
    return world


def customer_message(chatbot_id, conversation_id, customer="60123456789"):
    return ai_router.generate_response("When do you open?", customer, chatbot_id, source_channel="telegram",
                                       conversation_id=conversation_id)


def keys_sent(world):
    assert {url for url, _key in world.calls} <= {ai_gateway.openrouter_chat_completions_url()}
    return [KEY_NAMES.get(key, "another key") for _url, key in world.calls]


def assert_handed_to_staff(reply, world, trigger):
    assert isinstance(reply, HandoffAcknowledgement)
    assert reply == chat_pipeline_service.AI_UNAVAILABLE_HANDOFF_REPLY
    assert (reply.company_id, reply.chatbot_id) == (A, BOT_A)
    assert [(row["company_id"], row["payload"]) for row in world.saved] == [(A, {"trigger": trigger})]


# a. A's key is disabled

def test_client_a_on_a_disabled_key_goes_to_staff_and_client_b_on_its_own_key_is_answered(world):
    # The operator stops A's key because of A; OpenRouter then refuses that key.
    assert openrouter_key_service.disable_key_because_of(A) == "pool-1"
    # OpenRouter's documented answer to a disabled key: 401 invalid credentials.
    world.refuse[KEY_A] = http_response(401, {"error": {"code": 401, "message": "User not found."}})

    reply_a = customer_message(BOT_A, conversation_id=81)
    reply_b = customer_message(BOT_B, conversation_id=82)

    assert (world.keys[A]["status"], world.keys[A]["culprit_company_id"]) == ("disabled", A)
    assert world.keys[B]["status"] == "active"
    assert_handed_to_staff(reply_a, world, "ai_unavailable")
    assert reply_b == ANSWER_TEXT
    assert keys_sent(world) == ["key A", "key B"]  # A never borrowed B's key or the shared one


# b. A floods its webhook

SECRET_A, SECRET_B = "A" * 43, "B" * 43  # shaped like token_urlsafe(32)
CHANNELS = {SECRET_A: {"id": 1, "company_id": A, "chatbot_id": BOT_A},
            SECRET_B: {"id": 2, "company_id": B, "chatbot_id": BOT_B}}


def wait_until(condition):
    deadline = time.monotonic() + WAIT
    while not condition():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


@pytest.fixture
def telegram(world, monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(telegram_routes.telegram_blueprint)
    client = app.test_client()
    hold, started, replies = threading.Event(), [], []

    def reply_to_update(update, secret):
        """Stands in for process_telegram_update: the real reply, without its claim, conversation
        and Telegram send (database and Telegram work). A's replies are slow until released."""
        channel = CHANNELS[secret]
        if channel["company_id"] == A:
            started.append(update["update_id"])
            hold.wait(WAIT)
        message = update["message"]
        reply = ai_router.generate_response(message["text"], str(message["chat"]["id"]), channel["chatbot_id"],
                                            source_channel="telegram", conversation_id=message["chat"]["id"])
        with world.lock:
            replies.append((channel["company_id"], reply))

    monkeypatch.setattr(telegram_routes, "assert_telegram_channel_ready", CHANNELS.get)
    monkeypatch.setattr(telegram_routes, "process_telegram_update", reply_to_update)

    def post(secret, chat_id):
        update = {"update_id": chat_id, "message": {"message_id": 1, "chat": {"id": chat_id}, "text": "When do you open?"}}
        return client.post("/telegram/webhook/" + secret, json=update,
                           headers={"X-Telegram-Bot-Api-Secret-Token": secret}).status_code

    yield SimpleNamespace(post=post, hold=hold, started=started, replies=replies)
    hold.set()
    assert drain(), "webhook worker did not finish"


def test_client_a_flooding_its_webhook_gets_503s_and_client_b_is_still_answered(telegram, world):
    statuses = [telegram.post(SECRET_A, 1000 + n) for n in range(2)]
    assert wait_until(lambda: len(telegram.started) == 2), "A's first two replies never started"
    statuses += [telegram.post(SECRET_A, 1002 + n) for n in range(98)]  # 100 customers at once

    assert telegram.post(SECRET_B, 2000) == 200
    assert wait_until(lambda: (B, ANSWER_TEXT) in telegram.replies), "Client B waited behind Client A's flood"
    assert statuses == [200] * 22 + [503] * 78  # 2 running + 20 waiting; Telegram redelivers the rest
    assert len(telegram.started) == 2, "Client A ran more than 2 replies at once"
    assert [company for company, _reply in telegram.replies] == [B]

    telegram.hold.set()
    assert drain(), "webhook worker did not finish"
    assert sorted(company for company, _reply in telegram.replies) == [A] * 22 + [B]
    assert {reply for _company, reply in telegram.replies} == {ANSWER_TEXT}
    assert sorted(keys_sent(world)) == ["key A"] * 22 + ["key B"]


# c. A is suspended

def test_suspended_client_a_gets_no_ai_reply_and_client_b_is_answered(world, caplog):
    world.status[A] = "inactive"

    with caplog.at_level(logging.ERROR):
        reply_a = customer_message(BOT_A, conversation_id=81)
    reply_b = customer_message(BOT_B, conversation_id=82)

    assert reply_a == TROUBLE_REPLY
    assert "Company access is suspended" in caplog.text  # stopped by the suspension, not another error
    assert world.saved == []  # nothing recorded for a suspended Client
    assert reply_b == ANSWER_TEXT
    assert keys_sent(world) == ["key B"]  # A never reached OpenRouter


# d. A reaches its spending cap

def test_client_a_at_its_spending_cap_goes_to_staff_and_client_b_is_answered(world):
    world.refuse[KEY_A] = http_response(403, {"error": {"code": 403, "message": "Key limit exceeded",
                                                        "metadata": {"limit_source": "openrouter_key_limit"}}})

    reply_a = customer_message(BOT_A, conversation_id=81)
    reply_b = customer_message(BOT_B, conversation_id=82)

    assert_handed_to_staff(reply_a, world, "key_limit")
    world.owner.assert_called_once()
    assert f"company {A}" in world.owner.call_args.kwargs["label"]
    assert reply_b == ANSWER_TEXT
    assert keys_sent(world) == ["key A", "key B"]  # one call each: a spent key is never retried
