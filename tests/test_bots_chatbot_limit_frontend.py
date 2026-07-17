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
        self.assertIn("const limitReached = isChatbotLimitReached();", apply_fn)
        self.assertIn("const blocked = loading || limitReached;", apply_fn)
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
        self.assertIn("const blocked = loading || limitReached;", apply_fn)

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

    def test_create_bot_limit_is_tab_independent(self):
        self.assertIn("let currentBotView = \"active\";", self.html)
        self.assertIn("function canCreateChatbot()", self.html)
        can_create_fn = re.search(
            r"function canCreateChatbot\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertNotIn("currentBotView", can_create_fn)
        self.assertIn("chatbotEntitlement.loaded", can_create_fn)
        self.assertIn("!isChatbotLimitReached()", can_create_fn)

    def test_switching_tabs_reapplies_create_bot_limit_state(self):
        set_view_fn = re.search(
            r"function setBotView\(view\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("updateBotViewTabs();", set_view_fn)
        self.assertIn("applyChatbotLimitState();", set_view_fn)
        self.assertIn("fetchBots();", set_view_fn)

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

    def test_open_create_modal_guard_does_not_depend_on_tab(self):
        open_fn = re.search(
            r"function openCreateModal\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("if (!canCreateChatbot())", open_fn)
        self.assertNotIn("currentBotView", open_fn)

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

    def test_create_submit_guard_does_not_depend_on_tab(self):
        create_fn = re.search(
            r"async function createBot\(\) \{.*?const botName =",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("if (!canCreateChatbot())", create_fn)
        self.assertNotIn("currentBotView", create_fn)

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
        apply_fn = re.search(
            r"function applyChatbotLimitState\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn('helper.style.display = limitReached ? "block" : "none";', apply_fn)

    def test_helper_message_appears_at_limit(self):
        self.assertIn('id="chatbot-limit-helper"', self.html)
        apply_fn = re.search(
            r"function applyChatbotLimitState\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn('helper.textContent = limitReached ? getChatbotLimitMessage() : "";', apply_fn)
        self.assertIn('helper.style.display = limitReached ? "block" : "none";', apply_fn)

    def test_helper_message_hidden_below_limit(self):
        apply_fn = re.search(
            r"function applyChatbotLimitState\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn('helper.textContent = limitReached ? getChatbotLimitMessage() : "";', apply_fn)
        self.assertIn('helper.style.display = limitReached ? "block" : "none";', apply_fn)

    def test_archived_empty_view_reapplies_create_bot_limit_state(self):
        fetch_fn = re.search(
            r"async function fetchBots\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        archived_empty = fetch_fn.split('if (currentBotView === "archived")', 1)[1].split("return;", 1)[0]
        self.assertIn("applyChatbotLimitState();", archived_empty)

    def test_edit_delete_actions_remain_unaffected(self):
        self.assertIn('class="action-btn edit-btn"', self.html)
        self.assertIn('class="action-btn delete-btn"', self.html)
        self.assertIn("openEditBot(botId);", self.html)
        self.assertIn("deleteBot(botId);", self.html)
        self.assertNotIn('edit-btn" data-create-bot-trigger', self.html)
        self.assertNotIn('delete-btn" data-create-bot-trigger', self.html)

    def test_delete_refresh_path_updates_limit_state(self):
        delete_success = re.search(
            r'if \(result.status === "success"\) \{.*?closeDeleteModal\(\);.*?\}',
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("await loadChatbotUsage();", delete_success)
        self.assertIn("applyChatbotLimitState();", delete_success)
        self.assertIn("fetchBots();", delete_success)

    def test_limit_message_matches_expected_copy(self):
        self.assertIn(
            "Chatbot limit reached. Archive an existing bot or upgrade your plan to create more bots.",
            self.html,
        )

    def test_bot_remove_ui_uses_archive_wording(self):
        self.assertIn("<h2>Archive Bot</h2>", self.html)
        self.assertIn("Archive this bot and remove it from active use?", self.html)
        self.assertIn("will be preserved", self.html)
        self.assertIn(">Archive Bot</button>", self.html)
        self.assertIn("> Archive", self.html)
        self.assertIn("Failed to archive bot", self.html)

    def test_includes_active_archived_view_toggle(self):
        self.assertIn('id="active-bots-tab"', self.html)
        self.assertIn('id="archived-bots-tab"', self.html)
        self.assertIn("function setBotView(view)", self.html)
        self.assertIn('setBotView(\'active\')', self.html)
        self.assertIn('setBotView(\'archived\')', self.html)

    def test_archived_view_loads_archived_endpoint(self):
        fetch_fn = re.search(
            r"async function fetchBots\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn('currentBotView === "archived" ? "/api/bots/archived" : "/api/bots"', fetch_fn)
        self.assertIn('renderBotCard(bot, currentBotView === "archived")', fetch_fn)

    def test_archived_cards_show_restore_and_permanent_delete(self):
        render_fn = re.search(
            r"function renderBotCard\(bot, archived\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn('class="action-btn restore-btn"', render_fn)
        self.assertIn("> Restore", render_fn)
        self.assertIn('class="action-btn permanent-delete-btn"', render_fn)
        self.assertIn("> Permanently Delete", render_fn)
        archived_branch = render_fn.split(": `", 1)[0]
        self.assertIn("restore-btn", archived_branch)
        self.assertIn("permanent-delete-btn", archived_branch)
        self.assertNotIn("edit-btn", archived_branch)
        self.assertNotIn('class="action-btn delete-btn"', archived_branch)

    def test_active_cards_do_not_show_permanent_delete(self):
        render_fn = re.search(
            r"function renderBotCard\(bot, archived\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        active_branch = render_fn.split(": `", 1)[1]
        self.assertIn("edit-btn", active_branch)
        self.assertIn("delete-btn", active_branch)
        self.assertNotIn("permanent-delete-btn", active_branch)

    def test_restore_refreshes_usage_and_active_list(self):
        restore_fn = re.search(
            r"async function restoreBot\(botId\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn('authenticatedFetch(`/api/bots/${botId}/restore`', restore_fn)
        self.assertIn('method: "POST"', restore_fn)
        self.assertIn("await loadChatbotUsage();", restore_fn)
        self.assertIn('currentBotView = "active";', restore_fn)
        self.assertIn("applyChatbotLimitState();", restore_fn)
        self.assertIn("fetchBots();", restore_fn)

    def test_restore_limit_error_message_is_handled(self):
        self.assertIn(
            "Chatbot limit reached. Archive another active bot or upgrade your plan before restoring this bot.",
            self.html,
        )
        restore_fn = re.search(
            r"async function restoreBot\(botId\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn('result.code === "chatbot_limit"', restore_fn)
        self.assertIn("alert(getRestoreLimitMessage());", restore_fn)

    def test_permanent_delete_modal_requires_exact_bot_name(self):
        self.assertIn('id="permanent-delete-modal"', self.html)
        self.assertIn("This permanently deletes the bot. This cannot be undone.", self.html)
        self.assertIn("Related data may be removed, including knowledge files, conversations, messages", self.html)
        self.assertIn('id="permanent-delete-confirm-name"', self.html)
        self.assertIn('id="permanent-delete-error"', self.html)
        self.assertIn("Type the exact bot name to permanently delete this bot.", self.html)
        self.assertIn('id="permanent-delete-confirm-btn"', self.html)
        self.assertIn("disabled>Permanently Delete</button>", self.html)
        self.assertIn("function validatePermanentDeleteName(showErrorWhenInvalid = false)", self.html)
        self.assertIn("function isPermanentDeleteNameExactMatch()", self.html)
        self.assertIn("getPermanentDeleteTypedName() === selectedPermanentDeleteBotName", self.html)
        self.assertIn("input.value.trim()", self.html)
        self.assertIn("setupPermanentDeleteConfirmation();", self.html)

    def test_permanent_delete_wrong_or_empty_confirmation_shows_inline_error(self):
        delete_fn = re.search(
            r"async function confirmPermanentDeleteBot\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        invalid_branch = re.search(
            r"if \(!validatePermanentDeleteName\(true\)\) \{(?P<body>.*?)return;",
            delete_fn,
            flags=re.S,
        ).group("body")
        self.assertIn("showPermanentDeleteError();", invalid_branch)
        self.assertNotIn("alert(", invalid_branch)

    def test_permanent_delete_button_state_uses_trimmed_exact_case_sensitive_match(self):
        match_fn = re.search(
            r"function isPermanentDeleteNameExactMatch\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        state_fn = re.search(
            r"function updatePermanentDeleteButtonState\(showErrorWhenInvalid\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("input.value.trim()", self.html)
        self.assertIn("getPermanentDeleteTypedName() === selectedPermanentDeleteBotName", match_fn)
        self.assertNotIn(".toLowerCase()", match_fn)
        self.assertIn("const matches = isPermanentDeleteNameExactMatch();", state_fn)
        self.assertIn("button.disabled = !matches", state_fn)
        self.assertIn("hidePermanentDeleteError();", state_fn)

    def test_permanent_delete_input_event_updates_button_and_error(self):
        setup_fn = re.search(
            r"function setupPermanentDeleteConfirmation\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn('input.addEventListener("input"', setup_fn)
        self.assertIn("permanentDeleteConfirmationTouched = true;", setup_fn)
        self.assertIn("updatePermanentDeleteButtonState(true);", setup_fn)

    def test_permanent_delete_modal_open_close_resets_error(self):
        open_fn = re.search(
            r"function openPermanentDeleteModal\(botId, botName\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        close_fn = re.search(
            r"function closePermanentDeleteModal\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        reset_fn = re.search(
            r"function resetPermanentDeleteConfirmation\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("selectedPermanentDeleteBotName = botName || \"\";", open_fn)
        self.assertIn("resetPermanentDeleteConfirmation();", open_fn)
        self.assertIn("resetPermanentDeleteConfirmation();", close_fn)
        self.assertIn('input.value = "";', reset_fn)
        self.assertIn("button.disabled = true;", reset_fn)
        self.assertIn("hidePermanentDeleteError();", reset_fn)
        self.assertIn("permanentDeleteConfirmationTouched = false;", reset_fn)

    def test_permanent_delete_invalid_confirmation_does_not_call_api(self):
        delete_fn = re.search(
            r"async function confirmPermanentDeleteBot\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertLess(
            delete_fn.index("if (!validatePermanentDeleteName(true))"),
            delete_fn.index("authenticatedFetch"),
        )
        self.assertLess(
            delete_fn.index("return;"),
            delete_fn.index("authenticatedFetch"),
        )

    def test_permanent_delete_posts_confirmation_and_refreshes(self):
        delete_fn = re.search(
            r"async function confirmPermanentDeleteBot\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("permanentDeleteConfirmationTouched = true;", delete_fn)
        self.assertIn("if (!validatePermanentDeleteName(true))", delete_fn)
        self.assertIn('authenticatedFetch(`/api/bots/${selectedPermanentDeleteBotId}/permanent`', delete_fn)
        self.assertIn('method: "DELETE"', delete_fn)
        self.assertIn("confirm_bot_name", delete_fn)
        self.assertIn("confirm_bot_name: getPermanentDeleteTypedName()", delete_fn)
        self.assertIn("closePermanentDeleteModal();", delete_fn)
        self.assertIn("await loadChatbotUsage();", delete_fn)
        self.assertIn("applyChatbotLimitState();", delete_fn)
        self.assertIn("fetchBots();", delete_fn)


if __name__ == "__main__":
    unittest.main()
