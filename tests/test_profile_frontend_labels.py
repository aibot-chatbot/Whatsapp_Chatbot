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


class TestProfileUIPolish(unittest.TestCase):
    """Static checks for Phase 8A UI polish: trial text, money formatting."""

    @classmethod
    def setUpClass(cls):
        with open(PROFILE_PATH, "r", encoding="utf-8", errors="replace") as f:
            cls.html = f.read()

    def test_trial_text_no_mojibake(self):
        """Trial text must not contain hardcoded mojibake."""
        # Exact mojibake sequence that was in the trial text
        self.assertNotIn("ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â uses DeepSeek", self.html)

    def test_trial_text_has_clean_separator(self):
        """Trial text uses plain ASCII hyphen, not em dash."""
        self.assertIn("remaining) - uses", self.html)
        self.assertIn("DeepSeek AI", self.html)

    def test_format_micro_myr_helper_exists(self):
        """Shared micro-MYR formatting helper is defined."""
        self.assertIn("function formatMicroMyr", self.html)

    def test_format_micro_myr_zero_case(self):
        """formatMicroMyr handles zero correctly."""
        self.assertIn('"RM 0.00"', self.html)

    def test_format_micro_myr_tiny_positive(self):
        """formatMicroMyr has sub-cent positive branch."""
        self.assertIn('"RM <0.01"', self.html)

    def test_format_micro_myr_tiny_negative(self):
        """formatMicroMyr has sub-cent negative branch."""
        self.assertIn('"-RM <0.01"', self.html)

    def test_micro_myr_to_signed_delegates(self):
        """microMyrToSignedMyr delegates to formatMicroMyr."""
        self.assertIn("formatMicroMyr(val)", self.html)

    def test_no_inline_toFixed_balance_after(self):
        """Balance-after display uses formatMicroMyr, not inline toFixed."""
        self.assertNotIn('Balance after: RM " + ', self.html)
        self.assertIn('Balance after: " + formatMicroMyr(', self.html)

    def test_credit_summary_uses_format_micro_myr(self):
        """AI credit summary (included, topup, total) uses formatMicroMyr."""
        self.assertIn('formatMicroMyr(d.included_balance_micro_myr)', self.html)
        self.assertIn('formatMicroMyr(d.topup_balance_micro_myr)', self.html)
        self.assertIn('formatMicroMyr(d.total_balance_micro_myr)', self.html)

    def test_no_remaining_inline_fraction(self):
        """No remaining inline /1000000).toFixed(2) patterns exist."""
        # The old pattern should be gone from money-formatting contexts
        old_pattern = re.findall(r'/1000000\)\.toFixed\(2\)', self.html)
        # One remaining is in formatMicroMyr itself, that's expected
        self.assertLessEqual(len(old_pattern), 1,
            f"Found {len(old_pattern)} instances of /1000000).toFixed(2) - expected at most 1")


class TestTransactionTypeLabels(unittest.TestCase):
    """Verify transaction typeMap matches actual DB transaction_type values."""

    @classmethod
    def setUpClass(cls):
        with open(PROFILE_PATH, "r", encoding="utf-8", errors="replace") as f:
            cls.html = f.read()

    EXPECTED = [
        ("usage_debit", "AI Usage"),
        ("topup_purchase", "Credit Top-Up"),
        ("subscription_included", "Subscription Credit"),
        ("included_credit_grant", "Included Credit"),
        ("expiry", "Credit Expired"),
        ("adjustment", "Credit Adjustment"),
        ("refund", "Credit Refund"),
        ("reversal", "Credit Reversal"),
    ]

    def test_all_expected_type_map_entries_present(self):
        for key, label in self.EXPECTED:
            with self.subTest(key=key):
                self.assertIn('"' + key + '": "' + label + '"', self.html,
                    f"Missing typeMap entry: {key} -> {label}")

    def test_old_mismatched_keys_not_present_in_map(self):
        """Old keys 'usage' and 'topup' alone should not be typeMap keys (now usage_debit/topup_purchase)."""
        # 'usage' appears elsewhere (e.g. CSS classes), but not as a typeMap key
        self.assertNotIn('"usage": "AI Usage"', self.html)
        self.assertNotIn('"topup": "Credit Top-Up"', self.html)


class TestProfileJavaScriptSyntax(unittest.TestCase):
    """Catch browser-breaking JavaScript syntax errors in profile.html."""

    @classmethod
    def setUpClass(cls):
        import subprocess, tempfile, re, shutil, os

        # Check if Node.js is available
        cls.node_path = shutil.which("node") or shutil.which("nodejs")
        if cls.node_path is None:
            raise unittest.SkipTest("Node.js not available — skipping JS syntax check")

        with open(PROFILE_PATH, "r", encoding="utf-8", errors="replace") as f:
            html = f.read()

        # Extract all inline <script> blocks (not external src=...)
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE)

        if not scripts:
            raise unittest.SkipTest("No inline <script> blocks found")

        # Concatenate with semicolon separators to avoid ASI issues at boundaries
        cls.combined_js = ";\n".join(s.strip() for s in scripts if s.strip())

        if not cls.combined_js.strip():
            raise unittest.SkipTest("All script blocks are empty")

        # Write to temp file and check syntax
        cls.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".js", delete=False, encoding="utf-8")
        cls.tmp.write(cls.combined_js)
        cls.tmp.close()

        result = subprocess.run(
            [cls.node_path, "--check", cls.tmp.name],
            capture_output=True, text=True, timeout=15,
        )
        cls.syntax_ok = result.returncode == 0
        cls.syntax_error = result.stderr.strip() if not cls.syntax_ok else ""

    @classmethod
    def tearDownClass(cls):
        import os
        if hasattr(cls, "tmp") and os.path.exists(cls.tmp.name):
            os.unlink(cls.tmp.name)

    def test_profile_javascript_parses_without_syntax_error(self):
        self.assertTrue(
            self.syntax_ok,
            f"profile.html has a JavaScript syntax error:\n{self.syntax_error[:800]}",
        )


if __name__ == "__main__":
    unittest.main()
