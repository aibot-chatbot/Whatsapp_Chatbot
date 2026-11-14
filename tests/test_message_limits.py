"""Phase 5: the length cap and the rate limits stop a message before any filter, retrieval or AI call.

Every external service is mocked. Limits are checked with a fake clock or within one real second.
"""
import importlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import ai_router, chat_pipeline_service, content_review_service, email_service, message_limits
from app.services import web_widget_service
from app.services import channel_delivery_service as delivery

PHONE = "60123456789"
ANSWER = "We open at 9am."
COMPANY_OF_BOT = {3: 1, 5: 2}


@pytest.fixture(autouse=True)
def fresh_limits(monkeypatch):
    monkeypatch.setenv("RATELIMIT_ENABLED", "true")
    monkeypatch.setattr(message_limits, "_customers", {})
    monkeypatch.setattr(message_limits, "_clients", {})


def check(message="hi", company_id=1, chatbot_id=3, customer_id=PHONE, now=1000.0):
    return message_limits.check(message, company_id=company_id, chatbot_id=chatbot_id,
                                customer_id=customer_id, now=now)


# The length cap

def test_the_cap_is_2000_characters_and_the_widget_uses_the_same_one():
    assert message_limits.MAX_MESSAGE_LENGTH == 2000
    assert web_widget_service.MAX_MESSAGE_LENGTH == message_limits.MAX_MESSAGE_LENGTH
    assert check("x" * 2000) is None
    assert check("x" * 2001, now=1001.0) == message_limits.TOO_LONG_REPLY


# The customer limit

def test_a_customer_gets_eight_messages_a_minute_then_one_slow_down_then_silence():
    replies = [check(now=1000.0 + second) for second in range(11)]

    assert replies == [None] * 8 + [message_limits.SLOW_DOWN_REPLY] + ["<SILENT_BOT_RESPONSE>"] * 2


def test_the_customer_is_answered_again_once_the_minute_has_passed():
    for second in range(9):
        check(now=1000.0 + second)

    assert check(now=1068.0) is None


def test_a_new_burst_after_the_window_gets_a_new_slow_down():
    for second in range(9):
        check(now=1000.0 + second)
    replies = [check(now=1070.0 + second) for second in range(9)]

    assert replies == [None] * 8 + [message_limits.SLOW_DOWN_REPLY]


def test_each_customer_is_limited_separately_on_each_bot():
    for second in range(8):
        check(now=1000.0 + second)

    assert check(customer_id="60199999999", now=1009.0) is None
    assert check(chatbot_id=4, now=1009.0) is None
    assert check(now=1009.0) == message_limits.SLOW_DOWN_REPLY


# The Client limit

def test_a_client_gets_120_messages_a_minute_then_a_busy_reply():
    replies = [check(customer_id=f"customer-{n}", now=1000.0 + n / 10) for n in range(121)]

    assert replies == [None] * 120 + [message_limits.BUSY_REPLY]


def test_client_a_at_its_limit_never_blocks_client_b():
    for n in range(120):
        check(customer_id=f"customer-{n}", now=1000.0)

    assert check(company_id=1, customer_id="late", now=1001.0) == message_limits.BUSY_REPLY
    assert check(company_id=2, chatbot_id=5, customer_id="late", now=1001.0) is None


# Switches

def test_the_rate_limits_follow_the_apps_rate_limit_switch_but_the_cap_does_not(monkeypatch):
    monkeypatch.setenv("RATELIMIT_ENABLED", "false")

    assert {check(now=1000.0 + second) for second in range(20)} == {None}
    assert check("x" * 2001) == message_limits.TOO_LONG_REPLY


def test_each_limit_can_be_set_by_environment(monkeypatch):
    monkeypatch.setenv("MAX_MESSAGE_LENGTH", "50")
    monkeypatch.setenv("CUSTOMER_MESSAGES_PER_MINUTE", "2")
    monkeypatch.setenv("CLIENT_MESSAGES_PER_MINUTE", "3")
    try:
        reloaded = importlib.reload(message_limits)
        assert (reloaded.MAX_MESSAGE_LENGTH, reloaded.CUSTOMER_MESSAGES_PER_MINUTE,
                reloaded.CLIENT_MESSAGES_PER_MINUTE) == (50, 2, 3)
    finally:
        for name in ("MAX_MESSAGE_LENGTH", "CUSTOMER_MESSAGES_PER_MINUTE", "CLIENT_MESSAGES_PER_MINUTE"):
            monkeypatch.delenv(name)
        importlib.reload(message_limits)


# Wired into the reply path

@pytest.fixture
def world(monkeypatch):
    from app.database import agent_action_repository, conversation_repository
    from app.services import company_status_service

    saved = []

    def save(**fields):
        saved.append(fields)
        return {"id": 40 + len(saved)}

    world = SimpleNamespace(provider=Mock(return_value=ai_router._make_result_from_text(ANSWER, "openai", "m")),
                            flow=Mock(return_value=SimpleNamespace(handled=False, should_handoff_to_ai=True, reply=None)),
                            review=Mock(return_value=content_review_service.ReviewResult("safe")),
                            filter1=Mock(return_value=None), cooldown_handoff=Mock(), flag=Mock(),
                            save=Mock(side_effect=save), staff_email=Mock(return_value=True))
    monkeypatch.setenv("CONTENT_REVIEW_MODE", "block")
    monkeypatch.setattr(delivery, "is_pending_handoff_action", lambda action_id, *_: any(
        40 + index == action_id for index, _row in enumerate(saved, 1)))
    monkeypatch.setattr(chat_pipeline_service, "create_crm_lead_from_agent_signal", Mock())
    monkeypatch.setattr(chat_pipeline_service, "get_bot_by_id", lambda chatbot_id: {
        "id": chatbot_id, "company_id": COMPANY_OF_BOT[chatbot_id]})
    monkeypatch.setattr(email_service, "send_handoff_notification_email", world.staff_email)
    monkeypatch.setattr(company_status_service, "ensure_company_operational", Mock())
    monkeypatch.setattr(ai_router, "get_bot_by_id", lambda chatbot_id: {"id": chatbot_id,
                                                                        "company_id": COMPANY_OF_BOT[chatbot_id]})
    monkeypatch.setattr(conversation_repository, "get_conversation_by_id_and_chatbot", lambda conversation_id, chatbot_id: {
        "id": conversation_id, "chatbot_id": chatbot_id, "source_channel": "telegram"})
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated", lambda *_, **__: False)
    monkeypatch.setattr(content_review_service, "review_text", world.review)
    monkeypatch.setattr(ai_router.content_filter, "check_bot_text", world.filter1)
    monkeypatch.setattr(ai_router, "hand_off_during_cooldown", world.cooldown_handoff)
    monkeypatch.setattr(ai_router, "record_content_flag", world.flag)
    monkeypatch.setattr(chat_pipeline_service, "save_agent_action", world.save)
    monkeypatch.setattr(ai_router, "_try_process_flow_message", world.flow)
    monkeypatch.setattr(ai_router, "call_provider", world.provider)
    monkeypatch.setattr(ai_router, "_route_for_enforcement", Mock(return_value=("openai", "m")))
    monkeypatch.setattr(ai_router, "_make_usage_log", Mock())
    monkeypatch.setattr(ai_router, "process_needs_reply", lambda text, **_: text)
    monkeypatch.setattr(ai_router, "process_booking_reply", lambda text, **_: text)
    return world


def customer_message(text="When do you open?", chatbot_id=3, customer=PHONE, **kwargs):
    return ai_router.generate_response(text, customer, chatbot_id, source_channel="telegram",
                                       conversation_id=8, **kwargs)


def test_a_2001_character_message_reaches_no_filter_retrieval_or_ai(world):
    reply = customer_message("When do you open? " + "x" * 2001)

    assert reply == message_limits.TOO_LONG_REPLY
    world.provider.assert_not_called()
    world.review.assert_not_called()
    world.filter1.assert_not_called()
    world.flow.assert_not_called()
    world.staff_email.assert_not_called()


# Safety is never cut: self-harm gets the helpline and staff whatever the limits say

SELF_HARM = "saya nak bunuh diri"


def assert_helpline_once(world, reply):
    assert reply == chat_pipeline_service.SELF_HARM_HANDOFF_REPLY
    assert "Befrienders KL" in reply and "03-7627 2929" in reply and "999" in reply
    world.staff_email.assert_called_once()
    assert world.staff_email.call_args.kwargs["trigger"] == "self_harm"
    world.provider.assert_not_called()
    world.review.assert_not_called()


def test_a_self_harm_message_over_2000_characters_gets_the_helpline(world):
    assert_helpline_once(world, customer_message(SELF_HARM + " " + "x" * 2001))


def test_a_self_harm_message_after_the_customer_limit_gets_the_helpline(world):
    for _ in range(9):
        customer_message("When do you open?")
    world.provider.reset_mock()
    world.review.reset_mock()

    assert_helpline_once(world, customer_message(SELF_HARM))
    assert len(message_limits._customers[(3, PHONE)].times) == 8


def test_a_self_harm_message_while_the_client_is_at_its_limit_gets_the_helpline(world, monkeypatch):
    monkeypatch.setattr(message_limits, "CLIENT_MESSAGES_PER_MINUTE", 3)
    for n in range(3):
        customer_message(customer=f"customer-{n}")
    assert customer_message(customer="customer-busy") == message_limits.BUSY_REPLY
    world.provider.reset_mock()
    world.review.reset_mock()

    assert_helpline_once(world, customer_message(SELF_HARM))
    assert len(message_limits._clients[1].times) == 3
    assert (3, PHONE) not in message_limits._customers


def test_a_2000_character_message_is_answered(world):
    assert customer_message("x" * 2000) == ANSWER
    world.provider.assert_called_once()
    world.review.assert_called_once()


def test_a_long_test_chat_is_refused_the_same_way(world):
    assert customer_message("x" * 2001, operation_type=ai_router.OPERATION_TEST_CHAT) == message_limits.TOO_LONG_REPLY
    world.provider.assert_not_called()


def test_the_customer_limit_never_hands_off_or_counts_as_a_flag(world):
    replies = [customer_message() for _ in range(10)]

    assert replies == [ANSWER] * 8 + [message_limits.SLOW_DOWN_REPLY, "<SILENT_BOT_RESPONSE>"]
    assert world.provider.call_count == 8
    assert world.review.call_count == 8
    world.cooldown_handoff.assert_not_called()
    world.flag.assert_not_called()
    world.save.assert_not_called()


def test_an_owner_test_chat_is_never_silenced_by_the_customer_limit(world):
    replies = {customer_message(operation_type=ai_router.OPERATION_TEST_CHAT) for _ in range(10)}

    assert replies == {ANSWER}


def test_client_a_at_its_limit_does_not_block_client_b_on_the_reply_path(world, monkeypatch):
    monkeypatch.setattr(message_limits, "CLIENT_MESSAGES_PER_MINUTE", 3)

    client_a = [customer_message(chatbot_id=3, customer=f"customer-{n}") for n in range(4)]
    client_b = customer_message(chatbot_id=5, customer="customer-b")

    assert client_a == [ANSWER] * 3 + [message_limits.BUSY_REPLY]
    assert client_b == ANSWER
    assert world.provider.call_count == 4
    assert world.review.call_count == 4
