"""Regressions for the single source of truth for a bot's tone.

Two tone columns existed: ``chatbots.tone``, written by the bot list page and
read by nothing at runtime, and ``bot_configs.tone``, which is the value the
reply pipeline renders into the prompt. The bot list now shows the second one
and the first is no longer written from the UI.
"""

import unittest
from unittest.mock import patch

from tests.frontend_pages import WEB_PUBLIC_JS, page_source_path


class _Response:
    def __init__(self, data=None):
        self.data = data if data is not None else []


class _Query:
    """Minimal PostgREST-style chain recorder."""

    def __init__(self, response=None):
        self.response = response or _Response()
        self.table_name = None
        self.select_columns = None
        self.in_calls = []

    def table(self, table_name):
        self.table_name = table_name
        return self

    def select(self, columns="*", *args, **kwargs):
        self.select_columns = columns
        return self

    def in_(self, field, values):
        self.in_calls.append((field, list(values)))
        return self

    def eq(self, *args, **kwargs):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def execute(self):
        return self.response


class TestGetTonesForChatbots(unittest.TestCase):
    def test_deployed_profile_tone_wins_over_the_active_profile(self):
        from app.services import profile_service

        rows = [
            {"chatbot_id": 1, "profile_name": "Live", "is_active": False, "tone": "Formal"},
            {"chatbot_id": 1, "profile_name": "Draft", "is_active": True, "tone": "Friendly"},
        ]
        query = _Query(_Response(rows))

        with patch.object(profile_service, "supabase", query):
            tones = profile_service.get_tones_for_chatbots([1], {1: "Live"})

        # The deployed profile is the row the reply pipeline reads, so it is
        # the one the card must show.
        self.assertEqual(tones, {1: "Formal"})
        self.assertEqual(query.table_name, "bot_configs")
        self.assertEqual(query.in_calls, [("chatbot_id", [1])])

    def test_active_profile_is_used_when_nothing_is_deployed(self):
        from app.services import profile_service

        rows = [
            {"chatbot_id": 2, "profile_name": "Draft", "is_active": True, "tone": "Professional"},
            {"chatbot_id": 2, "profile_name": "Old", "is_active": False, "tone": "Formal"},
        ]
        query = _Query(_Response(rows))

        with patch.object(profile_service, "supabase", query):
            tones = profile_service.get_tones_for_chatbots([2], {2: ""})

        self.assertEqual(tones, {2: "Professional"})

    def test_legacy_response_style_column_is_still_resolved(self):
        from app.services import profile_service

        rows = [{"chatbot_id": 3, "profile_name": "Draft", "is_active": True,
                 "tone": "", "response_style": "Friendly"}]
        query = _Query(_Response(rows))

        with patch.object(profile_service, "supabase", query):
            tones = profile_service.get_tones_for_chatbots([3])

        self.assertEqual(tones, {3: "Friendly"})

    def test_bot_without_a_profile_reports_an_empty_tone(self):
        from app.services import profile_service

        query = _Query(_Response([]))

        with patch.object(profile_service, "supabase", query):
            tones = profile_service.get_tones_for_chatbots([4, 5])

        self.assertEqual(tones, {4: "", 5: ""})

    def test_no_query_is_issued_for_an_empty_bot_list(self):
        from app.services import profile_service

        query = _Query(_Response([{"chatbot_id": 1, "tone": "Formal"}]))

        with patch.object(profile_service, "supabase", query):
            tones = profile_service.get_tones_for_chatbots([])

        self.assertEqual(tones, {})
        self.assertIsNone(query.table_name)


class TestBotServiceAttachesConfigTone(unittest.TestCase):
    def test_list_bots_resolves_every_tone_in_one_query(self):
        from app.services import bot_service

        bots = [
            {"id": 1, "bot_name": "Alpha", "tone": "Formal", "deployed_profile_name": "Live"},
            {"id": 2, "bot_name": "Beta", "tone": "Formal", "deployed_profile_name": ""},
        ]

        with patch.object(bot_service, "get_all_bots", return_value=bots), \
            patch.object(
                bot_service, "get_tones_for_chatbots", return_value={1: "Friendly", 2: ""},
            ) as mock_tones:
            result = bot_service.list_bots(42)

        # One batched call for the whole page, not one per bot.
        mock_tones.assert_called_once_with([1, 2], {1: "Live", 2: ""})
        self.assertEqual(result[0]["config_tone"], "Friendly")
        self.assertEqual(result[1]["config_tone"], "")
        # The legacy column is untouched, not rewritten from the new value.
        self.assertEqual(result[0]["tone"], "Formal")
        self.assertNotIn("config_tone", bots[0])

    def test_get_bot_attaches_the_config_tone(self):
        from app.services import bot_service

        with patch.object(
            bot_service,
            "get_bot_by_id",
            return_value={"id": 8, "bot_name": "Alpha", "deployed_profile_name": ""},
        ), patch.object(bot_service, "get_tones_for_chatbots", return_value={8: "Professional"}):
            bot = bot_service.get_bot(8, 42)

        self.assertEqual(bot["config_tone"], "Professional")

    def test_tone_lookup_failure_does_not_break_the_bot_list(self):
        from app.services import bot_service

        with patch.object(
            bot_service, "get_all_bots", return_value=[{"id": 1, "bot_name": "Alpha"}],
        ), patch.object(
            bot_service, "get_tones_for_chatbots", side_effect=Exception("bot_configs unavailable"),
        ):
            result = bot_service.list_bots(42)

        self.assertEqual(result[0]["config_tone"], "")


class TestBotsApiExposesConfigTone(unittest.TestCase):
    def setUp(self):
        from app import create_app

        app = create_app()
        app.config["TESTING"] = True
        self.app = app
        self.client = app.test_client()

    def _patch_auth(self):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 42, "user_id": 1, "role": "admin"},
        )

    def _patch_user(self):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value={
                "id": 1,
                "email": "owner@example.com",
                "status": "active",
                "role": "admin",
                "company_id": 42,
            },
        )

    def test_bot_list_endpoint_returns_the_bot_configs_tone(self):
        from app.services import bot_service

        with self._patch_auth(), self._patch_user(), \
            patch.object(
                bot_service,
                "get_all_bots",
                return_value=[{"id": 8, "bot_name": "Alpha", "deployed_profile_name": ""}],
            ), \
            patch.object(bot_service, "get_tones_for_chatbots", return_value={8: "Professional"}):
            response = self.client.get(
                "/api/bots",
                headers={"Authorization": "Bearer token"},
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["data"][0]["config_tone"], "Professional")

    def test_single_bot_endpoint_returns_the_bot_configs_tone(self):
        from app.services import bot_service

        with self._patch_auth(), self._patch_user(), \
            patch.object(
                bot_service,
                "get_bot_by_id",
                return_value={"id": 8, "bot_name": "Alpha", "deployed_profile_name": ""},
            ), \
            patch.object(bot_service, "get_tones_for_chatbots", return_value={8: "Formal"}):
            response = self.client.get(
                "/api/bots/8",
                headers={"Authorization": "Bearer token"},
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["data"]["config_tone"], "Formal")


class TestBotsPageDropsTheSecondToneControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        markup = page_source_path("bots.html").read_text(encoding="utf-8")
        cls.html = markup + (WEB_PUBLIC_JS / "bots.js").read_text(encoding="utf-8")

    def test_tone_select_is_gone(self):
        self.assertNotIn('id="bot-tone"', self.html)
        self.assertNotIn('getElementById("bot-tone")', self.html)

    def test_bot_creation_and_update_no_longer_send_tone(self):
        self.assertNotIn("tone: botTone", self.html)

    def test_card_meta_shows_the_authoritative_tone(self):
        self.assertIn('escapeHtml(bot.config_tone || "Tone not set")', self.html)


if __name__ == "__main__":
    unittest.main()
