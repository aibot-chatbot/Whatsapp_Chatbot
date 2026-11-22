from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from app.database import agent_action_repository as actions, message_repository as messages

from app.services import channel_delivery_service as delivery
from app.services import channel_server_service


CHAT = {"id": 91, "chatbot_id": 7, "source_channel": "whatsapp_link",
        "platform_user_id": "visitor@lid"}
NOTICE = "The customer service session has ended. You are now chatting with the AI assistant again."
NOW = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)


def ago(minutes):
    return (NOW - timedelta(minutes=minutes)).isoformat()


@pytest.fixture
def handoff(monkeypatch):
    monkeypatch.delenv("HANDOFF_CONTROL_ENABLED", raising=False)
    rows = [{"id": 51, "company_id": 11, "created_at": ago(120)},
            {"id": 52, "company_id": 11, "created_at": ago(31)}]
    open_rows, latest = Mock(return_value=rows), Mock(return_value=None)
    resolve = Mock(side_effect=[({"_ai_resumed": False}, True), ({"_ai_resumed": True}, True)])
    send, save = Mock(return_value=True), Mock()
    monkeypatch.setattr(actions, "get_open_conversation_escalations", open_rows)
    monkeypatch.setattr(messages, "latest_staff_reply_at", latest)
    monkeypatch.setattr(actions, "resolve_escalation", resolve)
    monkeypatch.setattr(actions, "is_conversation_escalated", Mock(return_value=False))
    monkeypatch.setattr(delivery, "get_bound_channel", lambda chat: {"session_name": "original"})
    monkeypatch.setattr(channel_server_service, "send_text", send)
    monkeypatch.setattr(messages, "save_message", save)
    return SimpleNamespace(rows=rows, open=open_rows, latest=latest, resolve=resolve, send=send, save=save)


def test_dispatch_reply_uses_original_linked_session(monkeypatch):
    monkeypatch.setattr(delivery, "get_bound_channel", lambda chat: {"session_name": "original"})
    send = Mock(return_value=True)
    monkeypatch.setattr(channel_server_service, "send_text", send)
    assert delivery.dispatch_conversation_reply(CHAT, NOTICE)
    send.assert_called_once_with("original", "visitor@lid", NOTICE)


def test_notice_reports_new_handoff_without_sending_or_saving():
    dispatch, save = Mock(), Mock()
    assert delivery.send_ai_resumed_notice(
        CHAT, 7, is_paused=lambda *a, **kw: True, dispatch=dispatch, save=save,
    ) == (False, "not_sent", None)
    dispatch.assert_not_called()
    save.assert_not_called()


def test_idle_handoff_resolves_all_rows_and_delivers_notice_before_saving(handoff):
    handoff.send.side_effect = lambda *args: handoff.save.call_count == 0
    assert delivery.resume_ai_after_staff_idle(CHAT, 7, now=NOW) is True
    assert handoff.resolve.call_args_list == [call(51, 7, 11), call(52, 7, 11)]
    handoff.send.assert_called_once_with("original", "visitor@lid", NOTICE)
    handoff.save.assert_called_once_with(conversation_id=91, sender_type="bot", ai_generated=False,
                                         message_text=NOTICE, message_type="text", delivery_status="sent")


@pytest.mark.parametrize("opened,staff,expected", [
    (29, None, False), (120, 10, False), (120, 31, True), (30, 30, True),
])
def test_later_of_last_escalation_and_staff_reply_sets_idle_clock(handoff, opened, staff, expected):
    handoff.rows[-1]["created_at"] = ago(opened)
    handoff.latest.return_value = ago(staff) if staff is not None else None
    assert delivery.resume_ai_after_staff_idle(CHAT, 7, now=NOW) is expected
    assert handoff.resolve.call_count == (2 if expected else 0)
    assert handoff.send.call_count == handoff.save.call_count == int(expected)


def test_no_open_row_skips_staff_lookup_and_resolution(handoff):
    handoff.open.return_value = []
    assert delivery.resume_ai_after_staff_idle(CHAT, 7, now=NOW) is False
    handoff.latest.assert_not_called()
    handoff.resolve.assert_not_called()


def test_different_chatbot_cannot_resume_handoff(handoff):
    assert delivery.resume_ai_after_staff_idle(CHAT, 8, now=NOW) is False
    handoff.open.assert_not_called()
    handoff.resolve.assert_not_called()


def test_unreadable_staff_clock_defers_to_existing_pause_check(handoff):
    handoff.latest.side_effect = RuntimeError("staff clock unavailable")
    assert delivery.resume_ai_after_staff_idle(CHAT, 7, now=NOW) is False
    handoff.resolve.assert_not_called()
    handoff.send.assert_not_called()


def test_control_plane_owns_handoff_when_enabled(handoff, monkeypatch):
    monkeypatch.setenv("HANDOFF_CONTROL_ENABLED", "true")
    assert delivery.resume_ai_after_staff_idle(CHAT, 7, now=NOW) is False
    handoff.open.assert_not_called()
    handoff.resolve.assert_not_called()
    handoff.send.assert_not_called()


def test_unbound_legacy_handoff_suppresses_notice(handoff):
    handoff.resolve.side_effect = [({"_ai_resumed": False}, True)] * 2
    assert delivery.resume_ai_after_staff_idle(CHAT, 7, now=NOW) is False
    assert handoff.resolve.call_count == 2
    handoff.send.assert_not_called()
    handoff.save.assert_not_called()


def test_notice_send_failure_keeps_ai_resumed(handoff, caplog):
    handoff.send.side_effect = RuntimeError("private provider details")
    assert delivery.resume_ai_after_staff_idle(CHAT, 7, now=NOW) is True
    assert handoff.resolve.call_count == 2
    handoff.save.assert_not_called()
    assert "AI resume notice failed conversation_id=91 chatbot_id=7" in caplog.text
    assert "private provider details" not in caplog.text


def test_web_handoff_resumes_without_external_notice(handoff):
    assert delivery.resume_ai_after_staff_idle({**CHAT, "source_channel": "web"}, 7, now=NOW)
    handoff.latest.assert_called_once_with(91, 7, web=True)
    assert handoff.resolve.call_count == 2
    handoff.send.assert_not_called()
    handoff.save.assert_not_called()
