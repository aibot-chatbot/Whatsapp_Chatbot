"""Phase 5: a failed customer reply may try one same-tier model, only for a message Filter 2 cleared.

OpenRouter, Cloudflare, email and the database are mocked. No request leaves this process.
"""
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
import requests

from app.services import ai_router, chat_pipeline_service, content_review_service, email_service, openrouter_service
from app.services import channel_delivery_service as delivery
from app.services.model_catalog import OPENROUTER_PLAN_MODELS, get_model_tier, is_openrouter_model, same_tier_fallback

PHONE = "60123456789"
LUNA = "openai/gpt-6-luna"
FLASH = "google/gemini-3.8-flash"
ANSWER_TEXT = "We open at 9am."
MODERATION = {"error": {"code": 403, "message": "Your input was flagged", "metadata": {
    "reasons": ["violence"], "flagged_input": "synthetic flagged sentence", "provider_name": "OpenAI", "model_slug": LUNA,
}}}
KEY_LIMIT = {"error": {"code": 403, "message": "Key limit exceeded", "metadata": {"limit_source": "openrouter_key_limit"}}}


def answer(**extra):
    return {"id": "gen-1", "choices": [{"message": {"content": ANSWER_TEXT}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": 0.001}, **extra}


def http_response(status=200, payload=None):
    body = payload if payload is not None else answer()
    response = MagicMock()
    response.status_code = status
    response.ok = status < 400
    response.json.return_value = body
    response.text = json.dumps(body)
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} error", response=response)
    return response


def failure(kind):
    if kind == "timeout":
        return requests.exceptions.ReadTimeout("synthetic timeout")
    if kind == "connection":
        return requests.exceptions.ConnectionError("synthetic connection error")
    return http_response(int(kind), {"error": {"code": int(kind), "message": "synthetic"}})


@pytest.fixture
def world(monkeypatch):
    from app.database import agent_action_repository, conversation_repository
    from app.services import company_status_service

    saved = []

    def save(**fields):
        saved.append(fields)
        return {"id": 40 + len(saved)}

    world = SimpleNamespace(saved=saved, post=Mock(return_value=http_response()), usage=Mock())
    monkeypatch.setenv("CONTENT_REVIEW_MODE", "off")
    monkeypatch.setattr(company_status_service, "ensure_company_operational", Mock())
    monkeypatch.setattr(ai_router, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1}))
    monkeypatch.setattr(chat_pipeline_service, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1}))
    monkeypatch.setattr(conversation_repository, "get_conversation_by_id_and_chatbot", lambda conversation_id, chatbot_id: {
        "id": conversation_id, "chatbot_id": chatbot_id, "source_channel": "telegram", "customer_phone": PHONE})
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated", lambda *_, **__: False)
    monkeypatch.setattr(delivery, "is_pending_handoff_action", lambda action_id, *_: any(
        40 + index == action_id for index, _row in enumerate(saved, 1)))
    monkeypatch.setattr(chat_pipeline_service, "save_agent_action", Mock(side_effect=save))
    monkeypatch.setattr(chat_pipeline_service, "create_crm_lead_from_agent_signal", Mock())
    monkeypatch.setattr(chat_pipeline_service, "_after_reply", lambda _label, _work: None)
    monkeypatch.setattr(chat_pipeline_service, "_outage_email_sent_at", {})
    monkeypatch.setattr(email_service, "send_handoff_notification_email", Mock(return_value=True))
    monkeypatch.setattr(email_service, "send_moderation_alert_email", Mock(return_value=True))
    monkeypatch.setattr(email_service, "send_openrouter_key_alert_email", Mock(return_value=True))
    monkeypatch.setattr(content_review_service, "review_text", Mock(side_effect=AssertionError("Cloudflare called")))
    monkeypatch.setattr(ai_router, "_try_process_flow_message", Mock(return_value=SimpleNamespace(
        handled=False, should_handoff_to_ai=True, reply=None)))
    monkeypatch.setattr(ai_router, "_route_for_enforcement", Mock(return_value=("openai", LUNA)))
    monkeypatch.setattr(ai_router, "_check_ai_credit_before_provider", Mock())
    monkeypatch.setattr(ai_router, "_make_usage_log", world.usage)
    monkeypatch.setattr(ai_router, "prepare_chat_prompt", Mock(return_value={
        "direct_reply": None, "prompt": "built prompt", "intent": "question"}))
    monkeypatch.setattr(ai_router, "process_needs_reply", lambda text, **_: text)
    monkeypatch.setattr(ai_router, "process_booking_reply", lambda text, **_: text)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    monkeypatch.setattr(openrouter_service, "OPENROUTER_API_KEY", "synthetic-openrouter-key")
    monkeypatch.setattr(openrouter_service.requests, "post", world.post)
    monkeypatch.setattr(openrouter_service, "_moderation_alert_sent_at", {})
    monkeypatch.setattr(openrouter_service, "_in_background", lambda work: work())
    return world


def customer_message():
    return ai_router.generate_response("When do you open?", PHONE, 3, source_channel="telegram", conversation_id=8)


def sent_bodies(world):
    return [call.kwargs["json"] for call in world.post.call_args_list]


# One retry, on a same-tier model, for an outage only

@pytest.mark.parametrize("kind", ["timeout", "500", "503", "429"])
def test_a_timeout_5xx_or_429_is_retried_once_on_a_same_tier_model(world, kind):
    world.post.side_effect = [failure(kind), http_response()]

    reply = customer_message()

    assert reply == ANSWER_TEXT
    assert [body["model"] for body in sent_bodies(world)] == [LUNA, FLASH]
    assert get_model_tier(FLASH) == get_model_tier(LUNA)


def test_a_second_failure_goes_to_staff_without_a_third_call(world):
    world.post.side_effect = [failure("500"), failure("timeout")]

    assert customer_message() == chat_pipeline_service.AI_UNAVAILABLE_HANDOFF_REPLY
    assert world.post.call_count == 2


@pytest.mark.parametrize("payload", [MODERATION, KEY_LIMIT], ids=["moderation_block", "key_limit"])
def test_a_moderation_block_or_a_spent_key_is_sent_exactly_once(world, payload):
    world.post.return_value = http_response(403, payload)

    customer_message()

    assert world.post.call_count == 1


@pytest.mark.parametrize("kind", ["400", "401", "402", "404", "connection"])
def test_any_other_failure_is_not_retried(world, kind):
    world.post.side_effect = [failure(kind), http_response()]

    assert customer_message() == chat_pipeline_service.AI_UNAVAILABLE_HANDOFF_REPLY
    assert world.post.call_count == 1


def test_no_request_ever_names_a_models_list(world):
    world.post.side_effect = [failure("502"), http_response()]

    customer_message()

    bodies = sent_bodies(world)
    assert len(bodies) == 2
    assert all("models" not in body and isinstance(body["model"], str) for body in bodies)


def test_the_retry_keeps_the_customers_hashed_identity(world):
    world.post.side_effect = [failure("500"), http_response()]

    customer_message()

    assert {body["user"] for body in sent_bodies(world)} == {openrouter_service.end_user_id(1, PHONE)}


@pytest.mark.parametrize("reported,billed", [(None, FLASH), ("google/gemini-3.8-flash-20261101", "google/gemini-3.8-flash-20261101")])
def test_the_retry_is_billed_as_the_model_that_answered(world, reported, billed):
    world.post.side_effect = [failure("500"), http_response(200, answer(**({"model": reported} if reported else {})))]

    customer_message()

    [usage_call] = world.usage.call_args_list
    assert usage_call.args[0].model == billed


# Only a message Filter 2 positively cleared may fall back (owner decision)

@pytest.mark.parametrize("kind", ["timeout", "500", "429"])
def test_log_mode_never_retries_and_hands_the_chat_to_staff(world, monkeypatch, kind):
    monkeypatch.setenv("CONTENT_REVIEW_MODE", "log")
    world.post.side_effect = [failure(kind), http_response()]

    assert customer_message() == chat_pipeline_service.AI_UNAVAILABLE_HANDOFF_REPLY
    assert world.post.call_count == 1


def test_block_mode_without_a_verdict_never_retries(world, monkeypatch):
    monkeypatch.setenv("CONTENT_REVIEW_MODE", "block")
    monkeypatch.setattr(content_review_service, "review_text", Mock(return_value=content_review_service.UNAVAILABLE))
    world.post.side_effect = [failure("500"), http_response()]

    assert customer_message() == chat_pipeline_service.AI_UNAVAILABLE_HANDOFF_REPLY
    assert world.post.call_count == 1


SAFE = content_review_service.ReviewResult("safe")
UNSAFE = content_review_service.ReviewResult("unsafe", "threat", ("S1",))


@pytest.fixture
def block_mode(world, monkeypatch):
    monkeypatch.setenv("CONTENT_REVIEW_MODE", "block")
    review = Mock(return_value=SAFE)
    monkeypatch.setattr(content_review_service, "review_text", review)
    return review


def test_block_mode_with_a_safe_verdict_retries_once_on_a_same_tier_model(world, block_mode):
    world.post.side_effect = [failure("timeout"), http_response()]

    assert customer_message() == ANSWER_TEXT
    assert [body["model"] for body in sent_bodies(world)] == [LUNA, FLASH]
    block_mode.assert_called_once()


def test_block_mode_with_a_late_safe_verdict_never_retries(world, block_mode, monkeypatch):
    monkeypatch.setattr(content_review_service, "BLOCK_WAIT_SECONDS", 0.05)
    block_mode.side_effect = lambda _text: time.sleep(0.3) or SAFE
    world.post.side_effect = [failure("timeout"), http_response()]

    assert customer_message() == chat_pipeline_service.AI_UNAVAILABLE_HANDOFF_REPLY
    assert world.post.call_count == 1


def test_block_mode_with_a_busy_review_pool_never_retries(world, block_mode, monkeypatch):
    monkeypatch.setattr(chat_pipeline_service, "_content_review_slots", threading.BoundedSemaphore(1))
    chat_pipeline_service._content_review_slots.acquire()
    world.post.side_effect = [failure("timeout"), http_response()]

    assert customer_message() == chat_pipeline_service.AI_UNAVAILABLE_HANDOFF_REPLY
    assert world.post.call_count == 1
    block_mode.assert_not_called()


def test_an_unsafe_verdict_never_reaches_the_provider(world, block_mode, monkeypatch):
    monkeypatch.setattr(email_service, "send_content_flag_alert_email", Mock(return_value=True), raising=False)
    block_mode.return_value = UNSAFE

    customer_message()

    world.post.assert_not_called()


@pytest.mark.parametrize("mode,verdict,cleared", [
    ("block", SAFE, True), ("block", UNSAFE, False), ("block", content_review_service.UNAVAILABLE, False),
    ("log", SAFE, False),
])
def test_only_a_safe_verdict_in_block_mode_clears_the_message(monkeypatch, mode, verdict, cleared):
    monkeypatch.setenv("CONTENT_REVIEW_MODE", mode)
    monkeypatch.setattr(content_review_service, "review_text", Mock(return_value=verdict))
    monkeypatch.setattr(chat_pipeline_service, "_after_reply", lambda _label, work: work())
    monkeypatch.setattr(chat_pipeline_service, "record_content_flag", Mock())
    on_clear = Mock()

    chat_pipeline_service.review_customer_message("When do you open?", company_id=1, chatbot_id=3,
                                                  conversation_id=8, on_clear=on_clear)

    assert on_clear.called is cleared


def test_the_sender_never_decides_to_retry_by_itself(world):
    world.post.side_effect = [failure("500"), http_response()]

    success, _ = openrouter_service._request("prompt", model=LUNA, company_id=1, customer_id=PHONE)

    assert success is False
    assert world.post.call_count == 1


def test_call_provider_falls_back_only_when_told(world):
    world.post.side_effect = [failure("500"), http_response()]

    result = ai_router.call_provider("openai", "hello", PHONE, 3, model_name=LUNA, company_id=1)

    assert result.success is False
    assert world.post.call_count == 1


# Timeouts

def test_a_customer_reply_attempt_waits_at_most_twenty_seconds(world):
    customer_message()

    assert openrouter_service.CHAT_REPLY_TIMEOUT_SECONDS == 20
    assert world.post.call_args.kwargs["timeout"] == 20


def test_background_work_keeps_its_ninety_seconds(world):
    ai_router._call_openrouter_direct("prompt", LUNA, 0.3, company_id=1)

    assert world.post.call_args.kwargs["timeout"] == 90


# The fallback model never leaves the Client's plan, tier or route

PAID_MODELS = sorted({m["value"] for models in OPENROUTER_PLAN_MODELS.values() for m in models})


@pytest.mark.parametrize("model", PAID_MODELS)
def test_a_fallback_stays_on_every_plan_that_offers_the_model_and_on_its_tier(model):
    fallback = same_tier_fallback(model)

    assert fallback is not None and fallback != model
    assert get_model_tier(fallback) == get_model_tier(model)
    assert is_openrouter_model(fallback)
    for models in OPENROUTER_PLAN_MODELS.values():
        offered = [m["value"] for m in models]
        if model in offered:
            assert fallback in offered


def test_an_essential_bot_on_luna_falls_back_to_flash_not_to_an_advanced_only_model():
    assert same_tier_fallback(LUNA) == FLASH


@pytest.mark.parametrize("model", ["deepseek-v4-flash", "@cf/qwen/qwen3-30b-a3b-fp8", "openai/gpt-4.1", "unknown/model", None])
def test_models_outside_the_paid_plans_have_no_fallback(model):
    assert same_tier_fallback(model) is None
