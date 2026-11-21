"""Telegram connections must be verified, not assumed.

setWebhook only records a URL string. Telegram never checks that the URL is
reachable, so POST /api/telegram/connect used to answer "connected" for a bot
whose deliveries could never arrive - the exact failure that left a live bot
silent behind an offline tunnel. These tests pin down four seams:

1. getWebhookInfo is read after registration, and a reported delivery failure
   marks the channel failed instead of connected.
2. A failed verification keeps the channel row and its saved token.
3. The live delivery route never leaks a credential.
4. A plan limit produces a customer reply and a 403, never silence or a 500.
"""

import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from app import create_app
from app.routes import telegram_routes as tr
from app.services.billing_guard import BillingLimitError


AUTH_HEADERS = {"Authorization": "Bearer test-token"}
COMPANY_ID = 42
CHATBOT_ID = 29
CHANNEL_ID = 7
BOT_TOKEN = "8123456789:AAHtestsecrettoken"
WEBHOOK_SECRET = "storedwebhooksecretvalue"
DATABASE_USER = {
    "id": 31,
    "company_id": COMPANY_ID,
    "email": "telegram-admin@example.test",
    "role": "admin",
    "status": "active",
}


@contextmanager
def authenticated_admin():
    with patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={"user_id": DATABASE_USER["id"], "role": "admin"},
    ), patch(
        "app.database.user_repository.get_user_by_id",
        return_value=DATABASE_USER,
    ):
        yield


def _stored_channel(**overrides):
    channel = {
        "id": CHANNEL_ID,
        "company_id": COMPANY_ID,
        "chatbot_id": CHATBOT_ID,
        "bot_token": BOT_TOKEN,
        "bot_username": "demo_bot",
        "telegram_bot_id": "8123456789",
        "webhook_secret": WEBHOOK_SECRET,
        "webhook_url": "https://example.test/telegram/webhook/" + WEBHOOK_SECRET,
        "connection_status": "connected",
        "is_active": True,
    }
    channel.update(overrides)
    return channel


class _FakeTelegram:
    """Answers getWebhookInfo with whatever setWebhook was last given."""

    def __init__(self, last_error_message=None, last_error_date=None):
        self.registered_url = None
        self.last_error_message = last_error_message
        self.last_error_date = last_error_date

    def set_webhook(self, bot_token, webhook_url, secret_token=None):
        self.registered_url = webhook_url
        return True, None

    def webhook_info(self, bot_token):
        info = {
            "url": self.registered_url,
            "pending_update_count": 3,
            "ip_address": "203.0.113.10",
        }
        if self.last_error_message:
            info["last_error_message"] = self.last_error_message
            info["last_error_date"] = self.last_error_date
        return info, None


class TestDeliveryErrorTranslation(unittest.TestCase):
    """The user gets plain language; Telegram's own words stay in the log."""

    def test_a_404_from_the_tunnel_reads_as_unreachable(self):
        self.assertEqual(
            tr.describe_telegram_delivery_error(
                "Wrong response from the webhook: 404 Not Found"),
            tr.DELIVERY_UNREACHABLE_MESSAGE,
        )

    def test_a_bad_gateway_reads_as_unreachable(self):
        self.assertEqual(
            tr.describe_telegram_delivery_error(
                "Wrong response from the webhook: 502 Bad Gateway"),
            tr.DELIVERY_UNREACHABLE_MESSAGE,
        )

    def test_a_certificate_problem_says_so(self):
        self.assertEqual(
            tr.describe_telegram_delivery_error("SSL error {error:1416F086}"),
            tr.DELIVERY_CERTIFICATE_MESSAGE,
        )

    def test_anything_else_falls_back_to_the_generic_sentence(self):
        self.assertEqual(
            tr.describe_telegram_delivery_error("Too Many Requests: retry after 1"),
            tr.DELIVERY_GENERIC_MESSAGE,
        )

    def test_no_vendor_jargon_reaches_the_user(self):
        for message in (
            tr.DELIVERY_UNREACHABLE_MESSAGE,
            tr.DELIVERY_CERTIFICATE_MESSAGE,
            tr.DELIVERY_GENERIC_MESSAGE,
            tr.DELIVERY_WRONG_SERVER_MESSAGE,
        ):
            with self.subTest(message=message):
                lowered = message.lower()
                self.assertNotIn("webhook", lowered)
                self.assertNotIn("404", lowered)
                self.assertNotIn("ssl", lowered)


class TestCheckWebhookDelivery(unittest.TestCase):
    def test_a_reported_error_after_our_registration_is_a_failure(self):
        info = {
            "url": "https://example.test/hook",
            "last_error_message": "Wrong response from the webhook: 404 Not Found",
            "last_error_date": 1700000100,
        }
        with patch.object(tr, "get_telegram_webhook_info", return_value=(info, None)):
            status, reason, _ = tr.check_telegram_webhook_delivery(
                BOT_TOKEN, "https://example.test/hook", registered_since=1700000000)

        self.assertEqual(status, tr.DELIVERY_STATUS_FAILED)
        self.assertEqual(reason, tr.DELIVERY_UNREACHABLE_MESSAGE)

    def test_an_error_older_than_our_registration_belongs_to_the_old_url(self):
        info = {
            "url": "https://example.test/hook",
            "last_error_message": "Wrong response from the webhook: 404 Not Found",
            "last_error_date": 1699999000,
        }
        with patch.object(tr, "get_telegram_webhook_info", return_value=(info, None)):
            status, reason, _ = tr.check_telegram_webhook_delivery(
                BOT_TOKEN, "https://example.test/hook", registered_since=1700000000)

        self.assertEqual(status, tr.DELIVERY_STATUS_OK)
        self.assertIsNone(reason)

    def test_a_bot_pointed_at_another_server_is_a_failure(self):
        info = {"url": "https://someone-else.test/telegram/webhook/other"}
        with patch.object(tr, "get_telegram_webhook_info", return_value=(info, None)):
            status, reason, _ = tr.check_telegram_webhook_delivery(
                BOT_TOKEN, "https://example.test/hook", registered_since=1)

        self.assertEqual(status, tr.DELIVERY_STATUS_FAILED)
        self.assertEqual(reason, tr.DELIVERY_WRONG_SERVER_MESSAGE)

    def test_an_unreadable_report_is_unknown_not_failed(self):
        # Our own blind spot must never flap a working channel to failed.
        with patch.object(tr, "get_telegram_webhook_info", return_value=(None, "boom")):
            status, reason, info = tr.check_telegram_webhook_delivery(
                BOT_TOKEN, "https://example.test/hook", registered_since=1)

        self.assertEqual(status, tr.DELIVERY_STATUS_UNKNOWN)
        self.assertIsNone(reason)
        self.assertEqual(info, {})

    def test_a_non_numeric_error_date_does_not_raise(self):
        info = {
            "url": "https://example.test/hook",
            "last_error_message": "Connection refused",
            "last_error_date": "not-a-timestamp",
        }
        with patch.object(tr, "get_telegram_webhook_info", return_value=(info, None)):
            status, _, _ = tr.check_telegram_webhook_delivery(
                BOT_TOKEN, "https://example.test/hook", registered_since=1)

        self.assertEqual(status, tr.DELIVERY_STATUS_OK)


class TestGetWebhookInfoHelper(unittest.TestCase):
    def test_it_calls_get_webhook_info(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"ok": True, "result": {"url": "https://x.test"}}

        with patch.object(tr.requests, "get", return_value=response) as get:
            info, error = tr.get_telegram_webhook_info(BOT_TOKEN)

        self.assertIsNone(error)
        self.assertEqual(info, {"url": "https://x.test"})
        self.assertIn("/getWebhookInfo", get.call_args[0][0])

    def test_a_network_failure_never_returns_the_token(self):
        # The requests exception text embeds the request URL, token included.
        failure = tr.requests.RequestException(
            "Max retries exceeded with url: /bot" + BOT_TOKEN + "/getWebhookInfo")

        with patch.object(tr.requests, "get", side_effect=failure):
            info, error = tr.get_telegram_webhook_info(BOT_TOKEN)

        self.assertIsNone(info)
        self.assertNotIn(BOT_TOKEN, error)

    def test_a_telegram_level_error_is_reported(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"ok": False, "description": "Unauthorized"}

        with patch.object(tr.requests, "get", return_value=response):
            info, error = tr.get_telegram_webhook_info(BOT_TOKEN)

        self.assertIsNone(info)
        self.assertEqual(error, "Unauthorized")


class _RouteTestCase(unittest.TestCase):
    def setUp(self):
        ownership = patch.object(tr, "get_telegram_channel_by_bot_id", return_value=None)
        claim = patch.object(tr, "claim_telegram_channel_operation", return_value=_stored_channel(connection_status="pending"))
        activate = patch.object(tr, "activate_telegram_channel", side_effect=lambda channel_id, chatbot_id, company_id, **kwargs:
                                tr.update_telegram_channel(channel_id, {"connection_status": "connected", "last_error": None, "is_active": True}))
        channels = patch.object(tr, "get_telegram_channels_by_chatbot", return_value=[])
        publish_gate = patch.object(tr, "publish_test_block", return_value=None)
        publish_gate.start()
        self.addCleanup(publish_gate.stop)
        ownership.start()
        claim.start()
        activate.start()
        channels.start()
        self.addCleanup(ownership.stop)
        self.addCleanup(claim.stop)
        self.addCleanup(activate.stop)
        self.addCleanup(channels.stop)
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()


class TestConnectVerifiesDelivery(_RouteTestCase):
    @contextmanager
    def _connect_stack(self, telegram, updates):
        def record_update(channel_id, payload, **kwargs):
            updates.append((channel_id, payload))
            merged = _stored_channel()
            merged.update(payload)
            return merged

        # The webhook destination comes from the server's PUBLIC_BASE_URL and is
        # deliberately not accepted from the request body, so a caller cannot
        # point a tenant's Telegram deliveries at a host they control.
        with patch.dict(tr.os.environ, {"PUBLIC_BASE_URL": "https://example.test"}), \
                authenticated_admin(), \
                patch.object(tr, "verify_chatbot_access",
                             return_value={"id": CHATBOT_ID, "company_id": COMPANY_ID}), \
                patch.object(tr, "get_bot_by_id",
                             return_value={"id": CHATBOT_ID, "company_id": COMPANY_ID}), \
                patch.object(tr, "validate_telegram_bot_token",
                             return_value=({"id": 8123456789, "username": "demo_bot"}, None)), \
                patch.object(tr, "can_connect_channel"), \
                patch.object(tr, "create_telegram_channel",
                             return_value=_stored_channel(connection_status="pending")), \
                patch.object(tr, "set_telegram_webhook", side_effect=telegram.set_webhook), \
                patch.object(tr, "get_telegram_webhook_info",
                             side_effect=telegram.webhook_info), \
                patch.object(tr, "update_telegram_channel", side_effect=record_update):
            yield

    def _connect(self, telegram, updates):
        with self._connect_stack(telegram, updates):
            return self.client.post(
                "/api/telegram/connect?chatbot_id=" + str(CHATBOT_ID),
                headers=AUTH_HEADERS,
                json={"bot_token": BOT_TOKEN},
            )

    def test_a_reported_delivery_error_is_not_reported_as_connected(self):
        updates = []
        telegram = _FakeTelegram(
            last_error_message="Wrong response from the webhook: 404 Not Found",
            last_error_date=4102444800,
        )

        response = self._connect(telegram, updates)
        body = response.get_json()

        self.assertNotEqual(response.status_code, 200)
        self.assertEqual(body["status"], "error")
        self.assertEqual(body["code"], "webhook_not_delivering")
        self.assertEqual(body["message"], tr.DELIVERY_UNREACHABLE_MESSAGE)
        self.assertEqual(updates[-1][1]["connection_status"], "failed")
        self.assertEqual(updates[-1][1]["last_error"], tr.DELIVERY_UNREACHABLE_MESSAGE)

    def test_a_clean_report_still_connects(self):
        updates = []
        response = self._connect(_FakeTelegram(), updates)
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["data"]["connection_status"], "connected")
        self.assertEqual(updates[-1][1]["connection_status"], "connected")
        self.assertIsNone(updates[-1][1]["last_error"])

    def test_a_failed_verification_keeps_the_channel_row_and_the_token(self):
        updates = []
        telegram = _FakeTelegram(
            last_error_message="SSL error {error:1416F086}",
            last_error_date=4102444800,
        )

        with self._connect_stack(telegram, updates), \
                patch.object(tr, "delete_telegram_webhook") as delete_hook:
            response = self.client.post(
                "/api/telegram/connect?chatbot_id=" + str(CHATBOT_ID),
                headers=AUTH_HEADERS,
                json={"bot_token": BOT_TOKEN},
            )

        payload = updates[-1][1]
        self.assertEqual(response.status_code, 502)
        delete_hook.assert_not_called()
        self.assertEqual(updates[-1][0], CHANNEL_ID)
        self.assertNotIn("bot_token", payload)
        self.assertNotIn("is_active", payload)
        self.assertEqual(payload["last_error"], tr.DELIVERY_CERTIFICATE_MESSAGE)

    def test_no_credential_reaches_the_connect_response(self):
        updates = []
        telegram = _FakeTelegram(
            last_error_message="Wrong response from the webhook: 404 Not Found",
            last_error_date=4102444800,
        )
        response = self._connect(telegram, updates)

        body = response.get_data(as_text=True)
        self.assertNotIn(BOT_TOKEN, body)
        self.assertNotIn("bot_token", body)
        self.assertNotIn("webhook_secret", body)


class TestReconnectVerifiesDelivery(_RouteTestCase):
    @contextmanager
    def _reconnect_stack(self, telegram, updates, channel, billing_error=None):
        def record_update(channel_id, payload, **kwargs):
            updates.append((channel_id, payload))
            merged = dict(channel)
            merged.update(payload)
            return merged

        with authenticated_admin(), \
                patch.dict("os.environ", {"PUBLIC_BASE_URL": "https://example.test"}), \
                patch.object(tr, "verify_chatbot_access",
                             return_value={"id": CHATBOT_ID, "company_id": COMPANY_ID}), \
                patch.object(tr, "get_telegram_channel_by_id", return_value=channel), \
                patch.object(tr, "can_connect_channel", side_effect=billing_error), \
                patch.object(tr, "validate_telegram_bot_token",
                             return_value=({"id": 8123456789, "username": "demo_bot"}, None)), \
                patch.object(tr, "set_telegram_webhook", side_effect=telegram.set_webhook), \
                patch.object(tr, "get_telegram_webhook_info",
                             side_effect=telegram.webhook_info), \
                patch.object(tr, "update_telegram_channel", side_effect=record_update):
            yield

    def _reconnect(self, telegram, updates, channel, billing_error=None):
        with self._reconnect_stack(telegram, updates, channel, billing_error):
            return self.client.put(
                "/api/telegram/channels/" + str(CHANNEL_ID)
                + "/reconnect?chatbot_id=" + str(CHATBOT_ID),
                headers=AUTH_HEADERS,
            )

    def test_a_reported_delivery_error_is_not_reported_as_reconnected(self):
        updates = []
        telegram = _FakeTelegram(
            last_error_message="Connection refused",
            last_error_date=4102444800,
        )
        response = self._reconnect(telegram, updates, _stored_channel())
        payload = updates[-1][1]

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()["code"], "webhook_not_delivering")
        self.assertEqual(payload["connection_status"], "failed")
        self.assertEqual(payload["last_error"], tr.DELIVERY_UNREACHABLE_MESSAGE)

    def test_the_new_secret_is_saved_even_when_verification_fails(self):
        # Telegram already holds it. A row keeping the old secret would drop
        # every delivery that succeeds once the server recovers.
        updates = []
        telegram = _FakeTelegram(
            last_error_message="Connection refused",
            last_error_date=4102444800,
        )
        self._reconnect(telegram, updates, _stored_channel())
        payload = updates[-1][1]

        self.assertTrue(telegram.registered_url.endswith(payload["webhook_secret"]))
        self.assertEqual(payload["webhook_url"], telegram.registered_url)
        self.assertIs(payload["is_active"], True)

    def test_a_clean_report_still_reconnects(self):
        updates = []
        response = self._reconnect(_FakeTelegram(), updates, _stored_channel())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(updates[-1][1]["connection_status"], "connected")

    def test_a_plan_limit_returns_403_with_a_code_not_500(self):
        updates = []
        channel = _stored_channel(is_active=False, connection_status="disconnected")
        limit = BillingLimitError(
            "You have reached the channel limit for your plan.",
            code="channel_limit",
        )

        response = self._reconnect(_FakeTelegram(), updates, channel,
                                   billing_error=limit)
        body = response.get_json()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(body["code"], "channel_limit")
        self.assertEqual(body["message"],
                         "You have reached the channel limit for your plan.")
        self.assertEqual(updates, [])


class TestDeliveryRoute(_RouteTestCase):
    @contextmanager
    def _stack(self, info, channel=None):
        stored = channel if channel is not None else _stored_channel()
        with authenticated_admin(), \
                patch.object(tr, "verify_chatbot_access",
                             return_value={"id": CHATBOT_ID, "company_id": COMPANY_ID}), \
                patch.object(tr, "get_telegram_channel_by_id", return_value=stored), \
                patch.object(tr, "get_telegram_webhook_info", return_value=(info, None)):
            yield

    def _get(self, chatbot_id=CHATBOT_ID, channel_id=CHANNEL_ID):
        return self.client.get(
            "/api/telegram/channels/" + str(channel_id)
            + "/delivery?chatbot_id=" + str(chatbot_id),
            headers=AUTH_HEADERS,
        )

    def test_a_live_failure_is_reported_even_when_the_column_says_connected(self):
        info = {
            "url": _stored_channel()["webhook_url"],
            "pending_update_count": 12,
            "last_error_message": "Wrong response from the webhook: 502 Bad Gateway",
            "last_error_date": 1700000000,
        }
        with self._stack(info):
            response = self._get()

        data = response.get_json()["data"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["connection_status"], "connected")
        self.assertEqual(data["delivery_status"], "failed")
        self.assertIs(data["is_delivering"], False)
        self.assertEqual(data["message"], tr.DELIVERY_UNREACHABLE_MESSAGE)
        self.assertEqual(data["pending_update_count"], 12)

    def test_a_healthy_channel_reports_delivering(self):
        info = {"url": _stored_channel()["webhook_url"], "pending_update_count": 0}
        with self._stack(info):
            response = self._get()

        data = response.get_json()["data"]
        self.assertEqual(data["delivery_status"], "connected")
        self.assertIs(data["is_delivering"], True)
        self.assertIs(data["webhook_url_matches"], True)
        self.assertEqual(data["message"], tr.DELIVERY_OK_MESSAGE)

    def test_it_never_leaks_the_bot_token_or_the_webhook_secret(self):
        info = {
            "url": _stored_channel()["webhook_url"],
            "pending_update_count": 0,
            "ip_address": "203.0.113.10",
        }
        with self._stack(info):
            response = self._get()

        body = response.get_data(as_text=True)
        self.assertNotIn(BOT_TOKEN, body)
        self.assertNotIn(WEBHOOK_SECRET, body)
        self.assertNotIn("bot_token", body)
        self.assertNotIn("webhook_secret", body)

    def test_another_chatbots_channel_is_refused(self):
        with self._stack({"url": "https://example.test/hook"},
                         channel=_stored_channel(chatbot_id=CHATBOT_ID + 1)):
            response = self._get()

        self.assertEqual(response.status_code, 403)

    def test_a_missing_chatbot_id_is_refused(self):
        with self._stack({"url": "https://example.test/hook"}):
            response = self.client.get(
                "/api/telegram/channels/" + str(CHANNEL_ID) + "/delivery",
                headers=AUTH_HEADERS,
            )

        self.assertEqual(response.status_code, 400)

    def test_an_unknown_channel_is_a_404(self):
        with self._stack({"url": "https://example.test/hook"}, channel=False):
            response = self._get()

        self.assertEqual(response.status_code, 404)

    def test_a_member_cannot_read_delivery_state(self):
        member = dict(DATABASE_USER)
        member["role"] = "member"
        with patch("app.decorators.auth_decorator.jwt.decode",
                   return_value={"user_id": member["id"], "role": "member"}), \
                patch("app.database.user_repository.get_user_by_id",
                      return_value=member), \
                patch.object(tr, "get_telegram_channel_by_id") as lookup:
            response = self._get()

        self.assertEqual(response.status_code, 403)
        lookup.assert_not_called()

    def test_an_unauthenticated_request_is_refused(self):
        with patch.object(tr, "get_telegram_channel_by_id") as lookup:
            response = self.client.get(
                "/api/telegram/channels/" + str(CHANNEL_ID)
                + "/delivery?chatbot_id=" + str(CHATBOT_ID))

        self.assertEqual(response.status_code, 401)
        lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
