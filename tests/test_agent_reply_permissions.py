from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import create_app
from app.routes import agent_routes


@pytest.fixture
def staff(monkeypatch):
    user = {"role": "member", "company_id": 42, "status": "active"}
    monkeypatch.setattr("app.decorators.auth_decorator.jwt.decode",
                        lambda token, *a, **kw: {"user_id": int(token), "role": "owner"})
    monkeypatch.setattr("app.database.user_repository.get_user_by_id",
                        lambda user_id: {**user, "id": user_id})
    conversation = {"id": 101, "chatbot_id": 7, "source_channel": "telegram"}
    monkeypatch.setattr(agent_routes, "verify_chatbot_access", Mock(return_value={"id": 7, "company_id": 42}))
    monkeypatch.setattr(agent_routes, "get_conversation_by_id_and_chatbot", Mock(return_value=conversation))
    escalated = Mock(return_value=False)
    check_text = Mock(return_value=None)
    dispatch, save, record, web = Mock(), Mock(), Mock(), Mock(return_value={"delivery_status": "accepted"})
    monkeypatch.setattr(agent_routes, "is_conversation_escalated", escalated)
    monkeypatch.setattr(agent_routes.content_filter, "check_bot_text", check_text)
    monkeypatch.setattr(agent_routes, "_dispatch_conversation_reply", dispatch)
    monkeypatch.setattr(agent_routes, "save_message", save)
    monkeypatch.setattr(agent_routes, "record_content_flag", record)
    monkeypatch.setattr(agent_routes, "send_web_staff_reply", web)
    monkeypatch.setenv("RATELIMIT_ENABLED", "true")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "memory://")
    app = create_app()
    client = app.test_client()

    def reply(user_id=1):
        return client.post("/api/conversations/101/agent-reply",
                           headers={"Authorization": f"Bearer {user_id}"} if user_id else {},
                           json={"chatbot_id": 7, "text": "Hello"})

    return SimpleNamespace(user=user, conversation=conversation, escalated=escalated,
                           check_text=check_text, dispatch=dispatch, save=save, record=record,
                           web=web, app=app, reply=reply)


@pytest.mark.parametrize("channel", ["telegram", "web"])
@pytest.mark.parametrize("allowed_role,handed_over", [("owner", False), ("admin", False), ("member", True)])
def test_agent_reply_requires_current_role_or_handoff(staff, channel, allowed_role, handed_over):
    staff.conversation["source_channel"] = channel
    response = staff.reply()

    assert response.status_code == 403
    assert response.json == {
        "status": "error", "code": "STAFF_REPLY_NOT_ALLOWED",
        "message": "Only owners and admins can reply here. Members can reply to chats handed over to staff.",
    }
    staff.escalated.assert_called_once_with(101, 7, conversation=staff.conversation)
    for effect in (staff.check_text, staff.record, staff.dispatch, staff.save, staff.web):
        effect.assert_not_called()

    staff.user["role"] = allowed_role
    staff.escalated.reset_mock()
    staff.escalated.return_value = handed_over
    assert staff.reply().status_code == 200
    if handed_over:
        staff.escalated.assert_called_once_with(101, 7, conversation=staff.conversation)
    else:
        staff.escalated.assert_not_called()
    if channel == "web":
        staff.web.assert_called_once()
    else:
        staff.dispatch.assert_called_once_with(staff.conversation, "Hello")
        staff.save.assert_called_once()


@pytest.mark.parametrize("limit,budget", [(None, 20), ("1/minute;3/hour", 1), ("3/minute;1/hour", 1)])
def test_agent_reply_rate_limit_uses_each_authenticated_users_budget(staff, limit, budget):
    if limit:
        staff.app.config["RATELIMIT_AGENT_REPLY"] = limit
    staff.user["role"] = "admin"
    assert staff.reply(user_id=None).status_code == 401

    # Both users share the company, client and IP. Only the authenticated ID changes.
    for user_id in (1, 2):
        for _ in range(budget):
            assert staff.reply(user_id).status_code == 200
        limited = staff.reply(user_id)
        assert limited.status_code == 429
        assert limited.json["message"] == "Too many staff replies. Please try again later."
    assert staff.dispatch.call_count == staff.save.call_count == 2 * budget
