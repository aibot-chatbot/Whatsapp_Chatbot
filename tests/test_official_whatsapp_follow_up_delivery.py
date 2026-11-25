import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import channel_delivery_service as delivery
from app.services import follow_up_service as follow
from app.utils import whatsapp_utils as wa


NOW = datetime(2026, 11, 22, 2, tzinfo=timezone.utc)


@pytest.fixture
def scheduled(monkeypatch):
    bot = {"id": 2, "company_id": 1, "followups_enabled": True, "followup_template_id": 25}
    chat = {"id": 3, "chatbot_id": 2, "chatbots": bot, "platform_user_id": "MY.wa-id",
            "customer_phone": "+6011111111", "source_channel": "whatsapp",
            "source_channel_id": 10, "source_provider_id": "phone-id",
            "customer_needs": {"stage": "recommend"}}
    channel = {"id": 10, "company_id": 1, "chatbot_id": 2, "connection_status": "connected",
               "is_active": True, "verified_at": "today", "phone_number_id": "phone-id",
               "whatsapp_business_account_id": "waba", "access_token": "fake"}
    repo = Mock()
    repo.claim_due.return_value = [{"id": 9, "company_id": 1, "chatbot_id": 2, "conversation_id": 3,
                                    "platform": "whatsapp", "mode": "gentle", "kind": "sales",
                                    "source_message_id": 4, "touch_count": 0}]
    repo.latest_customer.return_value = {"id": 4, "created_at": (NOW - timedelta(hours=23)).isoformat()}
    repo.latest_lead.return_value = None
    repo.receipts.return_value = []
    repo.conversation.return_value = chat
    repo.consent_status.return_value = "granted"
    monkeypatch.setattr(follow, "repo", repo)
    monkeypatch.setattr(follow, "ensure_company_operational", Mock())
    monkeypatch.setattr(follow, "can_use_plan_feature", Mock(return_value=True))
    monkeypatch.setattr(follow, "is_conversation_escalated", Mock(return_value=False))
    monkeypatch.setattr(delivery, "get_whatsapp_channel_by_id", lambda channel_id: channel if channel_id == 10 else None)
    send = Mock(return_value=SimpleNamespace(status_code=201, json=lambda: {"messages": [{"id": "wamid.reply"}]}))
    draft = Mock(return_value="Would you like the measurements?")
    save = Mock(return_value={"id": 7})
    monkeypatch.setattr(wa, "send_message", send)
    monkeypatch.setattr(follow, "generate_follow_up_draft", draft)
    monkeypatch.setattr(follow, "save_message", save)
    monkeypatch.setenv("FOLLOWUP_SCHEDULER_ENABLED", "true")
    return SimpleNamespace(bot=bot, chat=chat, channel=channel, repo=repo, send=send, draft=draft, save=save)


def test_whatsapp_inside_window_records_accepted_text_from_original_number(scheduled):
    s = scheduled
    follow.run_due_follow_ups(now=NOW)
    payload = json.loads(s.send.call_args.args[0])
    assert (payload["to"], payload["type"], payload["text"]["body"]) == ("MY.wa-id", "text", s.draft.return_value)
    assert s.send.call_args.kwargs["channel"] is s.channel
    s.repo.consent_status.assert_called_with(1, "whatsapp", "MY.wa-id")
    assert s.save.call_args.kwargs["delivery_status"] == "sent"
    assert s.save.call_args.kwargs["platform_message_id"] == "wamid.reply"
    assert s.repo.settle.call_args.args[1]["touch_count"] == 1


@pytest.mark.parametrize("status", ["APPROVED", "PAUSED", "REJECTED", None])
def test_whatsapp_at_24_hours_only_sends_eligible_original_waba_template(scheduled, monkeypatch, status):
    from app.database import db

    s = scheduled
    s.repo.latest_customer.return_value["created_at"] = (NOW - timedelta(hours=24)).isoformat()
    row = {"id": 25, "company_id": 1, "waba_id": "waba", "status": status, "category": "MARKETING",
           "name": "checking_in", "language": "ms", "body_has_variables": False,
           "requires_component_parameters": False}
    filters = {}
    query = Mock()
    query.select.return_value = query.limit.return_value = query
    query.eq.side_effect = lambda k, v: filters.update({k: v}) or query
    query.execute.side_effect = lambda: SimpleNamespace(data=[row] if all(row[k] == v for k, v in filters.items()) else [])
    monkeypatch.setattr(db.supabase, "table", lambda table: query if table == "whatsapp_templates" else None)
    if status is None:
        s.bot["followup_template_id"] = None
    follow.run_due_follow_ups(now=NOW)
    s.draft.assert_not_called()
    if status != "APPROVED":
        s.send.assert_not_called()
        s.save.assert_not_called()
        assert s.repo.settle.call_args.args[1]["stop_reason"] == "template_missing"
        return
    payload = s.send.call_args.args[0]
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert payload == {"messaging_product": "whatsapp", "to": "MY.wa-id", "type": "template",
                       "template": {"name": "checking_in", "language": {"code": "ms"}}}
    assert s.send.call_args.kwargs["channel"] is s.channel
    assert filters["company_id"] == 1 and filters["waba_id"] == "waba" and filters["id"] == 25
    saved = s.save.call_args.kwargs
    assert saved["message_type"] == "template" and "checking_in" in saved["message_text"]
    assert saved["ai_generated"] is False and saved["delivery_status"] == "sent"


@pytest.mark.parametrize("outcome,status,reason", [
    ("accepted", "sent", None), ("rejected", "permanent_failed", "delivery_failed"),
    ("timeout", "permanent_failed", "needs_review"),
])
def test_linked_whatsapp_follow_up_uses_original_session_after_24h(scheduled, monkeypatch, caplog,
                                                                  outcome, status, reason):
    from app.services import channel_server_service as linked

    s = scheduled
    s.chat.update(source_channel="whatsapp_link", platform_user_id="123456789@lid")
    s.channel.update(phone_number="phone-id", session_name="original-session")
    s.repo.claim_due.return_value[0]["platform"] = "whatsapp_link"
    s.repo.latest_customer.return_value["created_at"] = (NOW - timedelta(days=2)).isoformat()
    monkeypatch.setattr(delivery, "get_linked_channel", lambda channel_id: s.channel if channel_id == 10 else None)
    send = Mock(return_value=outcome == "accepted")
    if outcome == "timeout":
        send.side_effect = linked.ChannelServerError("private " + s.chat["platform_user_id"])
    monkeypatch.setattr(linked, "send_text", send)
    follow.run_due_follow_ups(now=NOW)
    send.assert_called_once_with("original-session", "123456789@lid", s.draft.return_value)
    s.send.assert_not_called()
    assert s.save.call_args.kwargs["message_type"] == "text"
    assert s.save.call_args.kwargs["delivery_status"] == status
    assert s.save.call_args.kwargs["last_error"] == reason
    assert s.repo.settle.call_args.args[1]["stop_reason"] == reason
    assert s.chat["platform_user_id"] not in caplog.text


def test_whatsapp_window_expiring_while_drafting_never_sends_the_draft(scheduled):
    s = scheduled
    before = NOW - timedelta(seconds=1)
    s.repo.latest_customer.return_value["created_at"] = (NOW - timedelta(days=1)).isoformat()
    s.bot["followup_template_id"] = None
    now = [before]

    def generate(*args, **kwargs):
        now[0] = NOW
        return "Free-form draft"

    s.draft.side_effect = generate
    follow._execute(s.repo.claim_due.return_value[0], lambda: now[0])
    s.draft.assert_called_once()
    s.send.assert_not_called()
    assert s.repo.settle.call_args.args[1]["stop_reason"] == "template_missing"


def test_whatsapp_template_unconfirmed_dispatch_records_selected_template(scheduled, monkeypatch):
    from app.database import whatsapp_template_repository

    s = scheduled
    s.repo.latest_customer.return_value["created_at"] = (NOW - timedelta(days=1)).isoformat()
    monkeypatch.setattr(whatsapp_template_repository, "get_eligible",
                        Mock(return_value={"name": "checking_in", "language": "ms"}))
    s.send.side_effect = TimeoutError()
    follow.run_due_follow_ups(now=NOW)
    assert s.send.call_count == 1 and s.repo.settle.call_args.args[1]["stop_reason"] == "needs_review"
    assert s.save.call_args.kwargs["message_type"] == "template"
    assert s.save.call_args.kwargs["message_text"] == "checking_in (ms)"
    assert s.save.call_args.kwargs["follow_up_sent_at"] is None
