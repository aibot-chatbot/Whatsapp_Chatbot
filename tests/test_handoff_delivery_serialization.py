"""Same-process handoff persistence and automatic delivery must be serialized."""

from contextlib import contextmanager
import inspect
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

from app.database import agent_action_repository as actions
from app.routes import agent_routes
from app.services import channel_delivery_service as delivery
from app.utils import telegram_utils, whatsapp_utils


WAIT_SECONDS = 3


def _start(target):
    errors = []
    finished = Event()

    def run():
        try:
            target()
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    thread = Thread(target=run, daemon=True)
    thread.start()
    return SimpleNamespace(thread=thread, errors=errors, finished=finished)


def _join(worker):
    worker.thread.join(WAIT_SECONDS)
    assert not worker.thread.is_alive(), "The conversation lock did not release"
    if worker.errors:
        raise worker.errors[0]


def _observe_lock(monkeypatch, module, attempted, entered=None):
    from app.services.conversation_delivery_lock import conversation_delivery_lock

    @contextmanager
    def observed(conversation_id):
        attempted.set()
        with conversation_delivery_lock(conversation_id):
            if entered is not None:
                entered.set()
            try:
                yield
            finally:
                if entered is not None:
                    entered.clear()

    monkeypatch.setattr(module, "conversation_delivery_lock", observed)


def _fake_action_insert(monkeypatch, persist):
    client = Mock()
    client.table.return_value.insert.return_value.execute.side_effect = persist
    monkeypatch.setattr(actions, "supabase", client)


def _save_handoff(conversation_id=800):
    return actions.save_agent_action(
        chatbot_id=3, company_id=1, conversation_id=conversation_id,
        intent="handoff_request", action_type="request_handoff",
    )


def _sender_path(monkeypatch, source, paused, provider):
    module = {"telegram": telegram_utils, "whatsapp": whatsapp_utils}[source]
    channel = {
        "id": 4, "chatbot_id": 3, "company_id": 1, "is_active": True,
        "connection_status": "connected", "verified_at": "2026-09-14T00:00:00Z",
        "telegram_bot_id": "55", "phone_number_id": "55", "provider_user_id": "55",
        "bot_token": "synthetic-token", "access_token": "synthetic-token", "api_key": "synthetic-key",
    }
    conversation = {
        "id": 800, "chatbot_id": 3, "source_channel": source,
        "source_channel_id": 4, "source_provider_id": "55",
        "platform_user_id": "12345", "customer_phone": "+60123456789",
    }
    monkeypatch.setattr(delivery, ("get_linked_channel" if source == "whatsapp_link" else f"get_{source}_channel_by_id"), Mock(return_value=channel))
    lookup = "get_whatsapp_channel_by_phone_number_id" if source == "whatsapp" else f"get_{source}_channel_by_secret"
    monkeypatch.setattr(module, lookup, Mock(return_value=channel))
    create = "get_or_create_platform_conversation" if source == "telegram" else "get_or_create_conversation"
    monkeypatch.setattr(module, create, Mock(return_value=conversation))
    monkeypatch.setattr(module, "is_conversation_escalated", Mock(side_effect=lambda *_, **__: paused.is_set()))
    monkeypatch.setattr(module, "dispatch_media_after_reply", Mock())
    monkeypatch.setattr(module, "get_bot_by_id", Mock(return_value={"telegram_markdown_enabled": False}))
    if source == "whatsapp":
        monkeypatch.setattr(module, "update_workflow_state", Mock())
    claim = {"telegram": "claim_telegram_update", "whatsapp": "claim_processed_message"}[source]
    release = {"telegram": "release_telegram_update_claim", "whatsapp": "release_processed_message_claim"}[source]
    monkeypatch.setattr(module, claim, Mock(return_value=True))
    monkeypatch.setattr(module, release, Mock())
    monkeypatch.setattr(module, "generate_response", Mock(return_value="A generated reply"))
    monkeypatch.setattr(module, "save_message", Mock())
    sender = {"telegram": "send_telegram_message", "whatsapp": "send_message"}[source]
    send = Mock(side_effect=provider)
    monkeypatch.setattr(module, sender, send)
    if source == "telegram":
        payload = {"update_id": 9, "message": {"message_id": 10, "chat": {"id": 12345, "type": "private"},
                   "from": {"id": 12345}, "text": "Hello"}}
        run = lambda: module.process_telegram_update(payload, "synthetic-secret")
    else:
        payload = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "55"},
            "contacts": [{"wa_id": "12345"}], "messages": [{"id": "10", "type": "text", "text": {"body": "Hello"}}]}}]}]}
        run = lambda: module.process_whatsapp_message(payload)
    return SimpleNamespace(module=module, run=run, send=send, channel=channel, conversation=conversation)


@pytest.mark.parametrize("source", ["whatsapp", "telegram"])
def test_idle_handoff_check_precedes_customer_turn_pause(monkeypatch, source):
    paused = Event()
    paused.set()
    path = _sender_path(monkeypatch, source, paused, lambda *a, **kw: _accepted(source))
    def resume(conversation, chatbot_id):
        assert conversation == path.conversation and chatbot_id == 3
        paused.clear()
        return True
    check = Mock(side_effect=resume)
    monkeypatch.setattr(path.module, "resume_ai_after_staff_idle", check, raising=False)
    path.run()
    check.assert_called_once()
    path.module.generate_response.assert_called_once()
    assert path.module.generate_response.call_args.args[0] == "Hello"
    path.send.assert_called_once()


def _delivery_path(monkeypatch, case, paused, provider):
    if case in {"telegram", "whatsapp"}:
        return _sender_path(monkeypatch, case, paused, provider)
    source = case.split("_")[0]
    base = _sender_path(monkeypatch, source, paused, provider)
    if case == "telegram_fallback":
        monkeypatch.setattr(telegram_utils, "get_bot_by_id", Mock(return_value={"telegram_markdown_enabled": True}))

        def send(*args, **kwargs):
            if kwargs.get("parse_mode"):
                return {"ok": False, "format_rejected": True}
            return provider(*args, **kwargs)

        base.send.side_effect = send
        return base
    if case == "telegram_contact":
        sender = Mock(side_effect=provider)
        monkeypatch.setattr(telegram_utils, "send_telegram_contact_request", sender)
        return SimpleNamespace(module=telegram_utils, send=sender, run=lambda: telegram_utils._send_recorded_telegram_reply(
            base.conversation, base.channel, "12345", "Share your phone", contact_request=True))
    if case.endswith("_media"):
        from app.services import media_send_service as media

        monkeypatch.setattr(media, "get_active_attachments", Mock(return_value=[{"keywords": ["catalogue"], "label": "Catalogue"}]))
        monkeypatch.setattr(media, "get_bound_channel", Mock(return_value=base.channel))
        monkeypatch.setattr(media, "is_conversation_escalated", Mock(side_effect=lambda *_, **__: paused.is_set()))
        name = {"telegram": "send_telegram_media", "whatsapp": "send_meta_media_template"}[source]
        sender = Mock(side_effect=provider)
        monkeypatch.setattr(media, name, sender)
        return SimpleNamespace(module=media, send=sender, run=lambda: media.dispatch_media_after_reply(
            "catalogue", 3, "meta" if source == "whatsapp" else source, base.channel, "12345", conversation=base.conversation))


def _accepted(source):
    if source.endswith("_media"):
        return True
    if source == "whatsapp":
        return Mock(status_code=200, json=Mock(return_value={"messages": [{"id": "11"}]}))
    return {"ok": True, "success": True}


@pytest.mark.parametrize("source", ["telegram", "whatsapp", "telegram_fallback", "telegram_contact",
                                     "telegram_media", "whatsapp_media"])
def test_send_first_holds_handoff_persistence_until_provider_finishes(monkeypatch, source):
    paused, provider_entered, release_provider, handoff_attempted, sender_locked, persisted = [Event() for _ in range(6)]
    order = []

    def provider(*_, **__):
        assert sender_locked.is_set(), "Provider was called outside the delivery lock"
        provider_entered.set()
        assert release_provider.wait(WAIT_SECONDS)
        order.append("provider_finished")
        return _accepted(source)

    def persist():
        order.append("handoff_persisted")
        paused.set()
        persisted.set()
        return SimpleNamespace(data=[{"id": 9}])

    path = _delivery_path(monkeypatch, source, paused, provider)
    _observe_lock(monkeypatch, path.module, Event(), sender_locked)
    _observe_lock(monkeypatch, actions, handoff_attempted)
    _fake_action_insert(monkeypatch, persist)
    sender = _start(path.run)
    handoff = None
    try:
        assert provider_entered.wait(WAIT_SECONDS)
        handoff = _start(_save_handoff)
        assert handoff_attempted.wait(WAIT_SECONDS)
        assert not persisted.is_set()
    finally:
        release_provider.set()
        _join(sender)
        if handoff is not None:
            _join(handoff)
    assert order == ["provider_finished", "handoff_persisted"]
    assert path.send.call_count == (2 if source == "telegram_fallback" else 1)


@pytest.mark.parametrize("source", ["telegram", "whatsapp"])
def test_handoff_first_blocks_final_send_until_pause_is_persisted(monkeypatch, source):
    paused, insert_entered, release_insert, sender_attempted, persistence_locked = [Event() for _ in range(5)]

    def persist():
        assert persistence_locked.is_set(), "Handoff was inserted outside the delivery lock"
        insert_entered.set()
        assert release_insert.wait(WAIT_SECONDS)
        paused.set()
        return SimpleNamespace(data=[{"id": 9}])

    path = _sender_path(monkeypatch, source, paused, lambda *_, **__: _accepted(source))
    # Exercise a turn already admitted before the handoff insert reaches its final send.
    monkeypatch.setattr(path.module, "resume_ai_after_staff_idle", lambda *args: False)
    _observe_lock(monkeypatch, path.module, sender_attempted)
    _observe_lock(monkeypatch, actions, Event(), persistence_locked)
    _fake_action_insert(monkeypatch, persist)
    handoff = _start(_save_handoff)
    sender = None
    try:
        assert insert_entered.wait(WAIT_SECONDS)
        sender = _start(path.run)
        assert sender_attempted.wait(WAIT_SECONDS)
        path.send.assert_not_called()
    finally:
        release_insert.set()
        _join(handoff)
        if sender is not None:
            _join(sender)
    path.module.generate_response.assert_called_once()
    path.send.assert_not_called()
    assert all(call.kwargs["sender_type"] == "customer" for call in path.module.save_message.call_args_list)


@pytest.mark.parametrize("source", ["telegram", "whatsapp"])
def test_provider_exception_releases_lock_for_subsequent_handoff(monkeypatch, source):
    def failed_provider(*_, **__):
        raise RuntimeError("Synthetic provider failure")

    path = _sender_path(monkeypatch, source, Event(), failed_provider)
    sender = _start(path.run)
    assert sender.finished.wait(WAIT_SECONDS)
    assert len(sender.errors) == 1 and isinstance(sender.errors[0], RuntimeError)
    _fake_action_insert(monkeypatch, lambda: SimpleNamespace(data=[{"id": 9}]))
    handoff = _start(_save_handoff)
    _join(handoff)
    assert actions.supabase.table.return_value.insert.return_value.execute.call_count == 1


def test_distinct_conversation_handoff_does_not_wait_for_other_delivery(monkeypatch):
    from app.services.conversation_delivery_lock import conversation_delivery_lock

    _fake_action_insert(monkeypatch, lambda: SimpleNamespace(data=[{"id": 9}]))
    with conversation_delivery_lock(801):
        handoff = _start(lambda: _save_handoff(802))
        assert handoff.finished.wait(WAIT_SECONDS), "Unrelated conversations share a blocking lock"
    _join(handoff)


def test_reentrant_lock_allows_nested_action_persistence(monkeypatch):
    from app.services.conversation_delivery_lock import conversation_delivery_lock

    _fake_action_insert(monkeypatch, lambda: SimpleNamespace(data=[{"id": 9}]))

    def nested():
        with conversation_delivery_lock(803):
            with conversation_delivery_lock(803):
                assert _save_handoff(803) == {"id": 9}

    _join(_start(nested))


def test_context_exception_releases_lock_for_another_thread():
    from app.services.conversation_delivery_lock import conversation_delivery_lock

    with pytest.raises(ValueError):
        with conversation_delivery_lock(804):
            raise ValueError("Synthetic exception")
    acquired = Event()

    def acquire():
        with conversation_delivery_lock(804):
            acquired.set()

    worker = _start(acquire)
    _join(worker)
    assert acquired.is_set()


def test_resolution_waits_for_same_conversation_delivery(monkeypatch):
    from app.services.conversation_delivery_lock import conversation_delivery_lock

    attempted, completed = Event(), Event()
    row = {"id": 9, "conversation_id": 805, "chatbot_id": 3, "company_id": 1, "intent": "handoff_request"}
    monkeypatch.setattr(actions, "_get_escalation_by_id", Mock(return_value=row))
    client = Mock()

    def resolve():
        completed.set()
        return SimpleNamespace(data={"resolved_action": {**row, "status": "resolved"}, "changed": True, "ai_resumed": True})

    client.rpc.return_value.execute.side_effect = resolve
    monkeypatch.setattr(actions, "supabase", client)
    _observe_lock(monkeypatch, actions, attempted)
    with conversation_delivery_lock(805):
        worker = _start(lambda: actions.resolve_escalation(9, 3, 1))
        assert attempted.wait(WAIT_SECONDS)
        assert not completed.is_set()
    _join(worker)
    assert completed.is_set()


def test_new_handoff_before_resolve_notice_suppresses_ai_resumed_notification(monkeypatch):
    from app.services.conversation_delivery_lock import conversation_delivery_lock

    attempted, paused = Event(), Event()
    conversation = {"id": 806, "chatbot_id": 3, "source_channel": "telegram", "platform_user_id": "12345"}
    monkeypatch.setattr(agent_routes, "verify_chatbot_access", Mock(return_value={"company_id": 1}))
    monkeypatch.setattr(agent_routes, "get_conversation_by_id_and_chatbot", Mock(return_value=conversation))
    monkeypatch.setattr(agent_routes, "resolve_escalation", Mock(return_value=({
        "id": 9, "conversation_id": 806, "_ai_resumed": True,
    }, True)))
    monkeypatch.setattr(agent_routes, "is_conversation_escalated", Mock(side_effect=lambda *_, **__: paused.is_set()))
    dispatch, save = Mock(), Mock()
    monkeypatch.setattr(agent_routes, "_dispatch_conversation_reply", dispatch)
    monkeypatch.setattr(agent_routes, "save_message", save)
    _observe_lock(monkeypatch, agent_routes, attempted)

    def persist():
        paused.set()
        return SimpleNamespace(data=[{"id": 10}])

    _fake_action_insert(monkeypatch, persist)
    result = []

    def resolve_route():
        with Flask(__name__).test_request_context(json={"chatbot_id": 3}):
            response, status = inspect.unwrap(agent_routes.resolve_esc)(9)
            result.append((response.json, status))

    with conversation_delivery_lock(806):
        worker = _start(resolve_route)
        assert attempted.wait(WAIT_SECONDS)
        assert _save_handoff(806) == {"id": 10}
    _join(worker)
    response, status = result[0]
    assert status == 200
    assert response["data"]["ai_resumed"] is False
    assert response["data"]["handoff_state"] == "human"
    assert response["data"]["notification_status"] == "not_sent"
    dispatch.assert_not_called()
    save.assert_not_called()


def test_staff_reply_remains_allowed_during_persisted_handoff(monkeypatch):
    paused = Event()
    path = _sender_path(monkeypatch, "telegram", paused, lambda *_, **__: {"ok": True})
    paused.set()
    monkeypatch.setattr(agent_routes, "verify_chatbot_access", Mock(return_value={"company_id": 1}))
    monkeypatch.setattr(agent_routes, "get_conversation_by_id_and_chatbot", Mock(return_value=path.conversation))
    monkeypatch.setattr(agent_routes, "is_conversation_escalated", Mock(return_value=True))
    send, resolve, save = Mock(return_value={"ok": True}), Mock(), Mock()
    held = Event()
    _observe_lock(monkeypatch, agent_routes, Event(), held)
    def check_save(**kwargs):
        assert held.is_set(), "Idle expiry must wait until a staff send is recorded"
    save.side_effect = check_save
    monkeypatch.setattr(agent_routes, "send_telegram_message", send)
    monkeypatch.setattr(agent_routes, "resolve_escalation", resolve)
    monkeypatch.setattr(agent_routes, "save_message", save)
    with Flask(__name__).test_request_context(json={"chatbot_id": 3, "text": "Human response"}):
        response, status = inspect.unwrap(agent_routes.agent_reply)(800)
    assert status == 200
    assert response.json["data"]["delivery_status"] == "sent"
    send.assert_called_once()
    resolve.assert_not_called()
    assert save.call_args.kwargs["ai_generated"] is False
