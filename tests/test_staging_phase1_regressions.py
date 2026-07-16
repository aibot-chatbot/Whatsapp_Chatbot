"""Focused regressions for Manual Staging Smoke Test Phase 1 defects."""

import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AI_ROUTER = ROOT / "app" / "services" / "ai_router.py"
BILLING_NOTIFICATIONS = ROOT / "app" / "services" / "billing_notification_service.py"
PROFILE_HTML = ROOT / "frontend" / "profile.html"
MODEL_SETTINGS_HTML = ROOT / "frontend" / "model_settings.html"
BUNDLED_NODE = (
    Path.home()
    / ".cache"
    / "codex-runtimes"
    / "codex-primary-runtime"
    / "dependencies"
    / "node"
    / "bin"
    / "node.exe"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


class TestAiCreditNotificationWording(unittest.TestCase):
    def setUp(self):
        self.router = _read(AI_ROUTER)
        self.notifications = _read(BILLING_NOTIFICATIONS)

    def test_trial_detection_falls_back_to_plan_id_lookup(self):
        self.assertIn("plan_code = (sub.get(\"plan_code\") or \"\").lower()", self.router)
        self.assertIn("plan_id = sub.get(\"plan_id\")", self.router)
        self.assertIn("plan = get_plan_by_id(plan_id)", self.router)
        self.assertIn("(plan.get(\"code\") or \"\").lower().strip() == \"free\"", self.router)

    def test_trial_critical_and_depleted_use_upgrade_wording(self):
        critical = re.search(
            r"def _ai_credit_critical_message\(.*?\n\n",
            self.notifications,
            flags=re.S,
        ).group(0)
        depleted = re.search(
            r"def _ai_credit_depleted_message\(.*?\n\n",
            self.notifications,
            flags=re.S,
        ).group(0)
        self.assertIn("Upgrade to a paid plan now", critical)
        self.assertIn("Upgrade to a paid plan to continue", depleted)

    def test_paid_critical_and_depleted_use_top_up_wording(self):
        self.assertIn("Top up immediately to prevent service interruption.", self.notifications)
        self.assertIn("AI-powered features will not work until you top up.", self.notifications)


class TestBillingNotificationTimestamp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _read(PROFILE_HTML)
        cls.node = shutil.which("node") or (str(BUNDLED_NODE) if BUNDLED_NODE.exists() else None)

    def _run_formatter(self, value):
        if not self.node:
            self.skipTest("Node.js is not available")
        match = re.search(
            r"function formatBillingNotificationTimestamp\(value\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        )
        self.assertIsNotNone(match, "formatter function not found")
        script = (
            match.group(0)
            + "\nconst value = process.argv[1];"
            + "\nconst result = formatBillingNotificationTimestamp(value === '__MISSING__' ? null : value);"
            + "\nif (result === 'Invalid Date') process.exit(2);"
            + "\nconsole.log(result);"
        )
        arg = "__MISSING__" if value is None else value
        completed = subprocess.run(
            [self.node, "-e", script, arg],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout.strip()

    def test_notification_timestamp_renders_valid_date(self):
        rendered = self._run_formatter("2026-07-16T12:34:56Z")
        self.assertTrue(rendered)
        self.assertNotEqual(rendered, "Invalid Date")

    def test_missing_or_malformed_timestamp_never_renders_invalid_date(self):
        self.assertEqual(self._run_formatter(None), "")
        self.assertEqual(self._run_formatter("not-a-date"), "")
        self.assertNotIn("new Date(n.created_at +", self.html)
        self.assertIn("formatBillingNotificationTimestamp(n.created_at)", self.html)


class TestModelSettingsAccessDeniedState(unittest.TestCase):
    def setUp(self):
        self.html = _read(MODEL_SETTINGS_HTML)

    def test_access_denied_message_for_403_or_404(self):
        self.assertIn("function showBotAccessDeniedState()", self.html)
        self.assertIn("Chatbot not found or you do not have access.", self.html)
        self.assertIn("response.status === 403 || response.status === 404", self.html)

    def test_controls_hidden_or_disabled_after_bot_load_failure(self):
        self.assertIn('id="configuration-card"', self.html)
        self.assertIn('card.style.display = "none"', self.html)
        self.assertIn("setConfigurationControlsDisabled(true)", self.html)
        for control_id in ("ai-provider", "model-select", "custom-model-name", "temperature", "save-btn"):
            self.assertIn(f'getElementById("{control_id}")', self.html)

    def test_save_request_is_guarded_after_bot_load_failure(self):
        guard_index = self.html.index("if (botLoadFailed)")
        put_index = self.html.index("method: \"PUT\"")
        self.assertLess(guard_index, put_index)
        self.assertIn("return;", self.html[guard_index:put_index])

    def test_authorized_model_settings_flow_still_present(self):
        self.assertIn('if (result.status === "success")', self.html)
        self.assertIn("const bot = result.data;", self.html)
        self.assertIn("onProviderChange(); // Populate model list", self.html)
        self.assertIn("window.dispatchEvent(new CustomEvent(\"recheckBotStatus\"));", self.html)


if __name__ == "__main__":
    unittest.main()
