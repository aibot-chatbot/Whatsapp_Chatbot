"""Tests for scripts/reregister_telegram_webhooks.py.

The script re-points every connected Telegram bot at the current
PUBLIC_BASE_URL. It talks to Telegram and to Supabase, so every one of those
seams is mocked here: these tests must never touch a real bot or a real row.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reregister_telegram_webhooks.py"


def load_script():
    spec = importlib.util.spec_from_file_location("reregister_telegram_webhooks", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ReregisterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def channel(self, **overrides):
        row = {
            "id": 7,
            "chatbot_id": 42,
            "bot_token": "123:AAH-fake-token",
            "bot_username": "olympicedu_bot",
            "is_active": True,
        }
        row.update(overrides)
        return row

    def test_dry_run_writes_nothing(self):
        with patch.object(self.mod, "update_telegram_channel") as update, \
             patch.object(self.mod, "set_telegram_webhook") as set_hook, \
             patch.object(self.mod, "validate_telegram_bot_token",
                          return_value=({"id": 1, "username": "olympicedu_bot"}, None)):
            outcome, _ = self.mod.reregister(self.channel(), "https://x.example.com", apply=False)

        self.assertEqual(outcome, "would-update")
        update.assert_not_called()
        set_hook.assert_not_called()

    def test_dry_run_never_prints_the_secret(self):
        with patch.object(self.mod, "validate_telegram_bot_token",
                          return_value=({"id": 1, "username": "b"}, None)):
            _, detail = self.mod.reregister(self.channel(), "https://x.example.com", apply=False)

        self.assertIn("***", detail)
        self.assertNotIn("/telegram/webhook/wgt", detail)

    def test_a_delivering_bot_is_marked_connected(self):
        with patch.object(self.mod, "validate_telegram_bot_token",
                          return_value=({"id": 1, "username": "olympicedu_bot"}, None)), \
             patch.object(self.mod, "set_telegram_webhook", return_value=(True, None)), \
             patch.object(self.mod, "check_telegram_webhook_delivery",
                          return_value=("ok", "", {})), \
             patch.object(self.mod, "update_telegram_channel") as update:
            outcome, _ = self.mod.reregister(self.channel(), "https://x.example.com", apply=True)

        self.assertEqual(outcome, "connected")
        written = update.call_args[0][1]
        self.assertEqual(written["connection_status"], "connected")
        self.assertIsNone(written["last_error"])

    def test_each_run_mints_a_fresh_secret(self):
        seen = []

        def capture(_token, url, secret_token=None):
            seen.append(secret_token)
            return True, None

        with patch.object(self.mod, "validate_telegram_bot_token",
                          return_value=({"id": 1, "username": "b"}, None)), \
             patch.object(self.mod, "set_telegram_webhook", side_effect=capture), \
             patch.object(self.mod, "check_telegram_webhook_delivery",
                          return_value=("ok", "", {})), \
             patch.object(self.mod, "update_telegram_channel"):
            self.mod.reregister(self.channel(), "https://x.example.com", apply=True)
            self.mod.reregister(self.channel(), "https://x.example.com", apply=True)

        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0], seen[1], "a reused secret would survive a leaked URL")
        self.assertTrue(all(s for s in seen))

    def test_registered_but_not_delivering_is_not_reported_connected(self):
        with patch.object(self.mod, "validate_telegram_bot_token",
                          return_value=({"id": 1, "username": "b"}, None)), \
             patch.object(self.mod, "set_telegram_webhook", return_value=(True, None)), \
             patch.object(self.mod, "check_telegram_webhook_delivery",
                          return_value=("failed", "Telegram cannot reach your server right now.", {})), \
             patch.object(self.mod, "update_telegram_channel") as update:
            outcome, detail = self.mod.reregister(self.channel(), "https://x.example.com", apply=True)

        self.assertEqual(outcome, "undelivered")
        self.assertEqual(update.call_args[0][1]["connection_status"], "failed")
        self.assertIn("cannot reach", detail)

    def test_a_channel_with_no_token_is_skipped_not_broken(self):
        with patch.object(self.mod, "update_telegram_channel") as update:
            outcome, _ = self.mod.reregister(
                self.channel(bot_token=None), "https://x.example.com", apply=True)

        self.assertEqual(outcome, "skipped")
        update.assert_not_called()

    def test_a_rejected_token_deactivates_but_keeps_the_row(self):
        with patch.object(self.mod, "validate_telegram_bot_token",
                          return_value=(None, "Unauthorized")), \
             patch.object(self.mod, "update_telegram_channel") as update:
            outcome, _ = self.mod.reregister(self.channel(), "https://x.example.com", apply=True)

        self.assertEqual(outcome, "failed")
        written = update.call_args[0][1]
        self.assertEqual(written["connection_status"], "failed")
        self.assertFalse(written["is_active"])
        # The row and its token survive, so a later run can retry it.
        self.assertNotIn("bot_token", written)

    def test_no_detail_line_ever_carries_a_token(self):
        with patch.object(self.mod, "validate_telegram_bot_token",
                          return_value=(None, "Unauthorized")), \
             patch.object(self.mod, "update_telegram_channel"):
            _, detail = self.mod.reregister(self.channel(), "https://x.example.com", apply=True)

        self.assertNotIn("123:AAH-fake-token", detail)


if __name__ == "__main__":
    unittest.main()
