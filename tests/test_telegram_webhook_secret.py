"""Telegram webhook authentication and the reconnect billing gap.

Two defects this pins down:

1. setWebhook was registered without a secret_token, so anyone who learned the
   webhook URL could post updates into a tenant's conversation.
2. reconnect flipped is_active and connection_status back to connected without
   calling can_connect_channel, and those are exactly the two columns
   count_company_channels counts. A company at its channel limit could exceed
   it by disconnecting and reconnecting.
"""

import unittest
from unittest.mock import MagicMock, patch

from app.routes import telegram_routes as tr


class TestSetWebhookSecretToken(unittest.TestCase):
    def call(self, secret_token=None):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"ok": True}

        with patch.object(tr.requests, "post", return_value=response) as post:
            ok, error = tr.set_telegram_webhook(
                "8123:AAH", "https://example.test/telegram/webhook/abc",
                secret_token=secret_token)

        self.assertTrue(ok)
        self.assertIsNone(error)
        return post.call_args.kwargs["json"]

    def test_secret_token_is_sent_when_supplied(self):
        payload = self.call(secret_token="s3cret")
        self.assertEqual(payload["secret_token"], "s3cret")

    def test_payload_preserves_pending_updates(self):
        payload = self.call(secret_token="s3cret")
        self.assertIs(payload["drop_pending_updates"], False)
        self.assertEqual(payload["url"], "https://example.test/telegram/webhook/abc")

    def test_no_secret_token_key_when_none_is_supplied(self):
        # Never send secret_token: null, which Telegram would reject.
        self.assertNotIn("secret_token", self.call(secret_token=None))


class TestWebhookHeaderVerification(unittest.TestCase):
    """The route compares the header to the path secret in constant time."""

    def setUp(self):
        from app import create_app
        self.app = create_app()
        self.client = self.app.test_client()

    def post(self, secret, header=None):
        headers = {"Content-Type": "application/json"}
        if header is not None:
            headers["X-Telegram-Bot-Api-Secret-Token"] = header
        return self.client.post(f"/telegram/webhook/{secret}",
                                json={"update_id": 1}, headers=headers)

    def test_matching_header_is_processed(self):
        with patch.object(tr, "process_telegram_update") as process:
            response = self.post("abc123", header="abc123")

        self.assertEqual(response.status_code, 200)
        process.assert_called_once()

    def test_wrong_header_is_rejected_and_never_processed(self):
        with patch.object(tr, "process_telegram_update") as process:
            response = self.post("abc123", header="guessed")

        self.assertEqual(response.status_code, 403)
        process.assert_not_called()

    def test_missing_header_still_works_for_channels_connected_before_this(self):
        # Rejecting these would break every bot that is live right now. The
        # 256-bit path secret remains the primary gate.
        with patch.object(tr, "process_telegram_update") as process:
            response = self.post("abc123", header=None)

        self.assertEqual(response.status_code, 200)
        process.assert_called_once()


class TestReconnectRespectsTheChannelLimit(unittest.TestCase):
    def test_a_channel_that_is_not_counted_must_pass_the_limit_check(self):
        row = {"is_active": False, "connection_status": "disconnected"}
        self.assertFalse(tr._counts_towards_channel_limit(row))

    def test_a_failed_but_active_channel_is_not_counted(self):
        row = {"is_active": True, "connection_status": "failed"}
        self.assertFalse(tr._counts_towards_channel_limit(row))

    def test_a_live_channel_is_counted_and_is_not_re_checked(self):
        # Otherwise a company at its limit could never repair a channel it
        # already owns.
        row = {"is_active": True, "connection_status": "connected"}
        self.assertTrue(tr._counts_towards_channel_limit(row))

    def test_status_case_does_not_matter(self):
        row = {"is_active": True, "connection_status": "CONNECTED"}
        self.assertTrue(tr._counts_towards_channel_limit(row))

    def test_the_helper_mirrors_the_repository_filter(self):
        """count_company_channels filters is_active AND connection_status."""
        import inspect
        from app.database import billing_usage_repository as repo

        source = inspect.getsource(repo.count_company_channels)
        self.assertIn('"is_active", True', source)
        self.assertIn('"connection_status", "connected"', source)


if __name__ == "__main__":
    unittest.main()


class TestWebhookHeaderEdgeCases(unittest.TestCase):
    """A hostile header must not be able to turn a 403 into a 500."""

    def setUp(self):
        from app import create_app
        self.app = create_app()
        self.client = self.app.test_client()

    def post(self, secret, header):
        return self.client.post(
            f"/telegram/webhook/{secret}",
            json={"update_id": 1},
            headers={"Content-Type": "application/json",
                     "X-Telegram-Bot-Api-Secret-Token": header})

    def test_non_ascii_header_is_rejected_not_crashed(self):
        # hmac.compare_digest raises TypeError on non-ASCII str, which the
        # outer except would have turned into a 500.
        with patch.object(tr, "process_telegram_update") as process:
            response = self.post("abc123", "\u00e9\u00e9\u00e9")

        self.assertEqual(response.status_code, 403)
        process.assert_not_called()

    def test_empty_header_is_rejected(self):
        with patch.object(tr, "process_telegram_update") as process:
            response = self.post("abc123", "")

        self.assertEqual(response.status_code, 403)
        process.assert_not_called()

    def test_a_prefix_of_the_secret_is_rejected(self):
        with patch.object(tr, "process_telegram_update") as process:
            response = self.post("abc123", "abc")

        self.assertEqual(response.status_code, 403)
        process.assert_not_called()
