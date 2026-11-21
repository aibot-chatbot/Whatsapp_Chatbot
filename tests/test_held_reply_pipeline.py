"""Live channel replies are held before any hidden instruction can take effect."""
import logging
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask, g
import pytest

from app.database import agent_action_repository, conversation_repository
from app.services import ai_router, channel_delivery_service, chat_pipeline_service as pipeline
from app.services import deepseek_service, email_service, reply_review_service
from tests.test_reply_check_hook import MESSAGE, chat


VISIBLE = "Private shelf quote: RM937."
NOTES = '\n<<NEEDS {"goal":"private need"}>>\n<<BOOKING {"notes":"private booking"}>>'
HOLDING = "Let me check with our team"


@pytest.fixture
def live(chat, monkeypatch):
    bot = {"id": 7, "company_id": 11, "hold_risky_replies": True}
    conversation = {"id": 13, "chatbot_id": 7, "source_channel": "whatsapp"}
    rows, actions = [], []
    monkeypatch.delenv("REPLY_HOLD_MODE", raising=False)
    monkeypatch.setenv("REPLY_REVIEW_MODE", "log")
    monkeypatch.setattr(ai_router, "get_bot_by_id", lambda _: bot)
    monkeypatch.setattr(pipeline, "get_bot_by_id", lambda _: bot)
    monkeypatch.setattr(conversation_repository, "get_conversation_by_id_and_chatbot", lambda *_: conversation)
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated",
                        lambda *a, **kw: any(row["action_type"] == "request_handoff" for row in actions))
    monkeypatch.setattr(channel_delivery_service, "is_pending_handoff_action",
                        lambda *ids: ids == (23, 13, 7, 11) and bool(actions))
    monkeypatch.setattr(pipeline, "create_held_reply", lambda **row: rows.append(row), raising=False)

    def save_action(**row):
        actions.append(row)
        return {"id": 23}

    monkeypatch.setattr(pipeline, "_record_agent_action", save_action)
    monkeypatch.setattr(pipeline, "create_crm_lead_from_agent_signal", Mock())
    email = Mock()
    monkeypatch.setattr(email_service, "send_handoff_notification_email", email)
    review = Mock(return_value={"verdict": "pass", "category": "none", "subtype": "none"})
    monkeypatch.setattr(reply_review_service, "review_reply", review)
    monkeypatch.setattr(ai_router, "_route_for_enforcement", lambda *_: ("deepseek", "test-model"))

    def generate(visible=VISIBLE, *, operation=ai_router.OPERATION_CHAT_REPLY, legacy=False):
        chat.sdk.chat.completions.create.return_value.choices[0].message.content = visible + NOTES
        if legacy:
            return deepseek_service.generate_response(MESSAGE, "customer", 7)
        return ai_router.generate_response(MESSAGE, "customer", 7, operation_type=operation,
                                           conversation_id=13)

    return SimpleNamespace(bot=bot, rows=rows, actions=actions, email=email, review=review,
                           generate=generate, events=chat.events)


@pytest.mark.parametrize("legacy", [False, True], ids=["router", "legacy-deepseek"])
def test_code_finding_stores_visible_text_and_pauses_before_workflows(live, caplog, legacy):
    caplog.set_level(logging.INFO)
    answer = live.generate(legacy=legacy)
    assert answer == HOLDING
    assert isinstance(answer, channel_delivery_service.HandoffAcknowledgement)
    assert live.rows == [dict(company_id=11, chatbot_id=7, conversation_id=13, draft=VISIBLE,
                              category="facts", subtype="price")]
    assert agent_action_repository.is_conversation_escalated(13, 7)
    action, = live.actions
    assert action["payload"] == {"trigger": "reply_check", "category": "facts", "subtype": "price"}
    assert action["reason"] == "A price that is not in your knowledge."
    assert live.events == []
    assert live.review.call_args.args == (VISIBLE,)
    live.email.assert_called_once()
    assert live.email.call_args.kwargs["conversation"] == {"id": 13}
    assert live.email.call_args.kwargs["reply_check"] == {"category": "facts", "subtype": "price"}
    for marker in ("RM937", "private need", "private booking", "Private shelf quote"):
        assert marker not in repr(live.actions) + repr(live.email.call_args) + caplog.text


@pytest.mark.parametrize("draft,category,subtype", [
    ("The other customer's name is Demo Plum.", "leak", "other_customer"),
    (VISIBLE, "promise", "refund"),
    ("A full refund is guaranteed. The shelf is RM937.", "leak", "internal"),
])
def test_reviewer_hold_uses_strongest_safe_reason(live, draft, category, subtype, caplog):
    live.review.return_value = dict(verdict="hold", category=category, subtype=subtype,
                                    reason="Private reviewer explanation.")
    assert live.generate(draft) == HOLDING
    assert (live.rows[0]["category"], live.rows[0]["subtype"]) == (category, subtype)
    assert live.events == []
    assert "Private reviewer explanation." not in repr(live.actions) + repr(live.email.call_args) + caplog.text


def test_reviewer_error_delivers_without_finding(live, caplog):
    caplog.set_level(logging.INFO)
    live.review.side_effect = TimeoutError("Private exception.")
    assert live.generate("What price are you asking about?") == "What price are you asking about?" + NOTES + " (processed)"
    live.review.assert_called_once()
    assert live.rows == []
    assert "reason=error_TimeoutError" in caplog.text
    assert "Private exception." not in caplog.text


def test_reviewer_timeout_still_holds_a_code_finding(live):
    live.review.side_effect = TimeoutError()
    assert live.generate() == HOLDING
    assert live.rows[0]["subtype"] == "price"
    assert live.events == []


@pytest.mark.parametrize("provider", ["openai", "cloudflare"])
def test_router_holds_other_providers_before_processing_notes(chat, live, provider):
    assert chat.generate(provider) == HOLDING
    assert len(live.rows) == 1
    assert live.rows[0]["category"] == "facts"
    assert live.events == []


@pytest.mark.parametrize("mode", ["bot_off", "kill_switch", "check_off", "test_chat", "test_lab", "publish"])
def test_nonblocking_modes_preserve_existing_reply_processing(live, monkeypatch, mode):
    deferred = []
    monkeypatch.setattr(pipeline, "_after_reply", lambda _, fn: deferred.append(fn))
    operation = ai_router.OPERATION_CHAT_REPLY
    if mode == "bot_off":
        live.bot.pop("hold_risky_replies")
    elif mode == "kill_switch":
        monkeypatch.setenv("REPLY_HOLD_MODE", "off")
    elif mode == "check_off":
        monkeypatch.setenv("REPLY_CHECK_MODE", "off")
    elif mode == "test_chat":
        operation = ai_router.OPERATION_TEST_CHAT
    else:
        operation = ai_router.OPERATION_TEST_BOT
    with Flask(__name__).test_request_context():
        g.publish_test = mode == "publish"
        assert live.generate(operation=operation) == VISIBLE + NOTES + " (processed)"
        if mode in {"publish", "test_lab"}:
            assert g.reply_grade["status"] == "attention"
    if mode in {"bot_off", "kill_switch", "test_chat"}:
        live.review.assert_not_called()
        for write_audit in deferred:
            write_audit()
        live.review.assert_called_once()
    if mode == "check_off":
        live.review.assert_not_called()
    assert not live.rows
    live.email.assert_not_called()


def test_failed_storage_never_delivers_the_draft_or_processes_its_notes(live, monkeypatch, caplog):
    monkeypatch.setattr(pipeline, "create_held_reply", Mock(side_effect=ValueError(VISIBLE)), raising=False)
    assert VISIBLE not in live.generate()
    assert live.events == []
    assert VISIBLE not in caplog.text


def test_legacy_opt_in_lookup_failure_keeps_the_background_audit(live, monkeypatch, caplog):
    monkeypatch.setattr(pipeline, "get_bot_by_id", Mock(side_effect=OSError("private lookup detail")))
    deferred = []
    monkeypatch.setattr(pipeline, "_after_reply", lambda _, callback: deferred.append(callback))
    assert live.generate(legacy=True) == VISIBLE + NOTES
    live.review.assert_not_called()
    assert len(deferred) == 1
    deferred[0]()
    live.review.assert_called_once()
    assert live.actions[0]["payload"]["reply_check"]["mode"] == "log"
    assert live.rows == [] and "private lookup detail" not in caplog.text


@pytest.mark.parametrize("category,subtype,label", [
    ("facts", "price", "A price that is not in your knowledge."),
    (VISIBLE, VISIBLE, "This draft needs staff review."),
])
def test_staff_email_shows_reason_and_ids_only(monkeypatch, category, subtype, label):
    monkeypatch.setattr("app.database.user_repository.get_users_by_company",
                        lambda _: [{"email": "staff@example.test", "status": "active"}])
    monkeypatch.setenv("SMTP_SENDER_EMAIL", "sender@example.test")
    monkeypatch.setenv("SMTP_APP_PASSWORD", "synthetic-test-only")
    smtp = Mock()
    monkeypatch.setattr(email_service.smtplib, "SMTP", lambda *a, **kw: smtp)
    assert email_service.send_handoff_notification_email(
        11, {"id": 13, "source_channel": "web", "customer_name": VISIBLE}, 7,
        trigger="reply_check", reply_check={"category": category, "subtype": subtype})
    sent = smtp.sendmail.call_args.args[2]
    assert label in sent and "bot_id=7" in sent and "conversation_id=13" in sent
    if category == "facts":
        assert "Facts" in sent
    assert VISIBLE not in sent and "has requested to speak" not in sent
