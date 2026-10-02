"""Tests for scripts/reregister_wasender_webhooks.py.

The script re-points every connected WasenderAPI session at the current
PUBLIC_BASE_URL. It talks to WasenderAPI and to Supabase, so every one of those
seams is mocked here: these tests must never touch a real session or a real row.

The Wasender webhook has no signature header -- the secret in the URL path is
the only authentication factor on it. Several tests below exist purely to prove
that secret never reaches stdout.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reregister_wasender_webhooks.py"

NEW = "https://omnexa.com.my"
OLD = "https://aibot-chatbot-my.fly.dev"
SECRET = "path-secret-that-must-never-be-printed"
API_KEY = "wasender-api-key-never-print"
PAT = "wasender-personal-access-token-never-print"


def load_script():
    spec = importlib.util.spec_from_file_location("reregister_wasender_webhooks", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class WasenderReregisterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def channel(self, **overrides):
        row = {
            "id": 9,
            "chatbot_id": 42,
            "company_id": 3,
            "session_id": "8811",
            "session_name": "Sales line",
            "phone_number": "+60123456789",
            "api_key": API_KEY,
            "webhook_secret": SECRET,
            "webhook_url": OLD + "/wasender/webhook/" + SECRET,
            "connection_status": "connected",
            "is_active": True,
        }
        row.update(overrides)
        return row

    def session(self, url, **overrides):
        row = {
            "id": 8811,
            "webhook_url": url,
            "webhook_enabled": True,
            "webhook_events": ["messages.received"],
        }
        row.update(overrides)
        return row

    # ---------------- dry run ----------------

    def test_dry_run_writes_nothing(self):
        stale = OLD + "/wasender/webhook/" + SECRET
        with patch.object(self.mod, "read_session", return_value=self.session(stale)), \
             patch.object(self.mod, "set_session_webhook") as set_hook, \
             patch.object(self.mod, "update_wasender_channel") as update:
            outcome, _ = self.mod.reregister(self.channel(), NEW, PAT, apply=False)

        self.assertEqual(outcome, "would-update")
        set_hook.assert_not_called()
        update.assert_not_called()

    def test_dry_run_never_prints_the_path_secret(self):
        stale = OLD + "/wasender/webhook/" + SECRET
        with patch.object(self.mod, "read_session", return_value=self.session(stale)):
            _, detail = self.mod.reregister(self.channel(), NEW, PAT, apply=False)

        self.assertNotIn(SECRET, detail)
        # The house pattern is a SHA-256 fingerprint prefix, so the operator can
        # still tell two channels apart without the secret being readable.
        self.assertIn(self.mod.fingerprint(SECRET), detail)

    # ---------------- apply + verify ----------------

    def test_apply_repoints_the_session_and_reads_it_back(self):
        stale = OLD + "/wasender/webhook/" + SECRET
        fresh = NEW + "/wasender/webhook/" + SECRET
        with patch.object(self.mod, "read_session",
                          side_effect=[self.session(stale), self.session(fresh)]), \
             patch.object(self.mod, "set_session_webhook") as set_hook, \
             patch.object(self.mod, "update_wasender_channel") as update:
            outcome, _ = self.mod.reregister(self.channel(), NEW, PAT, apply=True)

        self.assertEqual(outcome, "updated")
        self.assertEqual(set_hook.call_args[0][2], fresh)
        self.assertEqual(update.call_args[0][1]["webhook_url"], fresh)

    def test_a_session_that_did_not_take_the_new_url_is_reported_failed(self):
        """WasenderAPI answered the update with success and kept the old URL.
        Only the read-back can tell, which is the whole point of doing one."""
        stale = OLD + "/wasender/webhook/" + SECRET
        with patch.object(self.mod, "read_session",
                          side_effect=[self.session(stale), self.session(stale)]), \
             patch.object(self.mod, "set_session_webhook"), \
             patch.object(self.mod, "update_wasender_channel") as update:
            outcome, detail = self.mod.reregister(self.channel(), NEW, PAT, apply=True)

        self.assertEqual(outcome, "failed")
        self.assertIn(OLD, detail)
        for call in update.call_args_list:
            self.assertNotEqual(call[0][1].get("webhook_url"), NEW + "/wasender/webhook/" + SECRET)

    def test_a_disabled_webhook_is_not_reported_as_verified(self):
        """The URL can be right while delivery is off. Reading the URL alone
        would call this a success and the tenant would still receive nothing."""
        stale = OLD + "/wasender/webhook/" + SECRET
        fresh = NEW + "/wasender/webhook/" + SECRET
        with patch.object(self.mod, "read_session",
                          side_effect=[self.session(stale),
                                       self.session(fresh, webhook_enabled=False)]), \
             patch.object(self.mod, "set_session_webhook"), \
             patch.object(self.mod, "update_wasender_channel"):
            outcome, _ = self.mod.reregister(self.channel(), NEW, PAT, apply=True)

        self.assertEqual(outcome, "failed")

    def test_a_session_not_subscribed_to_messages_received_is_not_verified(self):
        stale = OLD + "/wasender/webhook/" + SECRET
        fresh = NEW + "/wasender/webhook/" + SECRET
        with patch.object(self.mod, "read_session",
                          side_effect=[self.session(stale),
                                       self.session(fresh, webhook_events=["messages.update"])]), \
             patch.object(self.mod, "set_session_webhook"), \
             patch.object(self.mod, "update_wasender_channel"):
            outcome, _ = self.mod.reregister(self.channel(), NEW, PAT, apply=True)

        self.assertEqual(outcome, "failed")

    def test_a_session_already_pointing_at_the_new_url_is_a_no_op(self):
        fresh = NEW + "/wasender/webhook/" + SECRET
        with patch.object(self.mod, "read_session", return_value=self.session(fresh)), \
             patch.object(self.mod, "set_session_webhook") as set_hook, \
             patch.object(self.mod, "update_wasender_channel") as update:
            outcome, _ = self.mod.reregister(
                self.channel(webhook_url=fresh), NEW, PAT, apply=True)

        self.assertEqual(outcome, "no-op")
        set_hook.assert_not_called()
        update.assert_not_called()

    def test_a_correct_provider_with_a_stale_row_repairs_only_the_row(self):
        """Re-running after a crash between the provider call and the write.
        The provider is already right, so do not touch it -- just heal the row."""
        fresh = NEW + "/wasender/webhook/" + SECRET
        with patch.object(self.mod, "read_session", return_value=self.session(fresh)), \
             patch.object(self.mod, "set_session_webhook") as set_hook, \
             patch.object(self.mod, "update_wasender_channel") as update:
            outcome, _ = self.mod.reregister(self.channel(), NEW, PAT, apply=True)

        self.assertEqual(outcome, "updated")
        set_hook.assert_not_called()
        self.assertEqual(update.call_args[0][1]["webhook_url"], fresh)

    def test_an_unreadable_provider_does_not_condemn_the_channel(self):
        with patch.object(self.mod, "read_session",
                          side_effect=requests.RequestException("Wasender is unwell")), \
             patch.object(self.mod, "set_session_webhook") as set_hook, \
             patch.object(self.mod, "update_wasender_channel") as update:
            outcome, _ = self.mod.reregister(self.channel(), NEW, PAT, apply=True)

        self.assertEqual(outcome, "unverified")
        set_hook.assert_not_called()
        update.assert_not_called()

    def test_a_channel_without_a_session_id_is_skipped_not_broken(self):
        with patch.object(self.mod, "update_wasender_channel") as update, \
             patch.object(self.mod, "set_session_webhook") as set_hook:
            outcome, _ = self.mod.reregister(
                self.channel(session_id=None), NEW, PAT, apply=True)

        self.assertEqual(outcome, "skipped")
        update.assert_not_called()
        set_hook.assert_not_called()

    def test_without_a_personal_access_token_nothing_is_touched(self):
        """The session endpoint needs the tenant's own personal access token.
        Rewriting the row without it would leave the database claiming a URL
        WasenderAPI has never heard of."""
        with patch.object(self.mod, "read_session") as read, \
             patch.object(self.mod, "update_wasender_channel") as update:
            outcome, _ = self.mod.reregister(self.channel(), NEW, None, apply=True)

        self.assertEqual(outcome, "needs-token")
        read.assert_not_called()
        update.assert_not_called()

    # ---------------- idempotence of the secret ----------------

    def test_rerunning_keeps_the_same_secret_so_the_second_run_is_a_no_op(self):
        """Minting a fresh secret every run would make the target URL different
        every time, so no run could ever report a no-op -- and every run would
        open a window where the provider and the database disagree."""
        fresh = NEW + "/wasender/webhook/" + SECRET
        stale = OLD + "/wasender/webhook/" + SECRET
        channel = self.channel()

        with patch.object(self.mod, "read_session",
                          side_effect=[self.session(stale), self.session(fresh)]), \
             patch.object(self.mod, "set_session_webhook"), \
             patch.object(self.mod, "update_wasender_channel") as update:
            first, _ = self.mod.reregister(channel, NEW, PAT, apply=True)
        written = update.call_args[0][1]

        with patch.object(self.mod, "read_session", return_value=self.session(fresh)), \
             patch.object(self.mod, "set_session_webhook"), \
             patch.object(self.mod, "update_wasender_channel"):
            second, _ = self.mod.reregister({**channel, **written}, NEW, PAT, apply=True)

        self.assertEqual(first, "updated")
        self.assertEqual(second, "no-op")
        self.assertNotIn("webhook_secret", written)

    def test_rotating_the_secret_is_opt_in_and_writes_the_new_one(self):
        stale = OLD + "/wasender/webhook/" + SECRET
        captured = {}

        def capture(_session_id, _token, url):
            captured["url"] = url

        with patch.object(self.mod, "read_session",
                          side_effect=lambda *a: self.session(captured.get("url", stale))), \
             patch.object(self.mod, "set_session_webhook", side_effect=capture), \
             patch.object(self.mod, "update_wasender_channel") as update:
            outcome, detail = self.mod.reregister(
                self.channel(), NEW, PAT, apply=True, rotate_secret=True)

        self.assertEqual(outcome, "updated")
        written = update.call_args[0][1]
        self.assertIn("webhook_secret", written)
        self.assertNotEqual(written["webhook_secret"], SECRET)
        self.assertTrue(written["webhook_url"].startswith(NEW + "/wasender/webhook/"))
        self.assertNotIn(written["webhook_secret"], detail)

    # ---------------- safety ----------------

    def test_connection_status_is_never_written(self):
        """get_wasender_channel_by_secret filters on
        connection_status == "connected", so writing "failed" here would stop
        routing inbound messages for a channel that may still be delivering."""
        stale = OLD + "/wasender/webhook/" + SECRET
        with patch.object(self.mod, "read_session",
                          side_effect=[self.session(stale), self.session(stale)]), \
             patch.object(self.mod, "set_session_webhook"), \
             patch.object(self.mod, "update_wasender_channel") as update:
            self.mod.reregister(self.channel(), NEW, PAT, apply=True)

        for call in update.call_args_list:
            self.assertNotIn("connection_status", call[0][1])
            self.assertNotIn("is_active", call[0][1])

    def test_no_detail_line_ever_carries_a_secret(self):
        leaky = (SECRET, API_KEY, PAT)
        stale = OLD + "/wasender/webhook/" + SECRET
        details = []

        with patch.object(self.mod, "read_session",
                          side_effect=[self.session(stale), self.session(stale)]), \
             patch.object(self.mod, "set_session_webhook"), \
             patch.object(self.mod, "update_wasender_channel"):
            details.append(self.mod.reregister(self.channel(), NEW, PAT, apply=True)[1])

        with patch.object(self.mod, "read_session",
                          side_effect=ValueError("Provider verification failed.")), \
             patch.object(self.mod, "update_wasender_channel"):
            details.append(self.mod.reregister(self.channel(), NEW, PAT, apply=True)[1])

        details.append(self.mod.reregister(self.channel(), NEW, None, apply=True)[1])

        with patch.object(self.mod, "read_session", return_value=self.session(stale)):
            details.append(self.mod.reregister(self.channel(), NEW, PAT, apply=False)[1])

        for detail in details:
            for secret in leaky:
                self.assertNotIn(secret, detail)

    def test_the_stored_row_never_receives_a_credential(self):
        stale = OLD + "/wasender/webhook/" + SECRET
        fresh = NEW + "/wasender/webhook/" + SECRET
        with patch.object(self.mod, "read_session",
                          side_effect=[self.session(stale), self.session(fresh)]), \
             patch.object(self.mod, "set_session_webhook"), \
             patch.object(self.mod, "update_wasender_channel") as update:
            self.mod.reregister(self.channel(), NEW, PAT, apply=True)

        written = update.call_args[0][1]
        self.assertNotIn("api_key", written)
        for value in written.values():
            self.assertNotIn(API_KEY, str(value))
            self.assertNotIn(PAT, str(value))

    def test_the_fingerprint_is_short_and_is_not_the_secret(self):
        digest = self.mod.fingerprint(SECRET)
        self.assertEqual(len(digest), 12)
        self.assertNotIn(digest, SECRET)

    # ---------------- partial failure ----------------

    def test_a_partial_failure_names_every_channel_and_exits_non_zero(self):
        channels = [self.channel(id=1, session_name="one"),
                    self.channel(id=2, session_name="two"),
                    self.channel(id=3, session_name="three")]
        outcomes = iter([("updated", "one: repointed"),
                         ("failed", "two: session kept the old URL"),
                         ("updated", "three: repointed")])
        printed = []

        with patch.object(self.mod, "load_channels", return_value=channels), \
             patch.object(self.mod, "reregister", side_effect=lambda *a, **k: next(outcomes)), \
             patch.object(self.mod, "public_base_url", return_value=NEW), \
             patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))), \
             patch.object(sys, "argv", ["reregister_wasender_webhooks.py", "--apply",
                                        "--personal-access-token", PAT]):
            code = self.mod.main()

        self.assertEqual(code, 2)
        body = "\n".join(printed)
        for name in ("one", "two", "three"):
            self.assertIn(name, body)
        self.assertNotIn(PAT, body)

    def test_the_blast_radius_is_printed_before_anything_changes(self):
        channels = [self.channel(id=1, company_id=3), self.channel(id=2, company_id=4)]
        printed = []

        with patch.object(self.mod, "load_channels", return_value=channels), \
             patch.object(self.mod, "reregister", return_value=("no-op", "fine")), \
             patch.object(self.mod, "public_base_url", return_value=NEW), \
             patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))), \
             patch.object(sys, "argv", ["reregister_wasender_webhooks.py"]):
            code = self.mod.main()

        self.assertEqual(code, 0)
        header = "\n".join(printed[:6])
        self.assertIn("2", header)
        self.assertIn(NEW, header)
        self.assertIn("dry run", header.lower())


if __name__ == "__main__":
    unittest.main()
