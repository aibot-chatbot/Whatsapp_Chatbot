"""Every channel's AI reply reads the chatbot row once per turn, not once per lookup.

Telegram and WaSender opened a turn around the whole update; the widget, Meta
WhatsApp, Test Lab and /chat paths did not, so each paid ~57 PostgREST round
trips (~124 ms each to the database) instead of ~32.
"""

from types import SimpleNamespace
from unittest.mock import Mock

from app.database import bot_repository
from app.services import ai_router

BOT = {"id": 3, "company_id": 1, "ai_provider": "openrouter", "model_name": "m", "temperature": 0.2}


def _stub_reply_path(monkeypatch, provider):
    monkeypatch.setattr(ai_router, "_try_process_flow_message", Mock(
        return_value=SimpleNamespace(handled=False, should_handoff_to_ai=True, reply=None)))
    monkeypatch.setattr(ai_router, "_route_for_enforcement", lambda provider_name, model, company_id: (provider_name, model))
    monkeypatch.setattr(ai_router, "call_provider", provider)
    monkeypatch.setattr(ai_router, "_should_log_provider_usage", lambda result: False)
    monkeypatch.setattr(ai_router, "process_needs_reply", lambda text, **kwargs: text)
    monkeypatch.setattr(ai_router, "process_booking_reply", lambda text, tidy, **kwargs: tidy(text))


def _rereading_provider(*args, **kwargs):
    # Stands in for the prompt pipeline, which re-reads the bot row several times.
    bot_repository.get_bot_by_id(3)
    bot_repository.get_bot_by_id(3)
    return ai_router._make_result_from_text("Hello", "openrouter", "m")


def test_one_reply_reads_the_bot_row_once(monkeypatch):
    select = Mock(return_value=dict(BOT))
    monkeypatch.setattr(bot_repository, "_select_bot", select)
    _stub_reply_path(monkeypatch, _rereading_provider)

    assert ai_router.generate_response("Hi", "501", 3, source_channel="widget") == "Hello"
    assert select.call_count == 1


def test_each_reply_and_each_later_read_is_fresh(monkeypatch):
    select = Mock(return_value=dict(BOT))
    monkeypatch.setattr(bot_repository, "_select_bot", select)
    _stub_reply_path(monkeypatch, _rereading_provider)

    ai_router.generate_response("Hi", "501", 3, source_channel="widget")
    ai_router.generate_response("Again", "501", 3, source_channel="widget")
    bot_repository.get_bot_by_id(3)

    assert select.call_count == 3
