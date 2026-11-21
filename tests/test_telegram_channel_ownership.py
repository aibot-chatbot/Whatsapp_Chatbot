"""Provider ownership checks use fake rows and never contact live services."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import create_app
from app.database import telegram_channel_repository as repository
from app.routes import agent_routes, telegram_routes


PROVIDER_ID = "123456789"
HEADERS = {"Authorization": "Bearer synthetic-auth-token"}


def channel(**overrides):
    return {
        "id": 8, "chatbot_id": 53, "company_id": 1,
        "telegram_bot_id": PROVIDER_ID, "bot_token": "synthetic-owner-token",
        "is_active": True, "connection_status": "connected",
        "created_at": "2026-09-01", **overrides,
    }


class FakeQuery:
    def __init__(self, rows):
        self.rows = list(rows)
        self.update_data = None

    def select(self, _columns):
        return self

    def update(self, data):
        self.update_data = data
        return self

    def eq(self, key, value):
        self.rows = [row for row in self.rows if row.get(key) == value]
        return self

    def order(self, key, desc=False):
        self.rows.sort(key=lambda row: row.get(key, ""), reverse=desc)
        return self

    def limit(self, size):
        self.rows = self.rows[:size]
        return self

    def execute(self):
        if self.update_data is not None:
            for row in self.rows:
                row.update(self.update_data)
        return SimpleNamespace(data=self.rows)


@pytest.fixture
def setup(monkeypatch):
    rows = []
    monkeypatch.setattr(repository, "supabase", SimpleNamespace(
        table=lambda name: FakeQuery(rows)
    ))
    monkeypatch.setattr("app.decorators.auth_decorator.jwt.decode", lambda *a, **k: {"user_id": 1})
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda _: {
        "id": 1, "company_id": 1, "role": "admin", "status": "active",
    })
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
    monkeypatch.setattr(telegram_routes, "publish_test_block", Mock(return_value=None))
    for module in (telegram_routes, agent_routes):
        monkeypatch.setattr(module, "verify_chatbot_access", lambda _: {"id": 53, "company_id": 1})
    monkeypatch.setattr(telegram_routes, "get_bot_by_id", lambda *a, **k: {"id": 53, "company_id": 1})
    monkeypatch.setattr(telegram_routes, "get_telegram_channel_by_id", lambda _: channel())
    monkeypatch.setattr(telegram_routes, "validate_telegram_bot_token", Mock(return_value=({"id": int(PROVIDER_ID), "username": "synthetic_bot"}, None)))
    monkeypatch.setattr(telegram_routes, "can_connect_channel", Mock())
    create = Mock(return_value=channel(connection_status="pending"))
    update = Mock(side_effect=lambda row_id, data, **kwargs: channel(id=row_id, **data))
    claim = Mock(side_effect=lambda row, data: channel(**{**data, "connection_status": "pending"}))
    set_hook = Mock(return_value=(True, None))
    delete_hook = Mock(return_value=(True, None))
    monkeypatch.setattr(telegram_routes, "create_telegram_channel", create)
    monkeypatch.setattr(telegram_routes, "update_telegram_channel", update)
    monkeypatch.setattr(telegram_routes, "activate_telegram_channel", lambda row_id, chatbot_id, company_id, **kwargs:
                        update(row_id, {"connection_status": "connected", "last_error": None, "is_active": True}))
    monkeypatch.setattr(telegram_routes, "claim_telegram_channel_operation", claim)
    monkeypatch.setattr(telegram_routes, "set_telegram_webhook", set_hook)
    monkeypatch.setattr(telegram_routes, "delete_telegram_webhook", delete_hook)
    monkeypatch.setattr(telegram_routes, "check_telegram_webhook_delivery", Mock(return_value=(telegram_routes.DELIVERY_STATUS_OK, None, {})))
    monkeypatch.setattr(telegram_routes.requests, "get", Mock(side_effect=AssertionError("Unexpected HTTP")))
    monkeypatch.setattr(telegram_routes.requests, "post", Mock(side_effect=AssertionError("Unexpected HTTP")))
    app = create_app()
    app.config["TESTING"] = True
    return SimpleNamespace(client=app.test_client(), rows=rows, create=create,
                           update=update, claim=claim, set_hook=set_hook, delete_hook=delete_hook)


def connect_or_reconnect(setup, operation):
    if operation == "connect":
        return setup.client.post("/api/telegram/connect?chatbot_id=53", headers=HEADERS,
                                 json={"bot_token": "synthetic-owner-token"})
    return setup.client.put("/api/telegram/channels/8/reconnect?chatbot_id=53", headers=HEADERS)


@pytest.mark.parametrize("operation", ["connect", "reconnect"])
@pytest.mark.parametrize("other_company", [1, 29])
def test_active_provider_conflict_never_mutates_rows_or_provider(setup, operation, other_company):
    setup.rows.extend([channel(), channel(id=7, company_id=other_company, chatbot_id=35)])
    response = connect_or_reconnect(setup, operation)
    assert response.status_code == 409
    assert response.json["code"] == "telegram_bot_already_connected"
    assert "synthetic-owner-token" not in response.get_data(as_text=True)
    setup.create.assert_not_called()
    setup.update.assert_not_called()
    setup.claim.assert_not_called()
    setup.set_hook.assert_not_called()


@pytest.mark.parametrize("operation", ["connect", "reconnect"])
def test_unique_index_race_loser_returns_safe_conflict_before_provider(setup, operation):
    violation = Exception({"code": "23505", "message": "private duplicate row details"})
    (setup.create if operation == "connect" else setup.claim).side_effect = violation
    response = connect_or_reconnect(setup, operation)
    assert response.status_code == 409
    assert response.json["code"] == "telegram_bot_already_connected"
    assert "private" not in response.get_data(as_text=True)
    setup.set_hook.assert_not_called()


@pytest.mark.parametrize("operation", ["connect", "reconnect"])
def test_inactive_history_does_not_block_claim_before_registration(setup, operation):
    setup.rows.append(channel(id=7, company_id=29, chatbot_id=35, is_active=False))
    if operation == "reconnect":
        setup.rows.append(channel())

    def check_claim(*_args, **_kwargs):
        claim = setup.create.call_args.kwargs if operation == "connect" else setup.claim.call_args.args[1]
        assert claim["telegram_bot_id"] == PROVIDER_ID
        if operation == "reconnect":
            assert claim["is_active"] is True
            assert claim["connection_status"] == "pending"
        return True, None

    setup.set_hook.side_effect = check_claim
    response = connect_or_reconnect(setup, operation)
    assert response.status_code == 200
    setup.set_hook.assert_called_once()


def test_reconnect_empty_claim_does_not_change_provider(setup):
    setup.claim.side_effect = None
    setup.claim.return_value = None
    response = connect_or_reconnect(setup, "reconnect")
    assert response.status_code == 409
    setup.set_hook.assert_not_called()


@pytest.mark.parametrize("current", [channel(is_active=False), channel(telegram_bot_id=None)])
def test_unowned_disconnect_does_not_delete_shared_webhook(setup, monkeypatch, current):
    monkeypatch.setattr(telegram_routes, "get_telegram_channel_by_id", lambda _: current)
    response = setup.client.put("/api/telegram/channels/8/disconnect?chatbot_id=53", headers=HEADERS)
    assert response.status_code == 409
    setup.delete_hook.assert_not_called()
    setup.update.assert_not_called()


def test_disconnect_detects_other_active_row_even_when_self_is_first(setup):
    setup.rows.extend([channel(), channel(id=7, company_id=29, chatbot_id=35)])
    response = setup.client.put("/api/telegram/channels/8/disconnect?chatbot_id=53", headers=HEADERS)
    assert response.status_code == 409
    setup.delete_hook.assert_not_called()


def test_sole_active_owner_can_disconnect(setup):
    setup.rows.append(channel())
    response = setup.client.put("/api/telegram/channels/8/disconnect?chatbot_id=53", headers=HEADERS)
    assert response.status_code == 200
    setup.delete_hook.assert_called_once()
    assert setup.update.call_args.args[1]["is_active"] is False


def test_failed_provider_deletion_retains_active_owner(setup):
    setup.delete_hook.return_value = (False, "Telegram is unavailable")
    response = setup.client.put("/api/telegram/channels/8/disconnect?chatbot_id=53", headers=HEADERS)
    assert response.status_code == 502
    assert setup.update.call_args.args[1] == {
        "connection_status": "failed", "last_error": "Telegram is unavailable",
    }


@pytest.mark.parametrize("operation", ["connect", "reconnect"])
def test_failed_registration_keeps_retryable_ownership_for_reconciliation(setup, operation):
    setup.set_hook.return_value = (False, "Telegram is unavailable")
    response = connect_or_reconnect(setup, operation)
    assert response.status_code == 400
    assert setup.update.call_args.args[1] == {
        "connection_status": "failed", "last_error": "Telegram is unavailable",
    }


def test_token_validation_failure_does_not_release_another_pending_claim(setup, monkeypatch):
    monkeypatch.setattr(telegram_routes, "validate_telegram_bot_token", lambda _: (None, "Unauthorized"))
    response = connect_or_reconnect(setup, "reconnect")
    assert response.status_code == 400
    setup.claim.assert_not_called()
    setup.update.assert_not_called()
    setup.set_hook.assert_not_called()


@pytest.mark.parametrize("operation", ["reconnect", "disconnect"])
def test_pending_provider_operation_cannot_be_interrupted(setup, monkeypatch, operation):
    monkeypatch.setattr(telegram_routes, "get_telegram_channel_by_id", lambda _: channel(connection_status="pending"))
    response = setup.client.put(f"/api/telegram/channels/8/{operation}?chatbot_id=53", headers=HEADERS)
    assert response.status_code == 409
    assert response.json["code"] == "telegram_channel_busy"
    setup.claim.assert_not_called()
    setup.delete_hook.assert_not_called()
    setup.set_hook.assert_not_called()


def test_stale_disconnect_cannot_release_reconnect_claim(setup):
    row = channel()
    setup.rows.append(row)
    stale_disconnect = dict(row)
    assert repository.claim_telegram_channel_operation(dict(row), {"is_active": True})
    assert repository.claim_telegram_channel_operation(stale_disconnect, {}) is None
    assert row["is_active"] is True
    assert row["connection_status"] == "pending"


def test_disconnect_losing_conditional_claim_never_deletes_provider(setup):
    setup.claim.side_effect = None
    setup.claim.return_value = None
    response = setup.client.put("/api/telegram/channels/8/disconnect?chatbot_id=53", headers=HEADERS)
    assert response.status_code == 409
    setup.delete_hook.assert_not_called()
    setup.update.assert_not_called()


def test_reconnect_blocks_disconnect_and_other_claim_while_provider_call_runs(setup, monkeypatch):
    row = channel(webhook_secret="synthetic_existing_secret")
    setup.rows.append(row)
    monkeypatch.setattr(telegram_routes, "get_telegram_channel_by_id", lambda _: dict(row))
    monkeypatch.setattr(telegram_routes, "claim_telegram_channel_operation", repository.claim_telegram_channel_operation)

    def update(_row_id, data, **kwargs):
        row.update(data)
        return dict(row)

    setup.update.side_effect = update

    def overlapping_operations(*_args, **_kwargs):
        assert row["is_active"] is True
        assert row["connection_status"] == "pending"
        assert row["connection_slot_reserved"] is True
        disconnect = setup.client.put("/api/telegram/channels/8/disconnect?chatbot_id=53", headers=HEADERS)
        assert disconnect.status_code == 409
        assert disconnect.json["code"] == "telegram_channel_busy"
        another_connect = connect_or_reconnect(setup, "connect")
        assert another_connect.status_code == 409
        assert another_connect.json["code"] == "telegram_bot_already_connected"
        return True, None

    setup.set_hook.side_effect = overlapping_operations
    response = connect_or_reconnect(setup, "reconnect")
    assert response.status_code == 200
    assert row["is_active"] is True
    assert row["connection_status"] == "connected"
    setup.set_hook.assert_called_once()
    setup.delete_hook.assert_not_called()
    setup.create.assert_not_called()


def test_disconnect_claim_error_never_logs_private_exception_text(setup, caplog):
    setup.claim.side_effect = Exception("synthetic-private-note")
    response = setup.client.put("/api/telegram/channels/8/disconnect?chatbot_id=53", headers=HEADERS)
    assert response.status_code == 500
    assert "synthetic-private-note" not in caplog.text
    assert "synthetic-private-note" not in response.get_data(as_text=True)
    setup.delete_hook.assert_not_called()


def test_reconnect_rotates_the_existing_secret(setup, monkeypatch):
    # The webhook secret is both the URL path segment and Telegram's
    # secret_token, and anyone who has held the bot token can read it back from
    # getWebhookInfo. Reusing it on reconnect would leave a tenant with no way
    # to rotate a leaked channel secret, so reconnect must mint a new one and
    # persist it before setWebhook is called.
    stored = channel(webhook_secret="synthetic_existing_secret")
    monkeypatch.setattr(telegram_routes, "get_telegram_channel_by_id", lambda _: stored)
    response = connect_or_reconnect(setup, "reconnect")
    assert response.status_code == 200
    rotated = setup.claim.call_args.args[1]["webhook_secret"]
    assert rotated != stored["webhook_secret"]
    assert setup.set_hook.call_args.kwargs["secret_token"] == rotated
    assert rotated in setup.claim.call_args.args[1]["webhook_url"]


@pytest.mark.parametrize("operation", ["set", "delete"])
def test_provider_webhook_changes_preserve_pending_updates(monkeypatch, operation):
    post = Mock(return_value=SimpleNamespace(status_code=200, json=lambda: {"ok": True}))
    monkeypatch.setattr(telegram_routes.requests, "post", post)
    if operation == "set":
        assert telegram_routes.set_telegram_webhook("synthetic-token", "https://example.test/hook")[0]
    else:
        assert telegram_routes.delete_telegram_webhook("synthetic-token")[0]
    assert post.call_args.kwargs["json"]["drop_pending_updates"] is False


def test_history_listing_retains_inactive_rows_but_outbound_query_excludes_them(setup):
    setup.rows.extend([channel(), channel(id=9, is_active=False, created_at="2026-09-02")])
    assert [row["id"] for row in repository.get_telegram_channels_by_chatbot(53)] == [9, 8]
    assert [row["id"] for row in repository.get_telegram_channels_by_chatbot(53, active_only=True)] == [8]


@pytest.mark.parametrize("operation", ["reply", "resolve"])
@pytest.mark.parametrize("active_owner", [True, False])
def test_staff_outbound_never_uses_inactive_token(setup, monkeypatch, operation, active_owner):
    setup.rows.append(channel(id=9, is_active=False, bot_token="synthetic-inactive-token", created_at="2026-09-02"))
    if active_owner:
        setup.rows.append(channel())
    conversation = {"id": 100, "chatbot_id": 53, "source_channel": "telegram", "platform_user_id": "1234",
                    "source_channel_id": 8, "source_provider_id": PROVIDER_ID}
    monkeypatch.setattr("app.services.channel_delivery_service.get_telegram_channel_by_id",
                        lambda _: channel(verified_at="2026-09-14", is_active=active_owner))
    monkeypatch.setattr(agent_routes, "get_conversation_by_id_and_chatbot", lambda *a: conversation)
    monkeypatch.setattr(agent_routes, "resolve_escalation", lambda *a: ({"conversation_id": 100}, True))
    monkeypatch.setattr(agent_routes, "is_conversation_escalated", lambda *a, **kw: False)
    monkeypatch.setattr(agent_routes, "save_message", Mock())
    send = Mock(return_value={"ok": True})
    monkeypatch.setattr(agent_routes, "send_telegram_message", send)
    path = "/api/conversations/100/agent-reply" if operation == "reply" else "/api/agent/escalations/10/resolve"
    response = setup.client.post(path, headers=HEADERS, json={"chatbot_id": 53, "text": "Synthetic reply"})
    assert response.status_code == (409 if operation == "reply" and not active_owner else 200)
    if active_owner:
        send.assert_called_once()
        assert send.call_args.args[0] == "synthetic-owner-token"
    else:
        send.assert_not_called()
