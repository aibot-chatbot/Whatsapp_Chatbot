"""Connection lifecycle regressions use synthetic providers and scoped fake storage."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.routes import telegram_routes as tr
from app.database import telegram_channel_repository as repository
from app.utils import telegram_utils
from tests.test_telegram_channel_ownership import setup, channel, HEADERS, connect_or_reconnect


def test_successful_replacement_uses_atomic_activation(setup, monkeypatch):
    setup.rows.append(channel(id=7, telegram_bot_id="older-provider"))
    activate = Mock(return_value=channel())
    monkeypatch.setattr(tr, "activate_telegram_channel", activate, raising=False)
    response = connect_or_reconnect(setup, "connect")
    assert response.status_code == 200
    activate.assert_called_once_with(8, 53, 1, expected_attempt_at=None)


@pytest.mark.parametrize("operation", ["connect", "reconnect"])
def test_activation_failure_never_reports_connected(setup, monkeypatch, operation):
    activate = Mock(side_effect=RuntimeError("private database error"))
    monkeypatch.setattr(tr, "activate_telegram_channel", activate, raising=False)
    response = connect_or_reconnect(setup, operation)
    assert response.status_code == 503
    assert response.json["code"] == "telegram_activation_unavailable"
    assert "private" not in response.get_data(as_text=True)
    assert setup.update.call_args.args[1]["connection_status"] == "failed"
    setup.delete_hook.assert_not_called()


def test_lost_activation_response_cannot_disable_committed_connection(setup, monkeypatch):
    stored = channel(connection_status="pending")
    def update(channel_id, changes, *, expected_status=None, expected_attempt_at=None):
        if expected_status and stored["connection_status"] != expected_status:
            return None
        stored.update(changes)
        return stored
    def activate(*args, **kwargs):
        stored["connection_status"] = "connected"
        raise TimeoutError("response lost after commit")
    monkeypatch.setattr(tr, "update_telegram_channel", update)
    monkeypatch.setattr(tr, "activate_telegram_channel", activate)
    response = connect_or_reconnect(setup, "connect")
    assert response.status_code == 503
    assert stored["connection_status"] == "connected"
    assert stored["is_active"] is True


@pytest.mark.parametrize("operation", ["connect", "reconnect"])
def test_failed_registration_is_visible_and_retryable(setup, operation):
    setup.set_hook.return_value = False, "Failed to set Telegram webhook"
    response = connect_or_reconnect(setup, operation)
    assert response.status_code == 400
    assert setup.update.call_args.args[1]["connection_status"] == "failed"


def test_historical_delivery_error_with_empty_queue_is_not_current_outage(monkeypatch):
    monkeypatch.setattr(tr, "get_telegram_webhook_info", lambda _: ({
        "url": "https://example.test/hook", "pending_update_count": 0,
        "last_error_date": 100, "last_error_message": "Connection refused",
    }, None))
    status, _, _ = tr.check_telegram_webhook_delivery("synthetic", "https://example.test/hook")
    assert status == tr.DELIVERY_STATUS_OK


def test_missing_expected_webhook_never_reports_healthy(monkeypatch):
    monkeypatch.setattr(tr, "get_telegram_webhook_info", lambda _: ({"url": ""}, None))
    status, _, _ = tr.check_telegram_webhook_delivery("synthetic", None)
    assert status == tr.DELIVERY_STATUS_FAILED


def test_unknown_verification_preserves_previous_connection(setup, monkeypatch):
    activate = Mock()
    monkeypatch.setattr(tr, "activate_telegram_channel", activate, raising=False)
    monkeypatch.setattr(tr, "check_telegram_webhook_delivery", lambda *a, **k: ("unknown", None, {}))
    response = connect_or_reconnect(setup, "connect")
    assert response.status_code == 503
    assert response.json["code"] == "telegram_verification_unavailable"
    activate.assert_not_called()


def test_new_token_is_the_only_token_used_on_new_setup(setup):
    response = setup.client.post("/api/telegram/connect?chatbot_id=53", headers=HEADERS,
                                 json={"bot_token": "synthetic-new-token"})
    assert response.status_code == 200
    assert setup.create.call_args.kwargs["bot_token"] == "synthetic-new-token"
    assert setup.set_hook.call_args.args[0] == "synthetic-new-token"


def test_pending_and_failed_reservations_cannot_supply_outbound_token(setup):
    setup.rows.extend([channel(id=7, connection_status="failed"),
                       channel(id=6, connection_status="pending"), channel()])
    assert [row["id"] for row in repository.get_telegram_channels_by_chatbot(53, active_only=True)] == [8]


@pytest.mark.parametrize("state", ["pending", "failed"])
def test_unactivated_channel_preserves_incoming_update_for_retry(setup, monkeypatch, state):
    monkeypatch.setattr(telegram_utils, "get_telegram_channel_by_secret", lambda _: channel(connection_status=state))
    generate = Mock()
    monkeypatch.setattr(telegram_utils, "generate_response", generate)
    response = setup.client.post("/telegram/webhook/synthetic_secret", json={"update_id": 1},
                                 headers={"X-Telegram-Bot-Api-Secret-Token": "synthetic_secret"})
    assert response.status_code == 409
    generate.assert_not_called()


def test_temporary_activation_retry_does_not_fail_registration(monkeypatch):
    monkeypatch.setattr(tr, "get_telegram_webhook_info", lambda _: ({
        "url": "https://example.test/hook", "pending_update_count": 1,
        "last_error_date": 4102444800,
        "last_error_message": "Wrong response from the webhook: 409 Conflict",
    }, None))
    status, _, _ = tr.check_telegram_webhook_delivery("synthetic", "https://example.test/hook", registered_since=1)
    assert status == tr.DELIVERY_STATUS_OK


def test_latest_attempt_order_is_independent_of_creation_order(setup):
    setup.rows.extend([channel(id=8, created_at="2026-09-01", connection_attempted_at="2026-09-14", connection_status="failed"),
                       channel(id=9, created_at="2026-09-12", connection_attempted_at="2026-09-12")])
    assert [row["id"] for row in repository.get_telegram_channels_by_chatbot(53)] == [8, 9]


def test_failed_disconnect_can_be_retried(setup):
    setup.delete_hook.return_value = False, "Failed to delete Telegram webhook"
    response = setup.client.put("/api/telegram/channels/8/disconnect?chatbot_id=53", headers=HEADERS)
    assert response.status_code == 502
    assert setup.update.call_args.args[1]["connection_status"] == "failed"


def test_delivery_read_for_inactive_row_does_not_claim_connected(setup, monkeypatch):
    monkeypatch.setattr(tr, "get_telegram_channel_by_id", lambda _: channel(is_active=False))
    check = Mock()
    monkeypatch.setattr(tr, "check_telegram_webhook_delivery", check)
    response = setup.client.get("/api/telegram/channels/8/delivery?chatbot_id=53", headers=HEADERS)
    assert response.status_code == 200
    assert response.json["data"]["delivery_status"] == "unknown"
    assert response.json["data"]["checked_at"]
    check.assert_not_called()


def test_stale_activation_loser_never_overwrites_winner(setup, monkeypatch):
    monkeypatch.setattr(tr, "activate_telegram_channel", lambda *a, **k: None)
    response = connect_or_reconnect(setup, "connect")
    assert response.status_code == 409
    assert response.json["code"] == "telegram_connection_superseded"
    assert all("connection_status" not in call.args[1] for call in setup.update.call_args_list)
    setup.delete_hook.assert_not_called()


def test_replacement_at_channel_limit_reuses_existing_slot(setup, monkeypatch):
    setup.rows.append(channel(id=7, telegram_bot_id="old-provider"))
    billing = Mock(side_effect=AssertionError("Replacement must reuse its existing slot"))
    monkeypatch.setattr(tr, "can_connect_channel", billing)
    response = connect_or_reconnect(setup, "connect")
    assert response.status_code == 200
    billing.assert_not_called()


def test_rpc_is_scoped_to_the_authenticated_chatbot_and_company(monkeypatch):
    from app.database import channel_lifecycle_repository as lifecycle
    activate = Mock(return_value=channel())
    monkeypatch.setattr(lifecycle, "activate_channel", activate)
    assert repository.activate_telegram_channel(8, 53, 1)["id"] == 8
    activate.assert_called_once_with("telegram", 8, 53, 1, expected_attempt_at=None)


@pytest.mark.parametrize("data", [[], {}, "secret-response"])
def test_malformed_rpc_response_cannot_report_activation(monkeypatch, data):
    from app.database import channel_lifecycle_repository as lifecycle
    monkeypatch.setattr("app.services.billing_guard._resolve_company_subscription", lambda _: {"plan": {"channel_limit": 5}})
    monkeypatch.setattr(lifecycle, "supabase", SimpleNamespace(
        rpc=lambda *a: SimpleNamespace(execute=lambda: SimpleNamespace(data=data))))
    with pytest.raises(lifecycle.ChannelActivationError, match="Could not finish"):
        repository.activate_telegram_channel(8, 53, 1)


@pytest.mark.parametrize("response", [[], {"ok": True, "result": "secret-response"}])
def test_unreadable_webhook_info_is_unknown_without_exposing_response(monkeypatch, response):
    monkeypatch.setattr(tr.requests, "get", lambda *a, **k: SimpleNamespace(
        status_code=200, json=lambda: response))
    status, _, info = tr.check_telegram_webhook_delivery("synthetic", "https://example.test/hook")
    assert status == "unknown"
    assert info == {}
