"""Filter 1 on staff replies (plan A3): a reply with banned words is refused before any channel sends it.

Staff replies go back to the AI as chat history and out over WhatsApp, whose rules ban the same content.
"""
import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from unittest.mock import MagicMock, Mock, patch

import pytest

with patch("app.database.db.supabase", MagicMock()):
    from app import create_app

from app.routes import agent_routes
from app.services import content_filter

TELEGRAM_CONVERSATION = {"id": 101, "chatbot_id": 1, "source_channel": "telegram", "source_channel_id": 1,
                         "source_provider_id": "123", "customer_phone": None, "platform_user_id": "123456789"}
WEB_CONVERSATION = {**TELEGRAM_CONVERSATION, "source_channel": "web"}


@pytest.fixture
def staff(monkeypatch):
    client = create_app().test_client()
    world = MagicMock()
    monkeypatch.setattr("app.decorators.auth_decorator.jwt.decode",
                        lambda *_, **__: {"company_id": 42, "user_id": 1, "role": "admin"})
    monkeypatch.setattr("app.database.user_repository.get_user_by_id",
                        lambda *_: {"id": 1, "company_id": 42, "role": "admin", "status": "active"})
    monkeypatch.setattr(agent_routes, "verify_chatbot_access", lambda chatbot_id: {"id": 1, "company_id": 42})
    monkeypatch.setattr(agent_routes, "get_conversation_by_id_and_chatbot", lambda *_: world.conversation)
    monkeypatch.setattr(agent_routes, "_dispatch_conversation_reply", world.dispatch)
    monkeypatch.setattr(agent_routes, "send_web_staff_reply", world.web_reply)
    monkeypatch.setattr(agent_routes, "save_message", world.save_message)
    monkeypatch.setattr(agent_routes, "record_content_flag", world.record_flag, raising=False)
    monkeypatch.setattr(content_filter, "industry_for_bot", Mock(return_value="general"))
    world.conversation = TELEGRAM_CONVERSATION
    world.web_reply.return_value = {"delivery_status": "pending"}

    def reply(text):
        return client.post("/api/conversations/101/agent-reply", json={"chatbot_id": 1, "text": text},
                           headers={"Authorization": "Bearer test-token"})

    world.reply = reply
    return world


def test_a_staff_reply_with_banned_words_is_never_sent_or_saved(staff):
    response = staff.reply("we can sell you syabu")

    assert response.status_code == 422
    assert response.get_json()["code"] == "CONTENT_BLOCKED"
    assert "syabu" not in response.get_data(as_text=True)
    staff.dispatch.assert_not_called()
    staff.save_message.assert_not_called()


def test_a_refused_staff_reply_is_flagged_for_the_clients_company(staff):
    staff.reply("we can sell you syabu")

    kwargs = staff.record_flag.call_args.kwargs
    assert (kwargs["company_id"], kwargs["chatbot_id"], kwargs["conversation_id"], kwargs["source"]) == (42, 1, 101, "staff")
    assert kwargs["flag"].category == content_filter.DRUGS


def test_a_web_chat_staff_reply_is_refused_too(staff):
    staff.conversation = WEB_CONVERSATION

    response = staff.reply("i will kill you")

    assert response.status_code == 422
    staff.web_reply.assert_not_called()


def test_staff_may_point_a_customer_to_self_harm_support(staff):
    response = staff.reply("If thoughts of wanting to kill myself come back, please call 999.")

    assert response.status_code == 200
    staff.dispatch.assert_called_once()
    staff.record_flag.assert_not_called()


def test_an_ordinary_staff_reply_is_sent(staff):
    response = staff.reply("We open at 9am tomorrow.")

    assert response.status_code == 200
    staff.dispatch.assert_called_once()
    staff.save_message.assert_called_once()
