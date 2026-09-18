"""Tests for scripts/reregister_whatsapp_webhooks.py.

The script re-points the Meta WhatsApp webhook at the current PUBLIC_BASE_URL.
It talks to the Graph API and to Supabase, so every one of those seams is
mocked here: these tests must never touch a real Meta app or a real row.

Two facts these tests exist to protect:

  * a secret (tenant access token, app secret, verify token) must never reach
    stdout or a database column, and
  * connection_status must never be written, because
    get_whatsapp_channel_by_phone_number_id filters on
    connection_status == "connected" -- writing "failed" would take a tenant
    whose messages are still arriving via the app-level callback and stop
    routing them.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reregister_whatsapp_webhooks.py"

NEW = "https://omnexa.com.my"
OLD = "https://aibot-chatbot-my.fly.dev"
APP_SECRET = "meta-app-secret-never-print"
VERIFY_TOKEN = "meta-verify-token-never-print"
TENANT_TOKEN = "EAAG-tenant-access-token-never-print"


def load_script():
    spec = importlib.util.spec_from_file_location("reregister_whatsapp_webhooks", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class WhatsappReregisterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def setUp(self):
        creds = patch.object(self.mod, "meta_app_credentials",
                             return_value=("555000", APP_SECRET, VERIFY_TOKEN))
        creds.start()
        self.addCleanup(creds.stop)

    def channel(self, **overrides):
        row = {
            "id": 11,
            "chatbot_id": 42,
            "company_id": 3,
            "phone_number_id": "1111",
            "whatsapp_business_account_id": "2222",
            "waba_id": "2222",
            "access_token": TENANT_TOKEN,
            "display_phone_number": "+60123456789",
            "webhook_url": OLD + "/webhook",
            "connection_status": "connected",
            "is_active": True,
        }
        row.update(overrides)
        return row

    # ---------------- dry run ----------------

    def test_dry_run_writes_nothing(self):
        with patch.object(self.mod, "read_waba_override", return_value=(True, OLD + "/webhook")), \
             patch.object(self.mod, "set_waba_override") as set_override, \
             patch.object(self.mod, "update_whatsapp_channel") as update:
            outcome, _ = self.mod.reregister(self.channel(), NEW, apply=False)

        self.assertEqual(outcome, "would-update")
        set_override.assert_not_called()
        update.assert_not_called()

    def test_dry_run_on_the_app_subscription_writes_nothing(self):
        with patch.object(self.mod, "read_app_subscription",
                          return_value={"object": "whatsapp_business_account",
                                        "callback_url": OLD + "/webhook",
                                        "active": True, "fields": ["messages"]}), \
             patch.object(self.mod, "set_app_subscription") as set_app:
            outcome, detail = self.mod.reregister_app(NEW, apply=False)

        self.assertEqual(outcome, "app-would-update")
        set_app.assert_not_called()
        self.assertIn(NEW + "/webhook", detail)

    # ---------------- apply + verify ----------------

    def test_apply_repoints_the_app_callback_and_reads_it_back(self):
        reads = [
            {"object": "whatsapp_business_account", "callback_url": OLD + "/webhook",
             "active": True, "fields": ["messages"]},
            {"object": "whatsapp_business_account", "callback_url": NEW + "/webhook",
             "active": True, "fields": ["messages"]},
        ]
        with patch.object(self.mod, "read_app_subscription", side_effect=reads), \
             patch.object(self.mod, "set_app_subscription") as set_app:
            outcome, _ = self.mod.reregister_app(NEW, apply=True)

        self.assertEqual(outcome, "app-updated")
        set_app.assert_called_once()
        # The read-back is the proof. Meta accepts a callback_url it has not
        # contacted, so the POST returning success proves nothing at all.
        self.assertEqual(set_app.call_args[0][0], NEW + "/webhook")

    def test_an_app_callback_that_did_not_take_is_reported_failed(self):
        """Meta answered the POST with success and kept the old callback.
        That is exactly the silent failure this tooling exists to catch."""
        reads = [
            {"object": "whatsapp_business_account", "callback_url": OLD + "/webhook",
             "active": True, "fields": ["messages"]},
            {"object": "whatsapp_business_account", "callback_url": OLD + "/webhook",
             "active": True, "fields": ["messages"]},
        ]
        with patch.object(self.mod, "read_app_subscription", side_effect=reads), \
             patch.object(self.mod, "set_app_subscription"):
            outcome, detail = self.mod.reregister_app(NEW, apply=True)

        self.assertEqual(outcome, "app-failed")
        self.assertIn(OLD, detail)

    def test_an_app_callback_already_correct_is_a_no_op(self):
        with patch.object(self.mod, "read_app_subscription",
                          return_value={"object": "whatsapp_business_account",
                                        "callback_url": NEW + "/webhook",
                                        "active": True, "fields": ["messages"]}), \
             patch.object(self.mod, "set_app_subscription") as set_app:
            outcome, _ = self.mod.reregister_app(NEW, apply=True)

        self.assertEqual(outcome, "app-ok")
        set_app.assert_not_called()

    def test_a_stale_waba_override_is_repointed_and_read_back(self):
        """A per-WABA override beats the app-level callback. Fixing only the
        app default would leave this tenant posting to the dead host while the
        dashboard still says connected."""
        reads = [(True, OLD + "/webhook"), (True, NEW + "/webhook")]
        with patch.object(self.mod, "read_waba_override", side_effect=reads), \
             patch.object(self.mod, "set_waba_override") as set_override, \
             patch.object(self.mod, "update_whatsapp_channel") as update:
            outcome, _ = self.mod.reregister(self.channel(), NEW, apply=True)

        self.assertEqual(outcome, "updated")
        set_override.assert_called_once()
        self.assertEqual(update.call_args[0][1]["webhook_url"], NEW + "/webhook")

    def test_a_channel_already_pointing_at_the_new_url_is_a_no_op(self):
        with patch.object(self.mod, "read_waba_override", return_value=(True, None)), \
             patch.object(self.mod, "set_waba_override") as set_override, \
             patch.object(self.mod, "update_whatsapp_channel") as update:
            outcome, _ = self.mod.reregister(
                self.channel(webhook_url=NEW + "/webhook"), NEW, apply=True)

        self.assertEqual(outcome, "no-op")
        set_override.assert_not_called()
        update.assert_not_called()

    def test_an_override_that_did_not_take_is_reported_failed(self):
        reads = [(True, OLD + "/webhook"), (True, OLD + "/webhook")]
        with patch.object(self.mod, "read_waba_override", side_effect=reads), \
             patch.object(self.mod, "set_waba_override"), \
             patch.object(self.mod, "update_whatsapp_channel") as update:
            outcome, detail = self.mod.reregister(self.channel(), NEW, apply=True)

        self.assertEqual(outcome, "failed")
        self.assertIn(OLD, detail)
        # The stored URL must not claim the new host when the provider kept the old one.
        for call in update.call_args_list:
            self.assertNotEqual(call[0][1].get("webhook_url"), NEW + "/webhook")

    def test_an_unreadable_provider_does_not_condemn_the_channel(self):
        with patch.object(self.mod, "read_waba_override",
                          side_effect=requests.RequestException("Graph is unwell")), \
             patch.object(self.mod, "set_waba_override") as set_override, \
             patch.object(self.mod, "update_whatsapp_channel") as update:
            outcome, _ = self.mod.reregister(self.channel(), NEW, apply=True)

        self.assertEqual(outcome, "unverified")
        set_override.assert_not_called()
        update.assert_not_called()

    def test_a_channel_without_a_token_is_skipped_not_broken(self):
        with patch.object(self.mod, "update_whatsapp_channel") as update:
            outcome, _ = self.mod.reregister(
                self.channel(access_token=None), NEW, apply=True)

        self.assertEqual(outcome, "skipped")
        update.assert_not_called()

    # ---------------- safety ----------------

    def test_connection_status_is_never_written(self):
        """get_whatsapp_channel_by_phone_number_id filters on
        connection_status == "connected". Writing "failed" here would stop
        routing inbound messages for a tenant whose app-level callback is
        still delivering perfectly well."""
        reads = [(True, OLD + "/webhook"), (True, OLD + "/webhook")]
        with patch.object(self.mod, "read_waba_override", side_effect=reads), \
             patch.object(self.mod, "set_waba_override"), \
             patch.object(self.mod, "update_whatsapp_channel") as update:
            self.mod.reregister(self.channel(), NEW, apply=True)

        for call in update.call_args_list:
            self.assertNotIn("connection_status", call[0][1])
            self.assertNotIn("is_active", call[0][1])

    def test_no_detail_line_ever_carries_a_secret(self):
        leaky = (TENANT_TOKEN, APP_SECRET, VERIFY_TOKEN)
        details = []

        with patch.object(self.mod, "read_waba_override",
                          side_effect=ValueError("Provider verification failed.")), \
             patch.object(self.mod, "update_whatsapp_channel"):
            details.append(self.mod.reregister(self.channel(), NEW, apply=True)[1])

        with patch.object(self.mod, "read_waba_override", return_value=(True, OLD + "/webhook")), \
             patch.object(self.mod, "update_whatsapp_channel"):
            details.append(self.mod.reregister(self.channel(), NEW, apply=False)[1])

        with patch.object(self.mod, "read_app_subscription",
                          return_value={"callback_url": OLD + "/webhook", "active": True,
                                        "fields": ["messages"]}), \
             patch.object(self.mod, "set_app_subscription"):
            details.append(self.mod.reregister_app(NEW, apply=False)[1])

        for detail in details:
            for secret in leaky:
                self.assertNotIn(secret, detail)

    def test_the_stored_row_never_receives_a_secret(self):
        reads = [(True, OLD + "/webhook"), (True, NEW + "/webhook")]
        with patch.object(self.mod, "read_waba_override", side_effect=reads), \
             patch.object(self.mod, "set_waba_override"), \
             patch.object(self.mod, "update_whatsapp_channel") as update:
            self.mod.reregister(self.channel(), NEW, apply=True)

        written = update.call_args[0][1]
        self.assertNotIn("access_token", written)
        for value in written.values():
            self.assertNotIn(APP_SECRET, str(value))
            self.assertNotIn(VERIFY_TOKEN, str(value))

    # ---------------- partial failure ----------------

    def test_a_partial_failure_names_every_channel_and_exits_non_zero(self):
        """Channel 2 of 3 fails. The operator must not be left guessing which
        of the other two went through."""
        channels = [self.channel(id=1, phone_number_id="aaa", display_phone_number="+1"),
                    self.channel(id=2, phone_number_id="bbb", display_phone_number="+2"),
                    self.channel(id=3, phone_number_id="ccc", display_phone_number="+3")]
        outcomes = iter([("updated", "+1: repointed"),
                         ("failed", "+2: override did not take"),
                         ("updated", "+3: repointed")])
        printed = []

        with patch.object(self.mod, "load_channels", return_value=channels), \
             patch.object(self.mod, "reregister", side_effect=lambda *a, **k: next(outcomes)), \
             patch.object(self.mod, "reregister_app", return_value=("app-ok", "already correct")), \
             patch.object(self.mod, "public_base_url", return_value=NEW), \
             patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))), \
             patch.object(sys, "argv", ["reregister_whatsapp_webhooks.py", "--apply"]):
            code = self.mod.main()

        self.assertEqual(code, 2)
        body = "\n".join(printed)
        for name in ("+1", "+2", "+3"):
            self.assertIn(name, body)
        self.assertIn("failed", body)

    def test_the_blast_radius_is_printed_before_anything_changes(self):
        channels = [self.channel(id=1, company_id=3), self.channel(id=2, company_id=4)]
        printed = []

        with patch.object(self.mod, "load_channels", return_value=channels), \
             patch.object(self.mod, "reregister", return_value=("no-op", "fine")), \
             patch.object(self.mod, "reregister_app", return_value=("app-ok", "fine")), \
             patch.object(self.mod, "public_base_url", return_value=NEW), \
             patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))), \
             patch.object(sys, "argv", ["reregister_whatsapp_webhooks.py"]):
            code = self.mod.main()

        self.assertEqual(code, 0)
        header = "\n".join(printed[:6])
        self.assertIn("2", header)
        self.assertIn(NEW, header)
        self.assertIn("dry run", header.lower())


if __name__ == "__main__":
    unittest.main()
