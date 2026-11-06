"""When the AI cannot answer a real customer, the chat goes to staff instead of a dead end."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import ai_router, chat_pipeline_service, email_service
from app.services import channel_delivery_service as delivery
from app.services.billing_guard import BillingLimitError
from app.services.channel_delivery_service import HandoffAcknowledgement

APOLOGY = "Sorry, I'm having trouble replying right now. Please try again later."


@pytest.fixture
def world(monkeypatch):
    from app.database import agent_action_repository, conversation_repository
    from app.services import company_status_service

    saved = []

    def save(**fields):
        saved.append(fields)
        return {"id": 40 + len(saved)}

    def pending(action_id, conversation_id, chatbot_id, company_id):
        return any(40 + index == action_id and row["conversation_id"] == conversation_id
                   and row["intent"] == "handoff_request" for index, row in enumerate(saved, 1))

    def conversation(conversation_id, chatbot_id):
        return {"id": conversation_id, "chatbot_id": chatbot_id, "source_channel": world.source,
                "customer_phone": "60123456789"}

    world = SimpleNamespace(saved=saved, source="telegram", lead=Mock(), email=Mock(return_value=True),
                            provider=Mock(side_effect=TimeoutError("provider timed out")))
    monkeypatch.setattr(company_status_service, "ensure_company_operational", Mock())
    monkeypatch.setattr(ai_router, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1}))
    monkeypatch.setattr(chat_pipeline_service, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1}))
    monkeypatch.setattr(conversation_repository, "get_conversation_by_id_and_chatbot", conversation)
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated",
                        lambda conversation_id, *_, **__: any(row["conversation_id"] == conversation_id for row in saved))
    monkeypatch.setattr(delivery, "is_pending_handoff_action", pending)
    monkeypatch.setattr(chat_pipeline_service, "save_agent_action", Mock(side_effect=save))
    monkeypatch.setattr(chat_pipeline_service, "create_crm_lead_from_agent_signal", world.lead)
    monkeypatch.setattr(email_service, "send_handoff_notification_email", world.email)
    monkeypatch.setattr(chat_pipeline_service, "_after_reply", lambda _label, work: work())
    monkeypatch.setattr(chat_pipeline_service, "_outage_email_sent_at", {})
    monkeypatch.setattr(ai_router, "_try_process_flow_message", Mock(return_value=SimpleNamespace(
        handled=False, should_handoff_to_ai=True, reply=None)))
    monkeypatch.setattr(ai_router, "_route_for_enforcement", Mock(return_value=("deepseek", "synthetic-model")))
    monkeypatch.setattr(ai_router, "_make_usage_log", Mock())
    monkeypatch.setattr(ai_router, "call_provider", world.provider)
    return world


def _reply(conversation_id=8, **kwargs):
    return ai_router.generate_response("Do you open on Sunday?", "60123456789", 3,
                                       source_channel=kwargs.pop("source", "telegram"),
                                       conversation_id=conversation_id, **kwargs)


@pytest.mark.parametrize("failure", ["exception", "error_reply"])
def test_a_broken_ai_hands_the_customer_to_staff(world, failure):
    if failure == "error_reply":
        world.provider.side_effect = None
        world.provider.return_value = ai_router._make_result_from_text(
            "Sorry, I'm having trouble replying right now.", "deepseek", "synthetic-model", success=False)

    reply = _reply()

    assert isinstance(reply, HandoffAcknowledgement)
    assert reply == chat_pipeline_service.AI_UNAVAILABLE_HANDOFF_REPLY
    assert [(row["intent"], row["action_type"], row["conversation_id"], row["company_id"])
            for row in world.saved] == [("handoff_request", "request_handoff", 8, 1)]
    world.lead.assert_called_once()
    assert world.lead.call_args.kwargs["intent"] == "handoff_request"
    world.email.assert_called_once()
    assert world.email.call_args.kwargs["trigger"] == "ai_unavailable"


def test_the_paused_chat_stays_with_staff_on_the_next_message(world):
    _reply()
    assert _reply() == "<SILENT_BOT_RESPONSE>"
    assert len(world.saved) == 1
    assert world.provider.call_count == 1


def test_two_messages_failing_together_hand_over_once(world):
    replies = []

    def second_message_arrives_while_the_first_waits(*_args, **_kwargs):
        if world.provider.call_count == 1:
            replies.append(_reply())  # same conversation, its turn started before any handoff existed
        raise TimeoutError("provider timed out")

    world.provider.side_effect = second_message_arrives_while_the_first_waits
    replies.append(_reply())

    assert len(world.saved) == 1
    assert sorted(isinstance(reply, HandoffAcknowledgement) for reply in replies) == [False, True]
    assert "<SILENT_BOT_RESPONSE>" in replies


@pytest.mark.parametrize("failure", ["usage_log", "success_text_matching_an_error_pattern"])
def test_only_a_failed_provider_call_counts_as_an_outage(world, monkeypatch, failure):
    world.provider.side_effect = None
    if failure == "usage_log":
        # The model answered; only billing bookkeeping broke. That is not an AI outage.
        world.provider.return_value = ai_router._make_result_from_text("We open at 9am.", "deepseek", "synthetic-model")
        monkeypatch.setattr(ai_router, "_should_log_provider_usage", lambda _result: True)
        monkeypatch.setattr(ai_router, "_make_usage_log", Mock(side_effect=RuntimeError("charge RPC failed")))
    else:
        world.provider.return_value = ai_router._make_result_from_text(
            "If the aircond remote keeps having trouble connecting, reset it.", "deepseek", "synthetic-model")

    assert _reply() == APOLOGY
    assert world.saved == []
    world.email.assert_not_called()


@pytest.mark.parametrize("operation", [ai_router.OPERATION_TEST_CHAT, ai_router.OPERATION_TEST_BOT])
def test_dashboard_test_chats_keep_the_plain_apology(world, operation):
    world.source = "web"
    assert _reply(source="web", operation_type=operation) == APOLOGY
    assert world.saved == []
    world.email.assert_not_called()


def test_an_unrecorded_handoff_never_claims_staff_were_told(world):
    chat_pipeline_service.save_agent_action.side_effect = RuntimeError("database unavailable")
    assert _reply() == APOLOGY
    world.lead.assert_not_called()
    world.email.assert_not_called()


def test_an_outage_emails_each_company_once_per_window(world):
    first, second = _reply(8), _reply(9)
    assert isinstance(first, HandoffAcknowledgement) and isinstance(second, HandoffAcknowledgement)
    assert [row["conversation_id"] for row in world.saved] == [8, 9]
    world.email.assert_called_once()


def test_running_out_of_credit_is_not_treated_as_an_outage(world):
    world.provider.side_effect = BillingLimitError("AI credit exhausted")
    with pytest.raises(BillingLimitError):
        _reply()
    assert world.saved == []


@pytest.mark.parametrize("trigger,says,never_says", [
    ("ai_unavailable", "AI assistant could not reply", "requested to speak"),
    ("moderation_block", "safety filter refused a message", "requested to speak"),
    ("customer_request", "has requested to speak with a real staff member", "AI assistant could not reply"),
])
def test_the_staff_email_says_why_and_escapes_customer_text(monkeypatch, trigger, says, never_says):
    from app.database import user_repository
    monkeypatch.setenv("SMTP_SENDER_EMAIL", "noreply@example.test")
    monkeypatch.setenv("SMTP_APP_PASSWORD", "synthetic-password")
    monkeypatch.setattr(user_repository, "get_users_by_company",
                        Mock(return_value=[{"email": "staff@example.test", "status": "active"}]))
    smtp = Mock()
    connect = Mock(return_value=smtp)
    monkeypatch.setattr(email_service.smtplib, "SMTP", connect)
    conversation = {"id": 8, "source_channel": "telegram", "customer_name": "<a href='https://x.test'>Win</a>"}

    assert email_service.send_handoff_notification_email(1, conversation, 3, trigger=trigger) is True

    sent = smtp.sendmail.call_args.args[2]
    assert says in sent and never_says not in sent
    assert "<a href='https://x.test'>" not in sent
    assert "&lt;a href=&#x27;https://x.test&#x27;&gt;Win&lt;/a&gt;" in sent
    assert connect.call_args.kwargs["timeout"] == email_service.SUPPORT_NOTIFICATION_SMTP_TIMEOUT_SECONDS
