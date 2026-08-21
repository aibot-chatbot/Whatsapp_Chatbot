"""The share link has to count as a published channel.

Before this, dashboard_health_service walked telegram, wasender and whatsapp
only. A tenant who published by share link saw "Connect a channel to reach
customers, Not connected" on the dashboard forever, while the publish page
told them the same bot was live. Two screens contradicting each other on the
same fact is worse than either being wrong on its own.
"""

import unittest
from unittest.mock import patch

from app.services import dashboard_health_service as svc


def widget(**overrides):
    row = {
        "id": 1,
        "chatbot_id": 42,
        "company_id": 7,
        "public_key": "wgt_testkey",
        "is_enabled": True,
        "display_name": "Northweave Clinic",
    }
    row.update(overrides)
    return row


def telegram(**overrides):
    row = {
        "id": 3,
        "chatbot_id": 42,
        "bot_username": "northweave_bot",
        "telegram_bot_id": "8123",
        "connection_status": "connected",
        "is_active": True,
        "last_error": None,
    }
    row.update(overrides)
    return row


class ChannelHealthBase(unittest.TestCase):
    def health(self, widget_row=None, telegram_rows=(), wasender_rows=(), whatsapp_rows=()):
        with patch.object(svc, "get_widget_by_chatbot_id", return_value=widget_row), \
             patch.object(svc, "get_telegram_channels_by_chatbot", return_value=list(telegram_rows)), \
             patch.object(svc, "get_wasender_channels_by_chatbot", return_value=list(wasender_rows)), \
             patch.object(svc, "get_whatsapp_channels_by_chatbot", return_value=list(whatsapp_rows)):
            return svc._get_channel_health(42, 7)


class TestWidgetCountsAsAChannel(ChannelHealthBase):
    def test_enabled_widget_is_a_connected_channel(self):
        result = self.health(widget_row=widget())

        self.assertEqual(result["connected_count"], 1)
        item = result["items"][0]
        self.assertEqual(item["type"], "widget")
        self.assertTrue(item["connected"])
        self.assertEqual(item["label"], "Northweave Clinic")

    def test_disabled_widget_is_present_but_not_connected(self):
        result = self.health(widget_row=widget(is_enabled=False))

        self.assertEqual(result["connected_count"], 0)
        self.assertEqual(result["items"][0]["type"], "widget")
        self.assertFalse(result["items"][0]["connected"])
        self.assertEqual(result["items"][0]["status"], "disabled")

    def test_missing_widget_adds_no_item(self):
        result = self.health(widget_row=None)

        self.assertEqual(result["items"], [])
        self.assertEqual(result["connected_count"], 0)

    def test_widget_without_a_name_still_has_a_label(self):
        result = self.health(widget_row=widget(display_name=None))
        self.assertEqual(result["items"][0]["label"], "Share link")

    def test_widget_is_counted_alongside_the_other_channels(self):
        result = self.health(widget_row=widget(), telegram_rows=[telegram()])

        self.assertEqual(result["connected_count"], 2)
        self.assertEqual([i["type"] for i in result["items"]], ["widget", "telegram"])

    def test_a_widget_only_bot_clears_the_no_channel_warning(self):
        """The dashboard's onboarding step reads connected_count directly."""
        result = self.health(widget_row=widget())
        self.assertGreater(result["connected_count"], 0)

    def test_widget_never_reports_an_error_string(self):
        # There is no vendor to fail against; we host it.
        result = self.health(widget_row=widget(is_enabled=False))
        self.assertIsNone(result["items"][0]["last_error"])

    def test_company_id_is_passed_through_for_tenancy(self):
        with patch.object(svc, "get_widget_by_chatbot_id", return_value=None) as lookup, \
             patch.object(svc, "get_telegram_channels_by_chatbot", return_value=[]), \
             patch.object(svc, "get_wasender_channels_by_chatbot", return_value=[]), \
             patch.object(svc, "get_whatsapp_channels_by_chatbot", return_value=[]):
            svc._get_channel_health(42, 7)

        lookup.assert_called_once_with(42, 7)


class TestExistingChannelsAreUnchanged(ChannelHealthBase):
    def test_connected_telegram_still_counts(self):
        result = self.health(telegram_rows=[telegram()])
        self.assertEqual(result["connected_count"], 1)
        self.assertEqual(result["items"][0]["type"], "telegram")

    def test_disconnected_telegram_still_does_not_count(self):
        result = self.health(telegram_rows=[telegram(is_active=False,
                                                     connection_status="disconnected")])
        self.assertEqual(result["connected_count"], 0)

    def test_channel_errors_are_still_sanitised(self):
        result = self.health(telegram_rows=[telegram(
            connection_status="failed",
            last_error="bot_token 123:ABC rejected")])
        self.assertNotIn("123:ABC", result["items"][0]["last_error"])


if __name__ == "__main__":
    unittest.main()
