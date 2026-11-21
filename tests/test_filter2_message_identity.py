"""Stored customer ids reach Filter 2 without guessing the latest message."""
from unittest.mock import Mock

import pytest
from flask import Flask

from app.routes import widget_routes
from app.services import tuition_telegram_service, channel_server_service
from app.utils import telegram_utils, whatsapp_utils


@pytest.mark.parametrize("channel_name", ["telegram", "whatsapp", "whatsapp_link"])
@pytest.mark.parametrize("stored", [{"id": 731}, None])
def test_inbound_channel_passes_the_exact_saved_message_id(monkeypatch, channel_name, stored):
    modules = {"telegram": telegram_utils, "whatsapp": whatsapp_utils,
               "whatsapp_link": channel_server_service}
    module = modules[channel_name]
    conversation = {"id": 8, "chatbot_id": 3, "customer_phone": "60123456789"}
    channel = {"id": 4, "chatbot_id": 3, "company_id": 1, "bot_token": "synthetic-token"}
    events = []

    def save(**row):
        events.append(("save", row))
        return stored

    def generate(*args, **kwargs):
        events.append(("generate", kwargs))
        return "<SILENT_BOT_RESPONSE>"

    monkeypatch.setattr(module, "save_message", save)
    monkeypatch.setattr(module, "generate_response", generate)
    monkeypatch.setattr(module, "is_conversation_escalated", lambda *a, **k: False)
    monkeypatch.setattr(module, "channel_identity", lambda *a, **k: {})
    if channel_name == "telegram":
        monkeypatch.setattr(module, "get_or_create_platform_conversation", lambda **k: conversation)
        monkeypatch.setattr(module, "show_telegram_typing", Mock())
        monkeypatch.setattr(tuition_telegram_service, "is_tuition_update", lambda update: False)
        update = {"message": {"message_id": 99, "text": "Question",
                              "chat": {"id": 501, "type": "private"},
                              "from": {"id": 501, "first_name": "Customer"}}}
        module._process_claimed_telegram_update(update, channel, {})
    else:
        monkeypatch.setattr(module, "get_or_create_conversation", lambda **k: conversation)
        if channel_name == "whatsapp":
            monkeypatch.setattr(module, "update_workflow_state", Mock())
            value = {"contacts": [{"wa_id": "60123456789"}],
                     "messages": [{"id": "platform-99", "type": "text", "text": {"body": "Question"}}]}
            module._process_claimed_whatsapp_message(value, channel, {})
        else:
            module.process_message(channel, {"id": "platform-99", "fromMe": False, "from": "60123456789@c.us", "body": "Question"}, lambda _: True)

    assert [event[0] for event in events] == ["save", "generate"]
    assert events[0][1]["message_text"] == "Question"
    assert events[1][1]["conversation_id"] == 8
    if stored:
        assert events[1][1]["message_id"] == 731
    else:
        assert "message_id" not in events[1][1]


def test_widget_passes_the_saved_customer_id_before_generating(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    app.register_blueprint(widget_routes.widget_blueprint)
    conversation = {"id": 8}
    events = []
    monkeypatch.setattr(widget_routes, "_load_widget_or_error", lambda: ({"chatbot_id": 3}, {}))
    monkeypatch.setattr(widget_routes, "open_conversation", lambda *a: conversation)
    monkeypatch.setattr(widget_routes, "is_conversation_escalated", lambda *a, **k: False)
    monkeypatch.setattr(widget_routes, "assert_session_quota", lambda *a: 10)
    monkeypatch.setattr(widget_routes, "validate_session_id", lambda value: value)

    def save(conversation_id, message):
        events.append("save")
        return {"id": 731}

    def generate(*args, **kwargs):
        events.append("generate")
        assert kwargs["message_id"] == 731
        assert kwargs["conversation_id"] == 8
        return "<SILENT_BOT_RESPONSE>"

    monkeypatch.setattr(widget_routes, "record_customer_message", save)
    monkeypatch.setattr(widget_routes, "generate_response", generate)
    response = app.test_client().post("/api/widget/synthetic-key/message",
                                      json={"session_id": "synthetic-session", "message": "Question"})
    assert response.status_code == 200
    assert events == ["save", "generate"]
