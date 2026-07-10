"""Frontend tests verifying company-wide billing labels.

Ensures the profile page clarifies that billing/credit data is
company-wide and not per-bot.
"""

import os
import re
import unittest


PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend",
    "profile.html",
)


class TestCompanyWideBillingLabels(unittest.TestCase):
    """Verify billing sections are labelled as company-wide."""

    @classmethod
    def setUpClass(cls):
        with open(PROFILE_PATH, "r", encoding="utf-8", errors="replace") as f:
            cls.html = f.read()

    def test_section_header_says_company(self):
        self.assertIn("Company Plan", self.html)

    def test_shared_credit_explanation_exists(self):
        self.assertIn("apply to all chatbots in this company", self.html)

    def test_credit_not_labeled_per_bot(self):
        """Verify AI credit is not described as belonging to a single bot."""
        lower = self.html.lower()
        # Search for per-bot credit labels that would be misleading
        misleading = [
            "this chatbot's credit",
            "bot credit",
            "your chatbot's ai credit",
        ]
        for phrase in misleading:
            self.assertNotIn(phrase.lower(), lower)

    def test_billing_history_labeled_as_company(self):
        section_text = self.html
        # The billing history section mentions subscription payment history
        self.assertIn("Subscription Payment History", section_text)

    def test_bot_id_preserved(self):
        """Verify bot_id is preserved in navigation links."""
        # Check that pricing links include getBotQuery()
        self.assertIn("getBotQuery()", self.html)

    def test_no_suggestion_balance_belongs_to_bot(self):
        """Check for phrases that would incorrectly tie balance to a bot."""
        lower = self.html.lower()
        problematic = [
            "credit for this chatbot",
            "this bot's ai credit",
            "this chatbot's payment",
        ]
        for phrase in problematic:
            self.assertNotIn(phrase.lower(), lower,
                             f"Found misleading phrase: {phrase}")


class TestBotIdNavigation(unittest.TestCase):
    """Verify bot_id is used only for navigation purposes."""

    @classmethod
    def setUpClass(cls):
        with open(PROFILE_PATH, "r", encoding="utf-8", errors="replace") as f:
            cls.html = f.read()

    def test_pricing_link_preserves_bot(self):
        """Pricing navigation should preserve bot context."""
        self.assertIn("pricing.html", self.html)
        self.assertIn("getBotQuery()", self.html)

    def test_bot_id_not_in_billing_api_calls(self):
        """Billing API calls should not include bot_id parameter."""
        # Find all authenticatedFetch calls
        fetch_calls = re.findall(r'authenticatedFetch\("[^"]*"', self.html)
        billing_calls = [c for c in fetch_calls if '/api/billing' in c]
        for call in billing_calls:
            # bot_id should not appear in any billing API call URL
            self.assertNotIn("bot_id", call,
                             f"bot_id found in billing API call: {call}")


if __name__ == "__main__":
    unittest.main()
