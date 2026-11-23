"""The publish gate runs after tenant checks and before the first connection operation."""

import inspect
from unittest.mock import Mock

import pytest
from flask import Flask, g

from app import views
from app.routes import channel_server_routes, telegram_routes, whatsapp_routes
from app.services.billing_guard import BillingLimitError
from app.services import test_scenario_service as publish_test_service


CHANNELS = {
    "telegram": (telegram_routes, {"bot_token": "synthetic"}),
    "whatsapp": (whatsapp_routes, {"code": "synthetic", "phone_number_id": "123", "waba_id": "456"}),
}
ENDPOINTS = [
    ("telegram", "connect"), ("whatsapp", "connect"), ("whatsapp", "embedded-signup/complete"),
    ("channel-server", "connect"), ("channel-server", "channels/8/reconnect"),
    *((name, "channels/8/reconnect") for name in CHANNELS),
]


def client_for(provider, monkeypatch, channel_company=2):
    module = channel_server_routes if provider == "channel-server" else CHANNELS[provider][0]
    app = Flask(__name__)
    app.register_blueprint(getattr(module, provider.replace("-", "_") + "_blueprint"))
    # The real route table selects the handler, with identity injected at its ownership lookup.
    for endpoint, handler in app.view_functions.copy().items():
        app.view_functions[endpoint] = inspect.unwrap(handler)
    monkeypatch.setattr(module, "verify_chatbot_access", Mock(return_value={"company_id": 2}))
    if provider == "channel-server":
        @app.before_request
        def identity():
            g.company_id = 2
        monkeypatch.setattr(module.repo, "get", Mock(return_value={"company_id": channel_company, "chatbot_id": 4}))
        return app.test_client()
    monkeypatch.setattr(module, "get_bot_by_id", Mock(return_value={"company_id": 2}))
    monkeypatch.setattr(module, f"get_{provider}_channel_by_id", Mock(return_value={
        "chatbot_id": 4, "company_id": channel_company, "id": 8, "bot_token": "synthetic",
        "access_token": "synthetic", "connection_status": "disconnected", "is_active": False,
    }))
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
    return app.test_client()


@pytest.mark.parametrize("provider,path", ENDPOINTS)
def test_connect_and_reconnect_obey_latest_gate_before_channel_operations(provider, path, monkeypatch):
    client = client_for(provider, monkeypatch)
    module, body = ((channel_server_routes, {"chatbot_id": 4, "phone_number": "601112223333", "risk_consent": True})
                    if provider == "channel-server" else CHANNELS[provider])
    reconnect = path.endswith("/reconnect")
    first_operation = "ensure_channel_slot"
    if provider == "telegram":
        first_operation = "_check_channel_slot" if reconnect else "validate_telegram_bot_token"
    # This sentinel stops a permitted call before any channel mutation or network I/O.
    operation = Mock(side_effect=BillingLimitError("Reached the connection operation."))
    monkeypatch.setattr(module, first_operation, operation)
    latest = Mock(return_value=None)
    current = Mock(return_value="trained")
    monkeypatch.setattr(publish_test_service.repo, "latest_publish_test", latest)
    monkeypatch.setattr(publish_test_service, "fingerprint", current)
    monkeypatch.setenv("PUBLISH_TEST_GATE", "on")
    monkeypatch.setenv("REPLY_CHECK_MODE", "log")
    url = f"/api/{provider}/{path}?chatbot_id=4"
    method = client.put if reconnect else client.post

    run = {"run_id": "test", "scenario_keys": ["fact"], "fingerprint": "trained", "passed": True,
           "answers": [{"key": "fact", "status": "ok", "subtypes": []}]}
    saved = {"id": 1, "payload": {"publish_test": run}}
    for row, version, allowed in ((None, "trained", False), (saved, "trained", True), (saved, "changed", False)):
        latest.return_value = row
        current.return_value = version
        operation.reset_mock()
        response = method(url, json=body)
        latest.assert_called_with(4, 2)
        if allowed:
            assert response.status_code == 403
            assert response.json["message"] == "Reached the connection operation."
            operation.assert_called_once()
        else:
            assert response.status_code == 409
            assert response.json["code"] == "PUBLISH_TEST_REQUIRED"
            operation.assert_not_called()


@pytest.mark.parametrize("provider", CHANNELS)
def test_reconnect_rejects_foreign_channel_before_reading_gate(provider, monkeypatch):
    client = client_for(provider, monkeypatch, channel_company=99)
    module, _ = CHANNELS[provider]
    gate = Mock()
    monkeypatch.setattr(module, "publish_test_block", gate, raising=False)
    monkeypatch.setattr(module, "_check_channel_slot" if provider == "telegram" else "ensure_channel_slot",
                        Mock(side_effect=RuntimeError("Unexpected channel operation")))
    assert client.put(f"/api/{provider}/channels/8/reconnect?chatbot_id=4", json={}).status_code == 403
    gate.assert_not_called()


@pytest.mark.parametrize("provider", CHANNELS)
def test_existing_channels_can_list_check_delivery_and_disconnect_without_a_run(provider, monkeypatch):
    client = client_for(provider, monkeypatch)
    module, _ = CHANNELS[provider]
    gate = Mock(side_effect=AssertionError("Existing channels must not read publish tests"))
    monkeypatch.setattr(module, "publish_test_block", gate, raising=False)
    channel = {"id": 8, "chatbot_id": 4, "company_id": 2, "is_active": True,
               "connection_status": "connected", "telegram_bot_id": "123",
               "phone_number_id": "123", "access_token": "synthetic"}
    monkeypatch.setattr(module, f"get_{provider}_channel_by_id", Mock(return_value=channel))
    monkeypatch.setattr(module, f"get_{provider}_channels_by_chatbot", Mock(return_value=[channel]))
    if provider == "whatsapp":
        monkeypatch.setattr(module, "verify_meta_connection", Mock())
        monkeypatch.setattr(module, "disconnect_whatsapp_channel_record", Mock(return_value=channel))
    else:
        monkeypatch.setattr(module, "check_telegram_webhook_delivery", Mock(return_value=("ok", None, {})))
        monkeypatch.setattr(module, "get_telegram_channel_by_bot_id", Mock(return_value=None))
        monkeypatch.setattr(module, "claim_telegram_channel_operation", Mock(return_value=channel))
        monkeypatch.setattr(module, "delete_telegram_webhook", Mock(return_value=(True, None)))
        monkeypatch.setattr(module, "update_telegram_channel", Mock(return_value=channel))
    path = f"/api/{provider}/channels"
    assert client.get(path + "?chatbot_id=4").status_code == 200
    assert client.get(path + "/8/delivery?chatbot_id=4").status_code == 200
    assert client.put(path + "/8/disconnect?chatbot_id=4").status_code == 200
    gate.assert_not_called()


@pytest.mark.parametrize("provider,lookup", [("telegram", "assert_telegram_channel_ready")])
def test_active_webhook_still_queues_delivery_without_a_run(provider, lookup, monkeypatch):
    client = client_for(provider, monkeypatch)
    module, _ = CHANNELS[provider]
    gate = Mock(side_effect=AssertionError("Webhooks must not read publish tests"))
    monkeypatch.setattr(module, "publish_test_block", gate, raising=False)
    monkeypatch.setattr(module, lookup, Mock(return_value={"company_id": 2, "chatbot_id": 4}))
    submit = Mock(return_value=True)
    monkeypatch.setattr(module, "submit", submit)
    assert client.post(f"/{provider}/webhook/synthetic", json={}).status_code == 200
    submit.assert_called_once()
    gate.assert_not_called()


def test_meta_webhook_still_processes_incoming_messages_without_a_run(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(views.webhook_blueprint)
    app.view_functions["webhook.webhook_post"] = inspect.unwrap(views.webhook_post)
    gate = Mock(side_effect=AssertionError("Webhooks must not read publish tests"))
    monkeypatch.setattr(views, "publish_test_block", gate, raising=False)
    process = Mock()
    monkeypatch.setattr(views, "process_whatsapp_message", process)
    value = {"metadata": {"phone_number_id": "200"}, "contacts": [{"wa_id": "300"}],
             "messages": [{"id": "m1", "from": "300", "type": "text", "text": {"body": "hello"}}]}
    event = {"object": "whatsapp_business_account", "entry": [
        {"id": "100", "changes": [{"field": "messages", "value": value}]}]}
    assert app.test_client().post("/webhook", json=event).status_code == 200
    process.assert_called_once_with(event)
    gate.assert_not_called()
