"""The website widget gets the AI's [BUTTONS: ...] options as data, not as text.

Seam: POST /api/widget/<key>/message. The widget page turns `buttons` into
tappable chips, so the reply text must arrive without the tag.
"""

from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest
from flask import Flask

from app.routes import widget_routes as routes

SESSION = "web_" + "a" * 32


@pytest.fixture
def client(monkeypatch):
    widget = {"id": 1, "chatbot_id": 42, "company_id": 7, "public_key": "wgt_testkey",
              "is_enabled": True, "allowed_domains": [], "max_messages_per_session": 50}
    monkeypatch.setattr(routes, "resolve_public_widget", lambda *a, **k: (widget, {"company_id": 7}))
    monkeypatch.setattr(routes, "ensure_company_operational", lambda *a, **k: None)
    monkeypatch.setattr(routes, "open_conversation", lambda *a, **k: {"id": 100})
    monkeypatch.setattr(routes, "conversation_delivery_lock", lambda *a, **k: nullcontext())
    monkeypatch.setattr(routes, "is_conversation_escalated", lambda *a, **k: False)
    monkeypatch.setattr(routes, "assert_session_quota", lambda *a, **k: 10)
    monkeypatch.setattr(routes, "record_customer_message", lambda *a, **k: {"id": 1})
    monkeypatch.setattr(routes, "record_bot_message", lambda *a, **k: {"id": 2})
    monkeypatch.setattr(routes, "automatic_reply_allowed", lambda *a, **k: True)
    monkeypatch.setattr(routes, "generate_response", MagicMock(return_value=(
        "Here is our programme overview.\n\n[BUTTONS: Programme info | Competition rules | Event schedule]")))
    app = Flask(__name__)
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    app.register_blueprint(routes.widget_blueprint)
    return app.test_client()


def test_widget_page_shows_reply_buttons_as_the_tappable_suggestion_chips():
    from pathlib import Path

    page = (Path(__file__).resolve().parents[1] / "frontend" / "widget-chat.html").read_text(encoding="utf-8")
    reply_handler = page[page.index('api("/message"'):page.index(".catch(", page.index('api("/message"'))]
    assert 'addMessage(data.reply, "bot");' in reply_handler
    assert "renderSuggestions(data.buttons);" in reply_handler


def test_widget_reply_carries_buttons_as_data_and_text_without_the_tag(client):
    response = client.post("/api/widget/wgt_testkey/message",
                           json={"session_id": SESSION, "message": "Tell me about the programme"})

    data = response.get_json()["data"]
    assert data["reply"] == "Here is our programme overview."
    assert data["buttons"] == ["Programme info", "Competition rules", "Event schedule"]
