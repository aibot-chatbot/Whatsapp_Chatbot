"""Wasender logs must never copy webhook credentials or message contents."""

import logging
import inspect
from unittest.mock import Mock

import pytest
import requests
from flask import Flask

from app.services.webhook_worker import drain

from app.services import wasender_service as service
from app.services import wasender_retry_service as retry
from app.routes import wasender_routes as routes


SECRET = "synthetic-private-webhook-secret"
API_KEY = "synthetic-private-api-key"
PHONE = "+601112223333"
MESSAGE_ID = "synthetic-private-message-id"
CUSTOMER_NAME = "synthetic-private-customer-name"
MESSAGE = "synthetic-private-customer-message"
PROVIDER_BODY = "synthetic-private-provider-body"
PRIVATE_EVENT = "synthetic-private-event-value"
PRIVATE_VALUES = (
    SECRET, API_KEY, PHONE, PHONE[1:], MESSAGE_ID, CUSTOMER_NAME,
    MESSAGE, PROVIDER_BODY, PRIVATE_EVENT,
)


@pytest.mark.parametrize("scenario", ["unknown", "incoming", "ignored", "duplicate"])
def test_webhook_keeps_private_values_out_of_logs(monkeypatch, caplog, scenario):
    channel = {"id": 8, "chatbot_id": 4, "company_id": 2, "api_key": API_KEY, "provider_user_id": "123", "is_active": True, "connection_status": "connected", "verified_at": "2026-09-14"}
    monkeypatch.setattr(service, "get_wasender_channel_by_secret", Mock(
        return_value=None if scenario == "unknown" else channel,
    ))
    monkeypatch.setattr(service, "claim_wasender_message", Mock(
        return_value=scenario != "duplicate",
    ))
    monkeypatch.setattr(service, "get_or_create_conversation", Mock(return_value={"id": 9}))
    save = Mock()
    processed = Mock(return_value=scenario != "duplicate")
    send = Mock(return_value={"success": True, "data": {}, "error": None})
    monkeypatch.setattr(service, "save_message", save)
    monkeypatch.setattr(service, "claim_wasender_message", processed)
    monkeypatch.setattr(service, "generate_response", Mock(return_value="Synthetic reply"))
    monkeypatch.setattr(service, "is_conversation_escalated", Mock(return_value=False))
    monkeypatch.setattr(service, "get_bound_channel", Mock(return_value=channel))
    monkeypatch.setattr(service, "send_wasender_text_message", send)
    monkeypatch.setattr(service, "dispatch_media_after_reply", Mock())
    payload = {
        "event": PRIVATE_EVENT if scenario == "ignored" else "messages.received",
        "data": {"messages": {
            "key": {"id": MESSAGE_ID, "remoteJid": f"{PHONE[1:]}@s.whatsapp.net"},
            "messageBody": MESSAGE,
            "pushName": CUSTOMER_NAME,
        }},
    }

    with caplog.at_level(logging.INFO):
        service.process_wasender_webhook(payload, SECRET)

    if scenario == "incoming":
        send.assert_called_once_with(API_KEY, PHONE, "Synthetic reply")
        processed.assert_called_once_with(8, MESSAGE_ID)
        assert save.call_args_list[0].kwargs["message_text"] == MESSAGE
    else:
        send.assert_not_called()
        save.assert_not_called()
    assert caplog.records
    assert not any(value in caplog.text for value in PRIVATE_VALUES)
    assert not any(record.exc_info for record in caplog.records)


@pytest.mark.parametrize("scenario", ["success", "http_error", "request_error", "timeout"])
def test_send_logs_and_retry_errors_omit_provider_contents(monkeypatch, caplog, scenario):
    response = Mock(status_code=503 if scenario == "http_error" else 200)
    response.text = " ".join(PRIVATE_VALUES)
    response.json.return_value = {"provider": PROVIDER_BODY, "success": True}
    post = Mock(return_value=response)
    if scenario in {"request_error", "timeout"}:
        error_type = requests.Timeout if scenario == "timeout" else requests.RequestException
        post.side_effect = error_type(" ".join(PRIVATE_VALUES))
    monkeypatch.setattr(service.requests, "post", post)

    with caplog.at_level(logging.INFO):
        result = service.send_wasender_text_message(API_KEY, PHONE, MESSAGE)

    assert result["success"] is (scenario == "success")
    assert set(result) == {"success", "data", "error"}
    if scenario in {"success", "http_error"}:
        assert result["data"] == response.json.return_value
    else:
        assert result["data"] is None
    assert post.call_args.kwargs["json"] == {"to": PHONE, "text": MESSAGE}
    assert post.call_args.kwargs["headers"]["Authorization"] == f"Bearer {API_KEY}"
    assert not any(value in caplog.text for value in PRIVATE_VALUES)
    assert not any(value in (result["error"] or "") for value in PRIVATE_VALUES)
    assert not any(record.exc_info for record in caplog.records)
    if scenario == "http_error":
        assert "503" in caplog.text
    if scenario == "request_error":
        assert "RequestException" in caplog.text


@pytest.mark.parametrize("failed", [False, True])
def test_webhook_route_does_not_log_payload_keys_or_exception_values(monkeypatch, caplog, failed):
    app = Flask(__name__)
    app.register_blueprint(routes.wasender_blueprint)
    process = Mock(side_effect=RuntimeError(MESSAGE) if failed else None)
    monkeypatch.setattr(routes, "process_wasender_webhook", process)
    # The route reads the channel on the request thread to pick its company's lane.
    monkeypatch.setattr(routes, "get_wasender_channel_by_secret", Mock(return_value={"id": 1, "company_id": 3}))

    with caplog.at_level(logging.INFO):
        response = app.test_client().post(f"/wasender/webhook/{SECRET}", json={MESSAGE: API_KEY})

    # The route now acknowledges WasenderAPI before the reply is generated, so
    # it answers 200 either way and a failure surfaces from the worker instead
    # of the response. The invariant this test exists for is unchanged, and now
    # also covers the worker's own log line -- which is where an exception
    # actually reaches the log under the deferred path.
    assert response.status_code == 200
    assert drain(), "webhook worker did not finish"
    process.assert_called_once_with({MESSAGE: API_KEY}, SECRET)
    assert not any(value in caplog.text for value in PRIVATE_VALUES)
    assert not any(record.exc_info for record in caplog.records)


@pytest.mark.parametrize("handler", ["connect_wasender", "list_wasender_channels", "disconnect_wasender"])
def test_management_errors_use_safe_shared_logging(monkeypatch, caplog, handler):
    app = Flask(__name__)
    monkeypatch.setattr(routes, "verify_chatbot_access", Mock(side_effect=RuntimeError(API_KEY)))
    with app.test_request_context("/?chatbot_id=4"), caplog.at_level(logging.ERROR):
        function = inspect.unwrap(getattr(routes, handler))
        _, status = function(8) if handler == "disconnect_wasender" else function()

    assert status == 500
    assert "RuntimeError" in caplog.text
    assert not any(value in caplog.text for value in PRIVATE_VALUES)
    assert not any(record.exc_info for record in caplog.records)


@pytest.mark.parametrize("success", [False, True])
def test_retry_logs_omit_customer_and_provider_details(monkeypatch, caplog, success):
    monkeypatch.setattr(retry, "get_retryable_failed_wasender_messages", Mock(return_value=[{
        "id": 12, "message_text": MESSAGE, "retry_count": 0,
        "conversation": {"id": 8, "chatbot_id": 4, "customer_phone": PHONE},
    }]))
    monkeypatch.setattr(retry, "get_bound_channel", Mock(return_value={"api_key": API_KEY}))
    monkeypatch.setattr(retry, "is_conversation_escalated", Mock(return_value=False))
    monkeypatch.setattr(retry, "send_wasender_text_message", Mock(return_value={
        "success": success, "error": PROVIDER_BODY,
    }))
    monkeypatch.setattr(retry, "mark_message_retrying", Mock())
    mark_sent = Mock()
    mark_failed = Mock()
    monkeypatch.setattr(retry, "mark_message_sent_after_retry", mark_sent)
    monkeypatch.setattr(retry, "mark_message_retry_failed", mark_failed)

    with caplog.at_level(logging.INFO):
        assert retry.retry_failed_wasender_messages_once() == 1

    assert mark_sent.called is success
    assert mark_failed.called is not success
    assert not any(value in caplog.text for value in PRIVATE_VALUES)


def test_retry_worker_omits_exception_values(monkeypatch, caplog):
    monkeypatch.setattr(retry, "retry_failed_wasender_messages_once", Mock(side_effect=RuntimeError(API_KEY)))
    monkeypatch.setattr(retry.time, "sleep", Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt), caplog.at_level(logging.ERROR):
        retry.wasender_retry_loop()

    assert "RuntimeError" in caplog.text
    assert not any(value in caplog.text for value in PRIVATE_VALUES)
    assert not any(record.exc_info for record in caplog.records)
