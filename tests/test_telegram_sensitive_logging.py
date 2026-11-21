"""Synthetic Telegram failures must never copy credentials into application logs."""

import logging
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from app.services.webhook_worker import drain
import requests
from flask import Flask

from app.routes import telegram_routes
from app.services import media_send_service
from app.utils import telegram_utils
from app.utils.api_errors import GENERIC_MESSAGE, server_error


BOT_TOKEN = "synthetic-telegram-token"
WEBHOOK_SECRET = "synthetic-telegram-webhook-secret"
CUSTOMER_TEXT = "synthetic private customer message"
CHAT_ID = "synthetic-private-chat-id"
MEDIA_URL = "https://example.test/private-file?token=synthetic-media-secret"


@pytest.fixture(params=["message", "contact"])
def sender(request):
    if request.param == "message":
        return lambda: telegram_utils.send_telegram_message(
            BOT_TOKEN,
            CHAT_ID,
            CUSTOMER_TEXT,
            reply_markup={"inline_keyboard": [[{"text": "Help", "callback_data": "help"}]]},
            parse_mode="MarkdownV2",
        )
    return lambda: telegram_utils.send_telegram_contact_request(BOT_TOKEN, CHAT_ID)


def assert_no_sensitive_logs(caplog):
    for value in (BOT_TOKEN, WEBHOOK_SECRET, CUSTOMER_TEXT, CHAT_ID, MEDIA_URL):
        assert value not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_http_error_does_not_log_token_from_telegram_request_url(sender, caplog):
    response = requests.Response()
    response.status_code = 401
    response.url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response.reason = "Unauthorized"

    with patch.object(telegram_utils.requests, "post", return_value=response) as post:
        with caplog.at_level(logging.ERROR):
            assert sender() is None

    post.assert_called_once()
    assert_no_sensitive_logs(caplog)
    assert "HTTPError" in caplog.text


def test_connection_error_does_not_log_request_or_customer_data(sender, caplog):
    error = requests.ConnectionError(
        f"Cannot connect to /bot{BOT_TOKEN}/sendMessage "
        f"with chat_id={CHAT_ID} and text={CUSTOMER_TEXT}"
    )

    with patch.object(telegram_utils.requests, "post", side_effect=error):
        with caplog.at_level(logging.ERROR):
            assert sender() is None

    assert_no_sensitive_logs(caplog)
    assert "ConnectionError" in caplog.text


def test_timeout_retains_failure_return_without_sensitive_logs(sender, caplog):
    with patch.object(
        telegram_utils.requests,
        "post",
        side_effect=requests.Timeout(f"Timeout for /bot{BOT_TOKEN}/sendMessage"),
    ):
        with caplog.at_level(logging.ERROR):
            assert sender() is None

    assert_no_sensitive_logs(caplog)
    assert "Timeout" in caplog.text


def test_success_preserves_request_payload_and_response(sender, caplog):
    response = MagicMock(status_code=200)
    response.json.return_value = {"ok": True, "result": {"message_id": 42}}

    with patch.object(telegram_utils.requests, "post", return_value=response) as post:
        with caplog.at_level(logging.INFO):
            assert sender() == response.json.return_value

    response.raise_for_status.assert_called_once_with()
    assert post.call_args.args == (
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
    )
    assert post.call_args.kwargs["timeout"] == 10
    payload = post.call_args.kwargs["json"]
    assert payload["chat_id"] == CHAT_ID
    if "parse_mode" in payload:
        assert payload["text"] == CUSTOMER_TEXT
        assert payload["parse_mode"] == "MarkdownV2"
        assert payload["disable_web_page_preview"] is True
        assert payload["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "help"
    else:
        assert payload["reply_markup"]["keyboard"][0][0]["request_contact"] is True
        assert payload["reply_markup"]["one_time_keyboard"] is True
        assert payload["reply_markup"]["resize_keyboard"] is True
    assert_no_sensitive_logs(caplog)
    assert "200" in caplog.text


def test_unknown_webhook_channel_does_not_log_authentication_secret(caplog):
    with patch.object(
        telegram_utils, "get_telegram_channel_by_secret", return_value=None
    ), patch.object(telegram_utils.requests, "post") as post:
        with caplog.at_level(logging.ERROR):
            assert telegram_utils.process_telegram_update({}, WEBHOOK_SECRET) is None

    post.assert_not_called()
    assert_no_sensitive_logs(caplog)
    assert "No active Telegram channel" in caplog.text


@pytest.fixture
def telegram_client():
    app = Flask(__name__)
    app.register_blueprint(telegram_routes.telegram_blueprint)
    return app.test_client()


@pytest.mark.parametrize("failed_endpoint", ["answerCallbackQuery", "sendChatAction"])
def test_callback_network_error_does_not_escape_to_webhook_logs(
    failed_endpoint, telegram_client, caplog
):
    def reply(url, **kwargs):
        if url.endswith(f"/{failed_endpoint}"):
            raise requests.ConnectionError(f"Failed request to {url}")
        return MagicMock()

    channel = {"id": 1, "chatbot_id": 2, "company_id": 3, "bot_token": BOT_TOKEN, "telegram_bot_id": "123", "is_active": True, "connection_status": "connected", "verified_at": "2026-09-14"}
    update = {
        "update_id": 4,
        "callback_query": {
            "id": "callback-5",
            "message": {"message_id": 6, "chat": {"id": 7, "type": "private"}},
            "from": {"id": 7},
            "data": CUSTOMER_TEXT,
        },
    }
    with patch.object(
        telegram_utils, "get_telegram_channel_by_secret", return_value=channel
    ), patch.object(
        telegram_utils, "claim_telegram_update", return_value=True
    ), patch.object(telegram_utils, "release_telegram_update_claim"), patch.object(telegram_utils.requests, "post", side_effect=reply) as post:
        with caplog.at_level(logging.INFO):
            response = telegram_client.post(
                f"/telegram/webhook/{WEBHOOK_SECRET}",
                json=update,
                headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
            )
            # Drained inside the patch context: the update is processed on a
            # worker thread now, and letting these patches unwind first would
            # let the worker reach the real Telegram client.
            assert drain(), "webhook worker did not finish"

    assert post.call_args.args[0].endswith(f"/{failed_endpoint}")
    # Telegram is acknowledged before the update is processed, so a failure
    # during processing no longer becomes the webhook's response. It still must
    # not leak the customer's text or the bot token, which is what this guards,
    # and the error still has to be identifiable in the log.
    assert response.status_code == 200
    assert response.json == {"status": "ok"}
    assert_no_sensitive_logs(caplog)
    assert "ConnectionError" in caplog.text


@pytest.fixture(params=["telegram", "meta"])
def media_sender(request):
    attachment = {
        "media_url": MEDIA_URL,
        "media_type": "image",
        "caption": CUSTOMER_TEXT,
        "meta_template_name": "test_template",
    }
    if request.param == "telegram":
        return lambda: media_send_service.send_telegram_media(BOT_TOKEN, CHAT_ID, attachment)
    return lambda: media_send_service.send_meta_media_template(
        {"access_token": BOT_TOKEN, "phone_number_id": "test-phone-number-id"},
        attachment,
        "+60000000000",
    )


def test_media_provider_error_does_not_log_response_body(media_sender, caplog):
    response = MagicMock(
        status_code=400,
        text=f"Rejected {BOT_TOKEN} for {CHAT_ID}: {CUSTOMER_TEXT} with {MEDIA_URL}",
    )
    with patch.object(media_send_service.requests, "post", return_value=response) as post:
        with caplog.at_level(logging.ERROR):
            assert media_sender() is False

    post.assert_called_once()
    assert_no_sensitive_logs(caplog)
    assert "400" in caplog.text


def test_media_request_error_does_not_log_credentials_or_payload(media_sender, caplog):
    error = requests.ConnectionError(f"Request {BOT_TOKEN} {CUSTOMER_TEXT} {MEDIA_URL}")
    with patch.object(media_send_service.requests, "post", side_effect=error) as post:
        with caplog.at_level(logging.ERROR):
            assert media_sender() is False

    post.assert_called_once()
    assert_no_sensitive_logs(caplog)
    assert "ConnectionError" in caplog.text


def test_media_success_retains_payload_and_boolean_result(media_sender, caplog):
    response = MagicMock(status_code=200)
    with patch.object(media_send_service.requests, "post", return_value=response) as post:
        with caplog.at_level(logging.INFO):
            assert media_sender() is True

    post.assert_called_once()
    assert post.call_args.kwargs["timeout"] == 20
    payload = post.call_args.kwargs["json"]
    if "template" in payload:
        template = payload["template"]
        assert template["name"] == "test_template"
        assert template["components"][0]["parameters"][0]["image"]["link"] == MEDIA_URL
    else:
        assert payload.get("photo", payload.get("mediaUrl")) == MEDIA_URL
        assert payload["caption"] == CUSTOMER_TEXT
    assert_no_sensitive_logs(caplog)
    assert "200" in caplog.text


def test_shared_server_error_does_not_log_exception_or_chained_traceback(caplog):
    app = Flask(__name__)
    with app.app_context(), caplog.at_level(logging.ERROR):
        try:
            try:
                raise requests.ConnectionError(f"Request for {BOT_TOKEN} {CUSTOMER_TEXT}")
            except requests.ConnectionError as cause:
                raise RuntimeError(f"Storage failure containing {WEBHOOK_SECRET}") from cause
        except RuntimeError as error:
            response, status = server_error("synthetic_operation", error)

    assert status == 500
    assert response.json == {"status": "error", "message": GENERIC_MESSAGE}
    assert_no_sensitive_logs(caplog)
    assert "synthetic_operation" in caplog.text
    assert "RuntimeError" in caplog.text


def test_shared_server_error_retains_safe_custom_message_without_exception(caplog):
    app = Flask(__name__)
    with app.app_context(), caplog.at_level(logging.ERROR):
        response, status = server_error("synthetic_operation", message="Please retry later.")

    assert status == 500
    assert response.json == {"status": "error", "message": "Please retry later."}
    assert_no_sensitive_logs(caplog)


@pytest.mark.parametrize("operation", ["connect", "reconnect"])
@pytest.mark.parametrize("failed_endpoint", ["getMe", "setWebhook"])
@pytest.mark.parametrize("failure_kind", ["transport", "provider_response", "provider_description"])
def test_telegram_connection_failure_retains_status_without_exposing_credentials(
    operation, failed_endpoint, failure_kind, telegram_client, caplog
):
    channel = {
        "id": 1,
        "chatbot_id": 2,
        "company_id": 3,
        "bot_token": BOT_TOKEN,
        "is_active": True,
        "connection_status": "connected",
    }

    def telegram_response(url, **kwargs):
        if url.endswith(f"/{failed_endpoint}"):
            if failure_kind == "transport":
                raise requests.ConnectionError(f"Request to {url} with {WEBHOOK_SECRET}")
            if failure_kind == "provider_description":
                response = MagicMock(status_code=200)
                response.json.return_value = {
                    "ok": False, "description": f"Rejected {BOT_TOKEN} for {WEBHOOK_SECRET}"
                }
                return response
            return MagicMock(status_code=400, text=f"Failed {url} with {WEBHOOK_SECRET}")
        response = MagicMock(status_code=200)
        response.json.return_value = {"ok": True, "result": {"id": 4, "username": "test_bot"}}
        return response

    with ExitStack() as stack:
        stack.enter_context(patch.dict("os.environ", {"PUBLIC_BASE_URL": "https://example.test"}))
        stack.enter_context(patch(
            "app.decorators.auth_decorator.jwt.decode", return_value={"user_id": 5}
        ))
        stack.enter_context(patch(
            "app.database.user_repository.get_user_by_id",
            return_value={"id": 5, "company_id": 3, "role": "admin", "status": "active"},
        ))
        stack.enter_context(patch.object(telegram_routes, "verify_chatbot_access", return_value=channel))
        stack.enter_context(patch.object(telegram_routes, "publish_test_block", return_value=None))
        stack.enter_context(patch.object(telegram_routes, "get_bot_by_id", return_value=channel))
        stack.enter_context(patch.object(telegram_routes, "get_telegram_channel_by_id", return_value=channel))
        stack.enter_context(patch.object(telegram_routes, "get_telegram_channel_by_bot_id", return_value=None))
        stack.enter_context(patch.object(telegram_routes, "claim_telegram_channel_operation", return_value=channel))
        stack.enter_context(patch.object(telegram_routes, "create_telegram_channel", return_value=channel))
        stack.enter_context(patch.object(telegram_routes, "can_connect_channel"))
        stack.enter_context(patch.object(telegram_routes, "get_telegram_channels_by_chatbot", return_value=[]))
        update = stack.enter_context(patch.object(telegram_routes, "update_telegram_channel"))
        stack.enter_context(patch.object(telegram_routes.requests, "get", side_effect=telegram_response))
        stack.enter_context(patch.object(telegram_routes.requests, "post", side_effect=telegram_response))
        stack.enter_context(caplog.at_level(logging.ERROR))
        if operation == "connect":
            response = telegram_client.post(
                "/api/telegram/connect?chatbot_id=2",
                json={"bot_token": BOT_TOKEN, "telegram_bot_id": "123", "is_active": True, "connection_status": "connected", "verified_at": "2026-09-14"},
                headers={"Authorization": "Bearer synthetic-auth-token"},
            )
        else:
            response = telegram_client.put(
                "/api/telegram/channels/1/reconnect?chatbot_id=2",
                headers={"Authorization": "Bearer synthetic-auth-token"},
            )

    assert_no_sensitive_logs(caplog)
    assert BOT_TOKEN not in response.get_data(as_text=True)
    assert WEBHOOK_SECRET not in response.get_data(as_text=True)
    if failure_kind == "transport":
        assert response.status_code == 400
        assert "Could not reach Telegram" in response.json["message"]
        if failed_endpoint == "setWebhook":
            assert update.call_args.args[1]["connection_status"] == "failed"
    else:
        assert response.status_code == 400
        if failure_kind == "provider_response":
            assert "400" in response.json["message"]
        else:
            assert response.json["message"]
        if failed_endpoint == "setWebhook":
            update.assert_called_once()
            assert update.call_args.args[1]["last_error"] == response.json["message"]
        else:
            update.assert_not_called()


def test_delete_webhook_failure_does_not_return_provider_body(caplog):
    response = MagicMock(status_code=400, text=f"Rejected {BOT_TOKEN} for {WEBHOOK_SECRET}")
    with patch.object(telegram_routes.requests, "post", return_value=response):
        success, error = telegram_routes.delete_telegram_webhook(BOT_TOKEN)

    assert success is False
    assert "400" in error
    assert BOT_TOKEN not in error
    assert WEBHOOK_SECRET not in error
    assert_no_sensitive_logs(caplog)


@pytest.mark.parametrize("operation", ["set", "delete", "getMe", "getWebhookInfo"])
def test_webhook_management_does_not_return_provider_description(operation, caplog):
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "ok": False,
        "description": f"Rejected {BOT_TOKEN} for {WEBHOOK_SECRET}",
    }
    with patch.object(
        telegram_routes.requests, "post", return_value=response
    ), patch.object(telegram_routes.requests, "get", return_value=response):
        if operation == "set":
            success, error = telegram_routes.set_telegram_webhook(
                BOT_TOKEN, f"https://example.test/telegram/webhook/{WEBHOOK_SECRET}"
            )
        elif operation == "delete":
            success, error = telegram_routes.delete_telegram_webhook(BOT_TOKEN)
        elif operation == "getMe":
            success, error = telegram_routes.validate_telegram_bot_token(BOT_TOKEN)
        else:
            success, error = telegram_routes.get_telegram_webhook_info(BOT_TOKEN)

    assert not success
    assert error
    assert BOT_TOKEN not in error
    assert WEBHOOK_SECRET not in error
    assert_no_sensitive_logs(caplog)


@pytest.fixture
def authenticated_telegram_client(telegram_client):
    with patch(
        "app.decorators.auth_decorator.jwt.decode", return_value={"user_id": 5}
    ), patch(
        "app.database.user_repository.get_user_by_id",
        return_value={"id": 5, "company_id": 3, "role": "admin", "status": "active"},
    ), patch.object(telegram_routes, "verify_chatbot_access", return_value={"company_id": 3}):
        yield telegram_client


@pytest.mark.parametrize("raw_error", [
    f"502 Bad Gateway for /bot{BOT_TOKEN}: {CUSTOMER_TEXT}",
    {"description": f"Failure for /bot{BOT_TOKEN}: {CUSTOMER_TEXT}"},
])
def test_delivery_report_logs_only_safe_failure_description(
    authenticated_telegram_client, raw_error, caplog
):
    webhook_url = f"https://example.test/telegram/webhook/{WEBHOOK_SECRET}"
    provider_response = MagicMock(status_code=200)
    provider_response.json.return_value = {
        "ok": True,
        "result": {
            "url": webhook_url,
            "last_error_message": raw_error,
            "last_error_date": 1700000000,
            "pending_update_count": 3,
        },
    }
    channel = {"id": 1, "chatbot_id": 2, "bot_token": BOT_TOKEN, "webhook_url": webhook_url,
               "is_active": True, "connection_status": "connected"}
    with patch.object(
        telegram_routes, "get_telegram_channel_by_id", return_value=channel
    ), patch.object(telegram_routes.requests, "get", return_value=provider_response):
        with caplog.at_level(logging.WARNING):
            response = authenticated_telegram_client.get(
                "/api/telegram/channels/1/delivery?chatbot_id=2",
                headers={"Authorization": "Bearer synthetic-auth-token"},
            )

    assert response.status_code == 200
    assert response.json["data"]["delivery_status"] == "failed"
    assert response.json["data"]["pending_update_count"] == 3
    assert response.json["data"]["webhook_url_matches"] is True
    assert_no_sensitive_logs(caplog)
    for sensitive in (BOT_TOKEN, WEBHOOK_SECRET, CUSTOMER_TEXT):
        assert sensitive not in response.get_data(as_text=True)


@pytest.mark.parametrize("stored_error, expected_error", [
    (f"Request /bot{BOT_TOKEN} failed with {WEBHOOK_SECRET}", telegram_routes.DELIVERY_GENERIC_MESSAGE),
    (f"503 provider response: {CUSTOMER_TEXT}", telegram_routes.DELIVERY_UNREACHABLE_MESSAGE),
    (f"Telegram setWebhook failed with status 400: {BOT_TOKEN}", telegram_routes.DELIVERY_GENERIC_MESSAGE),
    (f"Unauthorized\n{WEBHOOK_SECRET}", telegram_routes.DELIVERY_GENERIC_MESSAGE),
    ({"description": CUSTOMER_TEXT}, telegram_routes.DELIVERY_GENERIC_MESSAGE),
    ("Unauthorized", "Unauthorized"),
    ("Telegram setWebhook failed with status 400", "Telegram setWebhook failed with status 400"),
    (telegram_routes.DELIVERY_CERTIFICATE_MESSAGE, telegram_routes.DELIVERY_CERTIFICATE_MESSAGE),
    (None, None),
])
def test_channel_list_safely_projects_historical_error_without_rewriting_it(
    authenticated_telegram_client, stored_error, expected_error, caplog
):
    channel = {
        "id": 1, "chatbot_id": 2, "company_id": 3, "bot_token": BOT_TOKEN,
        "webhook_url": "https://example.test/admin-visible-hook",
        "connection_status": "failed", "is_active": True, "last_error": stored_error,
    }
    with patch.object(
        telegram_routes, "get_telegram_channels_by_chatbot", return_value=[channel]
    ), patch.object(telegram_routes, "update_telegram_channel") as update:
        response = authenticated_telegram_client.get(
            "/api/telegram/channels?chatbot_id=2",
            headers={"Authorization": "Bearer synthetic-auth-token"},
        )

    assert response.status_code == 200
    data = response.json["data"][0]
    assert data["last_error"] == expected_error
    assert data["connection_status"] == "failed"
    assert data["is_active"] is True
    assert data["webhook_url"] == channel["webhook_url"]
    assert channel["last_error"] == stored_error
    update.assert_not_called()
    assert_no_sensitive_logs(caplog)
    for sensitive in (BOT_TOKEN, WEBHOOK_SECRET, CUSTOMER_TEXT):
        assert sensitive not in response.get_data(as_text=True)


@pytest.mark.parametrize("pending_count", [BOT_TOKEN, {"error": CUSTOMER_TEXT}])
def test_delivery_report_rejects_sensitive_values_in_numeric_field(
    authenticated_telegram_client, pending_count, caplog
):
    webhook_url = f"https://example.test/telegram/webhook/{WEBHOOK_SECRET}"
    channel = {"id": 1, "chatbot_id": 2, "bot_token": BOT_TOKEN, "webhook_url": webhook_url,
               "is_active": True, "connection_status": "connected"}
    info = {"url": webhook_url, "pending_update_count": pending_count}
    with patch.object(
        telegram_routes, "get_telegram_channel_by_id", return_value=channel
    ), patch.object(telegram_routes, "get_telegram_webhook_info", return_value=(info, None)):
        response = authenticated_telegram_client.get(
            "/api/telegram/channels/1/delivery?chatbot_id=2",
            headers={"Authorization": "Bearer synthetic-auth-token"},
        )

    assert response.status_code == 200
    assert response.json["data"]["pending_update_count"] is None
    assert response.json["data"]["delivery_status"] == "connected"
    assert response.json["data"]["webhook_url_matches"] is True
    assert_no_sensitive_logs(caplog)
    for sensitive in (BOT_TOKEN, WEBHOOK_SECRET, CUSTOMER_TEXT):
        assert sensitive not in response.get_data(as_text=True)
