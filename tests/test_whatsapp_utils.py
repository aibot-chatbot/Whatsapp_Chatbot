import json
import unittest

from app.utils.whatsapp_utils import (
    get_interactive_button_message,
    get_interactive_button_message_input,
    get_text_message_input,
)


class WhatsAppInteractiveButtonPayloadTests(unittest.TestCase):
    def _buttons(self, payload):
        return json.loads(payload)["interactive"]["action"]["buttons"]

    def test_interactive_button_payload_uses_maximum_three_buttons(self):
        payload = get_interactive_button_message(
            "1234567890",
            "Choose one",
            ["Sales", "Support", "Pricing", "Ignored"],
        )

        buttons = self._buttons(payload)
        self.assertEqual(len(buttons), 3)
        self.assertEqual([button["reply"]["title"] for button in buttons], [
            "Sales",
            "Support",
            "Pricing",
        ])

    def test_interactive_button_title_longer_than_twenty_characters_is_truncated(self):
        payload = get_interactive_button_message(
            "1234567890",
            "Choose one",
            ["This title is definitely too long"],
        )

        title = self._buttons(payload)[0]["reply"]["title"]
        self.assertEqual(title, "This title is defini")
        self.assertEqual(len(title), 20)

    def test_interactive_button_short_title_is_unchanged(self):
        payload = get_interactive_button_message(
            "1234567890",
            "Choose one",
            ["Sales"],
        )

        self.assertEqual(self._buttons(payload)[0]["reply"]["title"], "Sales")

    def test_interactive_button_payload_skips_empty_titles(self):
        payload = get_interactive_button_message(
            "1234567890",
            "Choose one",
            ["", "  ", None, "Support"],
        )

        buttons = self._buttons(payload)
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0]["reply"], {"id": "btn_0", "title": "Support"})

    def test_compatibility_wrapper_matches_primary_helper(self):
        args = ("1234567890", "Choose one", ["Sales", "Support"])

        self.assertEqual(
            get_interactive_button_message_input(*args),
            get_interactive_button_message(*args),
        )

    def test_plain_text_payload_is_unaffected(self):
        payload = json.loads(get_text_message_input("1234567890", "Hello"))

        self.assertEqual(payload["type"], "text")
        self.assertEqual(payload["text"], {"preview_url": False, "body": "Hello"})
        self.assertNotIn("interactive", payload)


if __name__ == "__main__":
    unittest.main()
