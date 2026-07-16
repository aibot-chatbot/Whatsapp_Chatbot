"""Focused frontend regressions for Integration channel-limit UI."""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_HTML = ROOT / "frontend" / "integration.html"


class TestIntegrationChannelLimitFrontend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = INTEGRATION_HTML.read_text(encoding="utf-8", errors="replace")

    def test_loads_channel_usage_from_billing_usage_endpoint(self):
        self.assertIn("channelEntitlement", self.html)
        self.assertIn("authenticatedFetch('/api/billing/usage')", self.html)
        self.assertIn("result.data.usage.channels", self.html)
        self.assertIn("used: Number(channels.used || 0)", self.html)
        self.assertIn("limit: channels.limit === null", self.html)

    def test_disconnected_platform_disabled_when_usage_equals_limit(self):
        update_button = re.search(
            r"function updatePlatformButton\(platform, isConnected\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("const blocked = !isConnected && isChannelLimitReached();", update_button)
        self.assertIn("button.disabled = true;", update_button)
        self.assertIn("button.innerText = 'Channel Limit Reached';", update_button)

    def test_pending_whatsapp_connection_is_blocked_at_limit(self):
        self.assertIn("function shouldBlockNewChannel(platform)", self.html)
        self.assertIn("isChannelLimitReached() && !isChannelConnected(latestChannels[platform])", self.html)
        self.assertIn("if (shouldBlockNewChannel(platform))", self.html)
        self.assertIn("showChannelLimitNotice(platform);", self.html)
        self.assertIn("if (shouldBlockNewChannel('whatsapp'))", self.html)
        self.assertIn("setWhatsAppCloudState('error', getChannelLimitMessage());", self.html)

    def test_existing_connected_manage_buttons_remain_enabled_at_limit(self):
        self.assertIn("button.innerText = isConnected ? 'Manage Telegram' : 'Connect Telegram';", self.html)
        self.assertIn("button.innerText = isConnected ? 'Manage WhatsApp' : 'Connect WhatsApp';", self.html)
        self.assertIn("button.innerText = isConnected ? 'Manage WasenderAPI' : 'Connect WasenderAPI';", self.html)
        self.assertIn("const blocked = !isConnected && isChannelLimitReached();", self.html)
        self.assertIn("button.disabled = false;", self.html)

    def test_below_limit_connect_actions_remain_enabled(self):
        limit_fn = re.search(
            r"function isChannelLimitReached\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("return Number(channelEntitlement.used || 0) >= Number(channelEntitlement.limit);", limit_fn)
        self.assertIn("button.disabled = false;", self.html)
        self.assertIn("button.style.cursor = 'pointer';", self.html)

    def test_unlimited_channel_plans_are_not_blocked(self):
        limit_fn = re.search(
            r"function isChannelLimitReached\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("channelEntitlement.limit === null", limit_fn)
        self.assertIn("return false;", limit_fn)

    def test_channel_limit_message_matches_expected_copy(self):
        self.assertIn(
            "Channel limit reached (${channelEntitlement.used}/${channelEntitlement.limit}). Disconnect an existing channel or upgrade your plan.",
            self.html,
        )


if __name__ == "__main__":
    unittest.main()
