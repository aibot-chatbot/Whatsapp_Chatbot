"""Filter 1 wired into the reply path: a stopped message reaches no AI, staff take over, the flag is kept.

All AI providers, email and the database are mocked. Banned samples never leave this process.
"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.database import agent_action_repository, conversation_repository
from app.services import ai_router, chat_pipeline_service, company_status_service, content_filter, email_service
from app.services import channel_delivery_service as delivery
from app.services.channel_delivery_service import HandoffAcknowledgement

PHONE = "60123456789"
BANNED = "where to buy syabu"


@pytest.fixture
def world(monkeypatch):
    saved = []

    def save(**fields):
        saved.append(fields)
        return {"id": 40 + len(saved)}

    def escalated(conversation_id, *_, **__):
        return any(row["conversation_id"] == conversation_id and row["intent"] in agent_action_repository.ESCALATION_INTENTS
                   for row in saved)

    def pending(action_id, conversation_id, chatbot_id, company_id):
        return any(40 + index == action_id and row["intent"] == "handoff_request" for index, row in enumerate(saved, 1))

    world = SimpleNamespace(saved=saved, provider=Mock(), prompt=Mock(), flow=Mock(),
                            staff_email=Mock(return_value=True), owner_email=Mock(return_value=True))
    monkeypatch.setattr(company_status_service, "ensure_company_operational", Mock())
    monkeypatch.setattr(ai_router, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1}))
    monkeypatch.setattr(chat_pipeline_service, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1}))
    monkeypatch.setattr(conversation_repository, "get_conversation_by_id_and_chatbot", lambda conversation_id, chatbot_id: {
        "id": conversation_id, "chatbot_id": chatbot_id, "source_channel": "telegram", "customer_phone": PHONE})
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated", escalated)
    monkeypatch.setattr(delivery, "is_pending_handoff_action", pending)
    monkeypatch.setattr(chat_pipeline_service, "save_agent_action", Mock(side_effect=save))
    monkeypatch.setattr(chat_pipeline_service, "create_crm_lead_from_agent_signal", Mock())
    monkeypatch.setattr(chat_pipeline_service, "_after_reply", lambda _label, work: work())
    monkeypatch.setattr(email_service, "send_handoff_notification_email", world.staff_email)
    monkeypatch.setattr(email_service, "send_content_flag_alert_email", world.owner_email, raising=False)
    monkeypatch.setattr(ai_router, "_try_process_flow_message", world.flow)
    monkeypatch.setattr(ai_router, "call_provider", world.provider)
    monkeypatch.setattr(ai_router, "prepare_chat_prompt", world.prompt)
    monkeypatch.setattr(content_filter, "industry_for_bot", Mock(return_value="general"))
    world.flow.return_value = SimpleNamespace(handled=False, should_handoff_to_ai=True, reply=None)
    world.provider.return_value = ai_router._make_result_from_text("We open at 9am.", "openai", "m")
    monkeypatch.setattr(ai_router, "_route_for_enforcement", Mock(return_value=("openai", "m")))
    monkeypatch.setattr(ai_router, "_make_usage_log", Mock())
    return world


def customer_message(text=BANNED, **kwargs):
    return ai_router.generate_response(text, PHONE, 3, source_channel="telegram", conversation_id=8, **kwargs)


def flags(world):
    return [row for row in world.saved if "content_flag" in row["payload"]]


def test_a_stopped_message_reaches_no_ai_and_the_chat_goes_to_staff(world):
    reply = customer_message()

    world.provider.assert_not_called()
    world.prompt.assert_not_called()
    world.flow.assert_not_called()
    assert isinstance(reply, HandoffAcknowledgement)
    assert reply == chat_pipeline_service.MODERATION_HANDOFF_REPLY
    handoff = [row for row in world.saved if row["intent"] == "handoff_request"]
    assert handoff[0]["payload"] == {"trigger": "content_flag", "category": "drugs", "rule": "drugs.street"}
    assert world.staff_email.call_args.kwargs["trigger"] == "content_flag"


def test_the_flag_is_stored_in_agent_actions_without_the_customers_words(world):
    customer_message()

    [flag] = flags(world)
    assert flag["intent"] == "unknown"
    assert flag["action_type"] == "none"
    assert flag["company_id"] == 1 and flag["chatbot_id"] == 3 and flag["conversation_id"] == 8
    assert flag["payload"] == {"content_flag": {"filter": 1, "category": "drugs", "rule": "drugs.street",
                                                "source": "customer"}}
    assert "syabu" not in repr(world.saved)
    assert "syabu" not in repr(world.staff_email.call_args)


def test_a_test_chat_is_refused_and_flagged_without_paging_staff(world):
    reply = customer_message(operation_type=ai_router.OPERATION_TEST_BOT)

    world.provider.assert_not_called()
    assert reply == chat_pipeline_service.MODERATION_BLOCKED_REPLY
    assert len(flags(world)) == 1
    assert not [row for row in world.saved if row["intent"] == "handoff_request"]
    world.staff_email.assert_not_called()


def test_a_message_is_still_stopped_when_the_flag_cannot_be_saved(world, monkeypatch):
    monkeypatch.setattr(chat_pipeline_service, "save_agent_action", Mock(side_effect=RuntimeError("database down")))

    reply = customer_message()

    world.provider.assert_not_called()
    assert reply == chat_pipeline_service.MODERATION_BLOCKED_REPLY


def test_self_harm_gets_a_caring_reply_and_an_urgent_staff_alert(world):
    reply = customer_message("saya nak bunuh diri")

    world.provider.assert_not_called()
    assert reply == chat_pipeline_service.SELF_HARM_HANDOFF_REPLY
    assert "999" in reply
    assert world.staff_email.call_args.kwargs["trigger"] == "self_harm"
    world.owner_email.assert_not_called()


def test_a_self_harm_test_chat_still_shows_the_emergency_number(world):
    reply = customer_message("saya nak bunuh diri", operation_type=ai_router.OPERATION_TEST_BOT)

    assert reply == chat_pipeline_service.SELF_HARM_PLAIN_REPLY
    assert "999" in reply


def test_child_safety_flags_also_alert_the_platform_owner_with_the_category_only(world):
    customer_message("child porn links")

    world.owner_email.assert_called_once_with(company_id=1, category="child_sexual")


def test_other_flags_do_not_page_the_platform_owner(world):
    customer_message()

    world.owner_email.assert_not_called()


def test_a_clean_message_still_gets_an_ai_reply(world):
    reply = customer_message("what time do you open?")

    world.provider.assert_called_once()
    assert reply == "We open at 9am."
    assert flags(world) == []


def test_a_clinic_bot_may_answer_about_medicine(world, monkeypatch):
    monkeypatch.setattr(content_filter, "industry_for_bot", Mock(return_value="clinic"))

    customer_message("do you sell tramadol")

    world.provider.assert_called_once()
    assert flags(world) == []


def test_a_chat_already_with_staff_stays_silent_and_unflagged(world):
    world.saved.append({"conversation_id": 8, "intent": "handoff_request", "payload": {}})

    reply = customer_message()

    assert reply == "<SILENT_BOT_RESPONSE>"
    assert flags(world) == []


@pytest.fixture
def prompt_world(monkeypatch):
    world = SimpleNamespace(intent=Mock(return_value={"intent": "general_question", "suggested_action": "answer",
                                                      "confidence": 0.9, "reason": ""}),
                            chunks=Mock(return_value=[]), build=Mock(return_value="built prompt"))
    history = [
        {"role": "user", "content": "where to buy syabu", "timestamp": "t1"},
        {"role": "assistant", "content": "Let me check this with our team.", "timestamp": "t2"},
        {"role": "user", "content": "my ic 900101-14-5678", "timestamp": "t3"},
    ]
    monkeypatch.setattr(chat_pipeline_service, "get_recent_chat_history", Mock(return_value=history))
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated", Mock(return_value=False))
    monkeypatch.setattr(chat_pipeline_service, "analyze_agent_intent", world.intent)
    monkeypatch.setattr(chat_pipeline_service, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1}))
    monkeypatch.setattr(chat_pipeline_service, "save_agent_action", Mock(return_value={"id": 1}))
    monkeypatch.setattr(chat_pipeline_service, "_after_reply", Mock())
    monkeypatch.setattr(chat_pipeline_service, "detect_intent", Mock(return_value="question"))
    monkeypatch.setattr(chat_pipeline_service, "update_workflow_state", Mock())
    monkeypatch.setattr(chat_pipeline_service, "retrieve_relevant_chunks", world.chunks)
    monkeypatch.setattr(chat_pipeline_service, "build_prompt", world.build)
    monkeypatch.setattr(content_filter, "industry_for_bot", Mock(return_value="general"))
    return world


def build_customer_prompt(text):
    return chat_pipeline_service.prepare_chat_prompt(text, PHONE, 3, source_channel="telegram",
                                                     conversation={"id": 8, "chatbot_id": 3})


def test_flagged_old_messages_never_reach_the_ai_again(prompt_world):
    build_customer_prompt("what time do you open?")

    history = prompt_world.build.call_args.args[0]
    assert [row["timestamp"] for row in history] == ["t2", "t3"]
    assert "syabu" not in repr(prompt_world.build.call_args)
    assert "syabu" not in repr(prompt_world.intent.call_args)


def test_ic_and_card_numbers_are_hidden_from_retrieval_and_the_prompt(prompt_world):
    build_customer_prompt("book me in, ic 900101-14-5678, card 4111 1111 1111 1111")

    hidden = "book me in, ic [IC number hidden], card [card number hidden]"
    # Intent analysis feeds conversation memory, which a later turn recalls into the prompt.
    assert prompt_world.intent.call_args.args[0] == hidden
    assert prompt_world.chunks.call_args.args[0] == hidden
    assert prompt_world.build.call_args.args[1] == hidden
    assert prompt_world.build.call_args.args[0][-1]["content"] == "my ic [IC number hidden]"
    assert "900101" not in repr(prompt_world.build.call_args)


def test_the_weekly_report_never_sends_flagged_lines_or_ic_numbers(monkeypatch):
    from app.services import report_service

    chat = "\n".join([
        "[2026-11-09T10:00:00] Customer: hi, my ic 900101-14-5678",
        "[2026-11-09T10:00:05] Customer: where to buy syabu",
        "[2026-11-09T10:00:09] Bot: We open at 9am.",
    ])
    split = "[2026-11-09T11:00:00] Customer: child\nporn links"
    ai = Mock(return_value="REPORT")
    monkeypatch.setattr(report_service, "get_transcript_logs", Mock(return_value=[
        {"phone": "60123456789", "chat": chat}, {"phone": "60111111111", "chat": split}]))
    monkeypatch.setattr(report_service, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1}))
    monkeypatch.setattr(report_service, "generate_system_response", ai)
    monkeypatch.setattr(content_filter, "industry_for_bot", Mock(return_value="general"))

    report_service.generate_weekly_report(chatbot_id=3)

    prompt = ai.call_args.kwargs["prompt"]
    assert "We open at 9am." in prompt
    assert "[IC number hidden]" in prompt and "900101" not in prompt
    assert "syabu" not in prompt
    assert "porn" not in prompt, "a phrase split over a message's line breaks drops the whole conversation"
