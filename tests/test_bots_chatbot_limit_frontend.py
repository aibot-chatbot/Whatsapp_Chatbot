"""Focused frontend regressions for My Bots chatbot-limit UI."""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOTS_HTML = ROOT / "frontend" / "bots.html"


class TestBotsChatbotLimitFrontend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = BOTS_HTML.read_text(encoding="utf-8", errors="replace")

    def test_loads_chatbot_usage_from_billing_usage_endpoint(self):
        self.assertIn('authenticatedFetch("/api/billing/usage")', self.html)
        self.assertIn("result.data.usage.chatbots", self.html)
        self.assertIn("chatbots.used", self.html)
        self.assertIn("chatbots.limit", self.html)

    def test_create_bot_remains_enabled_below_limit(self):
        apply_fn = re.search(
            r"function applyChatbotLimitState\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("const loading = !chatbotEntitlement.loaded;", apply_fn)
        self.assertIn("const blocked = loading || isChatbotLimitReached();", apply_fn)
        self.assertIn("button.disabled = blocked;", apply_fn)
        self.assertIn('button.title = loading ? "Checking chatbot limit..." : (blocked ? getChatbotLimitMessage() : "Create Bot");', apply_fn)

    def test_create_bot_is_disabled_while_entitlement_not_loaded(self):
        self.assertIn('data-create-bot-trigger="true" disabled title="Checking chatbot limit..."', self.html)
        apply_fn = re.search(
            r"function applyChatbotLimitState\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("const loading = !chatbotEntitlement.loaded;", apply_fn)
        self.assertIn("const blocked = loading || isChatbotLimitReached();", apply_fn)

    def test_create_bot_is_disabled_at_limit(self):
        limit_fn = re.search(
            r"function isChatbotLimitReached\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("chatbotEntitlement.limit === null", limit_fn)
        self.assertIn("return false;", limit_fn)
        self.assertIn("return chatbotEntitlement.used >= chatbotEntitlement.limit;", limit_fn)
        self.assertIn('data-create-bot-trigger="true"', self.html)
        self.assertIn("function canCreateChatbot()", self.html)
        self.assertIn("return chatbotEntitlement.loaded && !isChatbotLimitReached();", self.html)

    def test_open_create_modal_is_blocked_at_limit(self):
        open_fn = re.search(
            r"function openCreateModal\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("if (!canCreateChatbot())", open_fn)
        self.assertIn('alert(chatbotEntitlement.loaded ? getChatbotLimitMessage() : "Checking chatbot limit. Please try again in a moment.");', open_fn)
        self.assertIn("return;", open_fn)
        self.assertIn("create-modal", open_fn)

    def test_open_create_modal_is_blocked_while_entitlement_not_loaded(self):
        open_fn = re.search(
            r"function openCreateModal\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("if (!canCreateChatbot())", open_fn)
        self.assertIn("Checking chatbot limit. Please try again in a moment.", open_fn)

    def test_create_submit_is_blocked_at_limit(self):
        create_fn = re.search(
            r"async function createBot\(\) \{.*?const botName =",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("if (!canCreateChatbot())", create_fn)
        self.assertIn('alert(chatbotEntitlement.loaded ? getChatbotLimitMessage() : "Checking chatbot limit. Please try again in a moment.");', create_fn)
        self.assertIn("return;", create_fn)

    def test_create_submit_is_blocked_while_entitlement_not_loaded(self):
        create_fn = re.search(
            r"async function createBot\(\) \{.*?const botName =",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("if (!canCreateChatbot())", create_fn)
        self.assertIn("Checking chatbot limit. Please try again in a moment.", create_fn)
        self.assertIn("return;", create_fn)

    def test_unlimited_plans_are_not_blocked(self):
        load_fn = re.search(
            r"async function loadChatbotUsage\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("rawLimit === null || rawLimit === undefined ? null : Number(rawLimit)", load_fn)
        self.assertIn("limit: limit !== null && Number.isFinite(limit) ? limit : null", load_fn)

    def test_edit_delete_actions_remain_unaffected(self):
        self.assertIn('class="action-btn edit-btn"', self.html)
        self.assertIn('class="action-btn delete-btn"', self.html)
        self.assertIn("openEditBot(botId);", self.html)
        self.assertIn("deleteBot(botId);", self.html)
        self.assertNotIn('edit-btn" data-create-bot-trigger', self.html)
        self.assertNotIn('delete-btn" data-create-bot-trigger', self.html)

    def test_limit_message_matches_expected_copy(self):
        self.assertIn(
            "Chatbot limit reached. Delete an existing bot or upgrade your plan.",
            self.html,
        )


if __name__ == "__main__":
    unittest.main()
