"""Tests for the website chat widget (embed script, iframe, share link).

Covers the security-sensitive surface: public-key resolution, the domain
allowlist, per-session message caps, input validation, and the guarantee
that internal fields never leak through the public config endpoint.
"""

import unittest
from unittest.mock import MagicMock, patch

from app.services import web_widget_service as svc


def make_widget(**overrides):
    widget = {
        "id": 1,
        "chatbot_id": 42,
        "company_id": 7,
        "public_key": "wgt_testkey",
        "is_enabled": True,
        "allowed_domains": [],
        "display_name": "Acme Support",
        "subtitle": "We reply fast",
        "primary_color": "#4F46E5",
        "text_color": "#FFFFFF",
        "avatar_url": None,
        "launcher_position": "right",
        "launcher_label": "",
        "welcome_message": "Hi there!",
        "input_placeholder": "Type your message...",
        "suggested_questions": [],
        "show_branding": True,
        "branding_text": "Powered by AI",
        "collect_lead": False,
        "lead_prompt": "May I have your details?",
        "lead_require_name": True,
        "lead_require_email": True,
        "lead_require_phone": False,
        "max_messages_per_session": 50,
    }
    widget.update(overrides)
    return widget


# ── Key + session generation ──────────────────────────────────────────

class TestKeyGeneration(unittest.TestCase):

    def test_public_keys_are_prefixed_and_unique(self):
        keys = {svc.generate_public_key() for _ in range(50)}
        self.assertEqual(len(keys), 50, "public keys must not collide")
        for key in keys:
            self.assertTrue(key.startswith("wgt_"))
            self.assertGreater(len(key), 20)

    def test_generated_session_ids_pass_validation(self):
        for _ in range(20):
            session_id = svc.generate_session_id()
            self.assertEqual(svc.validate_session_id(session_id), session_id)

    def test_rejects_forged_session_ids(self):
        for bad in ("", "abc", "web_short", "../../etc/passwd",
                    "web_" + "x" * 200, "telegram_12345"):
            with self.assertRaises(svc.WidgetError):
                svc.validate_session_id(bad)


# ── Domain allowlist ──────────────────────────────────────────────────

class TestOriginAllowlist(unittest.TestCase):

    def test_empty_allowlist_permits_any_origin(self):
        widget = make_widget(allowed_domains=[])
        self.assertTrue(svc.is_origin_allowed(widget, "https://anything.test"))

    def test_exact_hostname_match(self):
        widget = make_widget(allowed_domains=["example.com"])
        self.assertTrue(svc.is_origin_allowed(widget, "https://example.com"))
        self.assertTrue(svc.is_origin_allowed(widget, "http://example.com:8080/page"))

    def test_subdomains_are_allowed(self):
        widget = make_widget(allowed_domains=["example.com"])
        self.assertTrue(svc.is_origin_allowed(widget, "https://shop.example.com"))

    def test_unrelated_domain_is_rejected(self):
        widget = make_widget(allowed_domains=["example.com"])
        self.assertFalse(svc.is_origin_allowed(widget, "https://evil.test"))

    def test_suffix_lookalike_is_rejected(self):
        """notexample.com must not satisfy an example.com allowlist."""
        widget = make_widget(allowed_domains=["example.com"])
        self.assertFalse(svc.is_origin_allowed(widget, "https://notexample.com"))

    def test_missing_origin_allows_direct_share_link(self):
        widget = make_widget(allowed_domains=["example.com"])
        self.assertTrue(svc.is_origin_allowed(widget, None))


# ── Public config exposure ────────────────────────────────────────────

class TestPublicConfig(unittest.TestCase):

    def test_internal_fields_are_never_exposed(self):
        config = svc.public_config(make_widget())
        for leaked in ("chatbot_id", "company_id", "allowed_domains", "id"):
            self.assertNotIn(leaked, config)

    def test_appearance_fields_are_exposed(self):
        config = svc.public_config(make_widget(display_name="Acme Support"))
        self.assertEqual(config["display_name"], "Acme Support")
        self.assertEqual(config["public_key"], "wgt_testkey")


# ── Widget resolution ─────────────────────────────────────────────────

class TestResolvePublicWidget(unittest.TestCase):

    def test_unknown_key_raises_404(self):
        with patch.object(svc, "get_widget_by_public_key", return_value=None):
            with self.assertRaises(svc.WidgetError) as ctx:
                svc.resolve_public_widget("wgt_missing")
        self.assertEqual(ctx.exception.status, 404)

    def test_disabled_widget_raises_403(self):
        widget = make_widget(is_enabled=False)
        with patch.object(svc, "get_widget_by_public_key", return_value=widget):
            with self.assertRaises(svc.WidgetError) as ctx:
                svc.resolve_public_widget("wgt_testkey")
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.code, "widget_disabled")

    def test_inactive_chatbot_raises_403(self):
        widget = make_widget()
        with patch.object(svc, "get_widget_by_public_key", return_value=widget), \
                patch.object(svc, "get_bot_by_id", return_value={"is_active": False}):
            with self.assertRaises(svc.WidgetError) as ctx:
                svc.resolve_public_widget("wgt_testkey")
        self.assertEqual(ctx.exception.code, "chatbot_inactive")

    def test_enabled_widget_with_active_bot_resolves(self):
        widget = make_widget()
        bot = {"id": 42, "is_active": True}
        with patch.object(svc, "get_widget_by_public_key", return_value=widget), \
                patch.object(svc, "get_bot_by_id", return_value=bot):
            resolved_widget, resolved_bot = svc.resolve_public_widget("wgt_testkey")
        self.assertEqual(resolved_widget["chatbot_id"], 42)
        self.assertEqual(resolved_bot, bot)


# ── Session quota (AI credit abuse guard) ─────────────────────────────

class TestSessionQuota(unittest.TestCase):

    def test_allows_messages_below_the_cap(self):
        widget = make_widget(max_messages_per_session=10)
        with patch.object(svc, "count_messages_by_conversation", return_value=3):
            self.assertEqual(svc.assert_session_quota(widget, 99), 7)

    def test_blocks_at_the_cap(self):
        widget = make_widget(max_messages_per_session=10)
        with patch.object(svc, "count_messages_by_conversation", return_value=10):
            with self.assertRaises(svc.WidgetError) as ctx:
                svc.assert_session_quota(widget, 99)
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(ctx.exception.code, "session_limit_reached")


# ── Message validation ────────────────────────────────────────────────

class TestMessageValidation(unittest.TestCase):

    def test_trims_whitespace(self):
        self.assertEqual(svc.normalise_incoming_message("  hello  "), "hello")

    def test_rejects_empty_messages(self):
        for bad in ("", "   ", None):
            with self.assertRaises(svc.WidgetError):
                svc.normalise_incoming_message(bad)

    def test_rejects_oversized_messages(self):
        with self.assertRaises(svc.WidgetError) as ctx:
            svc.normalise_incoming_message("x" * (svc.MAX_MESSAGE_LENGTH + 1))
        self.assertEqual(ctx.exception.code, "message_too_long")


# ── Settings validation ───────────────────────────────────────────────

class TestUpdateWidgetSettings(unittest.TestCase):

    def setUp(self):
        self.widget = make_widget()
        self.ensure = patch.object(svc, "ensure_widget", return_value=self.widget)
        self.ensure.start()
        self.addCleanup(self.ensure.stop)

    def _update(self, payload):
        captured = {}

        def fake_update(chatbot_id, company_id, data):
            captured.update(data)
            return {**self.widget, **data}

        with patch.object(svc, "update_widget", side_effect=fake_update):
            svc.update_widget_settings(42, 7, payload)

        return captured

    def test_rejects_invalid_hex_colour(self):
        for bad in ("red", "#12", "4F46E5", "#GGGGGG", ""):
            with self.assertRaises(svc.WidgetError):
                self._update({"primary_color": bad})

    def test_accepts_and_uppercases_valid_colour(self):
        self.assertEqual(self._update({"primary_color": "#4f46e5"})["primary_color"],
                         "#4F46E5")

    def test_rejects_invalid_launcher_position(self):
        with self.assertRaises(svc.WidgetError):
            self._update({"launcher_position": "top"})

    def test_rejects_javascript_avatar_url(self):
        with self.assertRaises(svc.WidgetError):
            self._update({"avatar_url": "javascript:alert(1)"})

    def test_clamps_message_cap(self):
        for bad in (0, 501, -5, "many"):
            with self.assertRaises(svc.WidgetError):
                self._update({"max_messages_per_session": bad})

    def test_truncates_overlong_text(self):
        result = self._update({"display_name": "A" * 500})
        self.assertEqual(len(result["display_name"]), 80)

    def test_normalises_domains_to_bare_hostnames(self):
        result = self._update({
            "allowed_domains": ["https://Example.com/path", " shop.example.com ", ""]
        })
        self.assertEqual(result["allowed_domains"],
                         ["example.com", "shop.example.com"])

    def test_caps_suggested_questions(self):
        result = self._update({"suggested_questions": [f"Q{i}" for i in range(20)]})
        self.assertEqual(len(result["suggested_questions"]),
                         svc.MAX_SUGGESTED_QUESTIONS)

    def test_rejects_empty_payload(self):
        with self.assertRaises(svc.WidgetError):
            self._update({"unknown_field": "x"})


# ── Lead capture ──────────────────────────────────────────────────────

class TestLeadCapture(unittest.TestCase):

    def test_enforces_required_fields(self):
        widget = make_widget(lead_require_name=True, lead_require_email=True)
        with self.assertRaises(svc.WidgetError):
            svc.capture_lead(widget, {"id": 1}, {"email": "a@b.com"})
        with self.assertRaises(svc.WidgetError):
            svc.capture_lead(widget, {"id": 1}, {"name": "Ann"})

    def test_rejects_malformed_email(self):
        widget = make_widget(lead_require_name=False, lead_require_email=True)
        with self.assertRaises(svc.WidgetError) as ctx:
            svc.capture_lead(widget, {"id": 1}, {"email": "not-an-email"})
        self.assertEqual(ctx.exception.code, "invalid_email")

    def test_creates_crm_lead_on_the_web_channel(self):
        widget = make_widget(lead_require_phone=False)
        with patch.object(svc, "create_crm_lead",
                          return_value={"id": 5}) as mock_create:
            svc.capture_lead(
                widget,
                {"id": 11},
                {"name": "Ann", "email": "ann@example.com"},
            )

        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs["source_channel"], "web")
        self.assertEqual(kwargs["company_id"], 7)
        self.assertEqual(kwargs["chatbot_id"], 42)
        self.assertEqual(kwargs["conversation_id"], 11)

    def test_duplicate_lead_does_not_raise(self):
        widget = make_widget()
        with patch.object(svc, "create_crm_lead",
                          side_effect=Exception("duplicate key")):
            self.assertIsNone(
                svc.capture_lead(
                    widget, {"id": 11},
                    {"name": "Ann", "email": "ann@example.com"},
                )
            )


# ── Conversation wiring ───────────────────────────────────────────────

class TestConversationWiring(unittest.TestCase):

    def test_opens_conversation_on_the_web_channel(self):
        widget = make_widget()
        with patch.object(svc, "get_or_create_platform_conversation",
                          return_value={"id": 3}) as mock_open:
            svc.open_conversation(widget, "web_abcdefghijklmnop")

        kwargs = mock_open.call_args.kwargs
        self.assertEqual(kwargs["source_channel"], "web")
        self.assertEqual(kwargs["chatbot_id"], 42)
        self.assertEqual(kwargs["platform_user_id"], "web_abcdefghijklmnop")


if __name__ == "__main__":
    unittest.main()
