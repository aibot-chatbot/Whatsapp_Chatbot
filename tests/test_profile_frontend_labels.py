"""Frontend tests verifying company-wide billing labels.

Ensures the profile page clarifies that billing/credit data is
company-wide and not per-bot.
"""

import os
import re
import json
import shutil
import subprocess
import tempfile
import unittest


# --- Billing moved out of profile.html (2026-09) -------------------------------
# The billing surface now lives on its own page, split across markup, logic and
# styles. These assertions guard the billing guarantees, so they read all three
# parts of that page as one source rather than a single monolithic file.
def _read_billing_source():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _parts = []
    for _rel in (("billing.html",), ("assets", "js", "billing.js"), ("assets", "css", "billing.css")):
        _path = os.path.join(_root, "frontend", *_rel)
        with open(_path, "r", encoding="utf-8", errors="replace") as _fh:
            _parts.append(_fh.read())
    return chr(10).join(_parts)


def _fn_body(source, name):
    """Return the brace-matched body of a JS function declaration."""
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\(", source)
    if not m:
        raise AssertionError("function %s not found in billing source" % name)
    start = source.index("{", m.end() - 1)
    depth = 0
    for j in range(start, len(source)):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[start:j + 1]
    raise AssertionError("unbalanced braces in %s" % name)


def _map_entry_re(key, label):
    """Match a JS object entry for key -> label under either quoting style.

    The old page wrote {"chat_reply": "Chat Reply"}; the rewritten billing page
    writes {chat_reply: "Chat Reply"}. The data is identical, so this asserts
    the guarantee independently of source formatting.
    """
    return re.compile('"?' + re.escape(key) + '"?[ ]*:[ ]*"' + re.escape(label) + '"')
# ------------------------------------------------------------------------------



PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend",
    "profile.html",
)


class TestCompanyWideBillingLabels(unittest.TestCase):
    """Verify billing sections are labelled as company-wide."""

    @classmethod
    def setUpClass(cls):
        cls.html = _read_billing_source()

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
        # Check that pricing links include botQuery()
        self.assertIn("botQuery()", self.html)

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
        cls.html = _read_billing_source()

    def test_pricing_link_preserves_bot(self):
        """Pricing navigation should preserve bot context."""
        self.assertIn("pricing.html", self.html)
        self.assertIn("botQuery()", self.html)

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
        cls.html = _read_billing_source()

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
        """The signed formatter delegates to the shared currency formatter."""
        self.assertIn("formatMicroMyr(", _fn_body(self.html, "signedMicroMyr"))
    def test_no_inline_toFixed_balance_after(self):
        """Balance-after is formatted, never hand-rolled with toFixed."""
        self.assertNotIn('Balance after: RM " + ', self.html)
        self.assertIn("Balance after", self.html)
        self.assertNotRegex(self.html, re.compile(r"Balance after.{0,80}toFixed"))
    def test_credit_summary_uses_format_micro_myr(self):
        """All three balance figures go through the shared currency formatter."""
        body = _fn_body(self.html, "setBalanceFigures")
        self.assertEqual(body.count("formatMicroMyr("), 3, body)
    def test_no_remaining_inline_fraction(self):
        """No remaining inline /1000000).toFixed(2) patterns exist."""
        # The old pattern should be gone from money-formatting contexts
        old_pattern = re.findall(r'/1000000\)\.toFixed\(2\)', self.html)
        # One remaining is in formatMicroMyr itself, that's expected
        self.assertLessEqual(len(old_pattern), 1,
            f"Found {len(old_pattern)} instances of /1000000).toFixed(2) - expected at most 1")

    def test_free_trial_uses_effective_status_fields(self):
        """The Free-plan resolver reads the effective and trial status fields."""
        body = _fn_body(self.html, "resolveFreeState")
        for field in ("trial_expired", "trial_active", "effective_status"):
            self.assertIn(field, body)
        self.assertIn("Trial Expired", self.html)
    def test_free_trial_hides_monthly_accounting_period(self):
        """A free plan shows no monthly billing period.

        The rewritten page omits the Period Start/End rows for a free plan
        instead of rendering them and hiding them with an inline style, so the
        guarantee is asserted on the branch rather than on display toggling.
        """
        body = _fn_body(self.html, "renderPlan")
        self.assertIn("Period Start", body)
        self.assertIn("Period End", body)
        self.assertRegex(body, re.compile(r"if \(isFree\)[\s\S]{0,400}?\} else \{[\s\S]{0,400}?Period Start"))
    def test_free_trial_shows_trial_ended_copy(self):
        """Expired-trial copy survives the move to the billing page."""
        self.assertIn("Trial Ended", self.html)
        self.assertIn("Trial End", self.html)
        self.assertIn("upgrade to continue", self.html)
        self.assertIn("trialLabel", self.html)
    def test_paid_plan_status_path_unchanged(self):
        """Paid plans keep using effective/raw paid status, not Free trial labels."""
        self.assertRegex(self.html, re.compile(
            r"displayStatus\s*=\s*isFree\w*\s*\?\s*\w+\.badgeStatus\s*:\s*"
            r"\(\s*\w+\.effective_status\s*\|\|\s*\w+\.status\s*\)"))

class TestFreeBillingDisplayResolver(unittest.TestCase):
    """Execute the Profile Free-trial display resolver for key states."""

    @classmethod
    def setUpClass(cls):
        cls.html = _read_billing_source()
        cls.node_path = shutil.which("node") or shutil.which("nodejs")
        if cls.node_path is None:
            raise unittest.SkipTest("Node.js not available - skipping resolver execution")

        start = cls.html.index("function resolveFreeState")
        brace = cls.html.index("{", start)
        depth = 0
        end = None
        for idx in range(brace, len(cls.html)):
            char = cls.html[idx]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = idx + 1
                    break
        if end is None:
            raise AssertionError("Could not extract resolveFreeState")
        cls.resolver_js = cls.html[start:end]

    def _resolve(self, sub_data):
        script = self.resolver_js + "\nconsole.log(JSON.stringify(resolveFreeState(INPUT)));"
        script = "const INPUT = " + json.dumps(sub_data) + ";\n" + script
        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False, encoding="utf-8") as tmp:
            tmp.write(script)
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                [self.node_path, tmp_path],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
        finally:
            os.unlink(tmp_path)
        return json.loads(result.stdout)

    def test_active_raw_free_expired_trial_displays_trial_expired(self):
        result = self._resolve({
            "status": "active",
            "effective_status": "expired",
            "trial_expired": True,
            "trial_missing": False,
            "trial_status": "expired",
            "trial_ends_at": "2026-07-23T02:12:51.880632+00:00",
        })
        self.assertEqual(result["badgeStatus"], "trial_expired")
        self.assertEqual(result["trialLabel"], "Trial Ended")

    def test_trialing_raw_free_expired_trial_displays_trial_expired(self):
        result = self._resolve({
            "status": "trialing",
            "effective_status": "expired",
            "trial_expired": True,
            "trial_status": "expired",
            "trial_ends_at": "2026-07-23T02:12:51.880632+00:00",
        })
        self.assertEqual(result["badgeStatus"], "trial_expired")
        self.assertEqual(result["trialLabel"], "Trial Ended")

    def test_db_expired_free_displays_trial_expired(self):
        result = self._resolve({
            "status": "expired",
            "effective_status": "expired",
            "trial_expired": True,
            "trial_status": "expired",
            "trial_ends_at": "2026-07-21T03:08:34.741265+00:00",
        })
        self.assertEqual(result["badgeStatus"], "trial_expired")
        self.assertEqual(result["trialLabel"], "Trial Ended")

    def test_missing_trial_end_displays_trial_expired_without_fake_date(self):
        result = self._resolve({
            "status": "active",
            "effective_status": "expired",
            "trial_expired": True,
            "trial_missing": True,
            "trial_status": "missing",
            "trial_ends_at": None,
        })
        self.assertEqual(result["badgeStatus"], "trial_expired")
        self.assertEqual(result["trialLabel"], "Trial End")
        self.assertTrue(result["trialMissing"])

    def test_future_free_trial_displays_trialing(self):
        result = self._resolve({
            "status": "trialing",
            "effective_status": "trialing",
            "trial_active": True,
            "trial_expired": False,
            "trial_status": "active",
            "trial_ends_at": "2099-01-01T00:00:00+00:00",
        })
        self.assertEqual(result["badgeStatus"], "trialing")
        self.assertEqual(result["trialLabel"], "Trial Ends")


class TestTransactionTypeLabels(unittest.TestCase):
    """Verify transaction typeMap matches actual DB transaction_type values."""

    @classmethod
    def setUpClass(cls):
        cls.html = _read_billing_source()

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
                self.assertRegex(self.html, _map_entry_re(key, label),
                    f"Missing typeMap entry: {key} -> {label}")

    def test_old_mismatched_keys_not_present_in_map(self):
        """Old keys 'usage' and 'topup' alone should not be typeMap keys (now usage_debit/topup_purchase)."""
        # 'usage' appears elsewhere (e.g. CSS classes), but not as a typeMap key
        self.assertNotRegex(self.html, _map_entry_re("usage", "AI Usage"))
        self.assertNotRegex(self.html, _map_entry_re("topup", "Credit Top-Up"))

    def test_usage_debit_operation_type_labels_present(self):
        self.assertIn("function usageLabel", self.html)
        self.assertRegex(self.html, _map_entry_re("knowledge_extraction", "Knowledge Training"))
        self.assertRegex(self.html, _map_entry_re("knowledge_refinement_questions", "Refine Answers"))
        self.assertRegex(self.html, _map_entry_re("knowledge_refinement_verification", "Refine Answers"))
        self.assertRegex(self.html, _map_entry_re("test_scenario_generation", "Test Scenario Generation"))
        self.assertRegex(self.html, _map_entry_re("persona_derivation", "Persona Derivation"))
        self.assertRegex(self.html, _map_entry_re("profile_knowledge_match", "Profile / Knowledge Validation"))
        self.assertRegex(self.html, _map_entry_re("website_knowledge_extraction", "Website Knowledge Training"))
        self.assertRegex(self.html, _map_entry_re("knowledge_graph_extraction", "Knowledge Graph Training"))
        self.assertRegex(self.html, _map_entry_re("chat_reply", "Chat Reply"))
        self.assertRegex(self.html, _map_entry_re("message_reply", "Chat Reply"))
        self.assertRegex(self.html, _map_entry_re("customer_reply", "Chat Reply"))
        self.assertRegex(self.html, _map_entry_re("test_bot", "Test Bot"))
        self.assertRegex(self.html, _map_entry_re("test_chat", "Test Bot"))
        # Same three-tier fallback as before: explicit map, then a humanised
        # slug, then the generic label. Asserted without pinning identifiers.
        self.assertRegex(_fn_body(self.html, "usageLabel"), re.compile(
            r'return\s+\w+\[\w+\]\s*\|\|\s*\w+\(\w+\)\s*\|\|\s*"AI Usage";'))

    def test_usage_debit_uses_ai_usage_type_for_label(self):
        """usage_debit rows are labelled from ai_usage_type, falling back to operation_type."""
        self.assertRegex(self.html, re.compile(
            r'transaction_type[\s\S]{0,160}?usage_debit[\s\S]{0,200}?'
            r'usageLabel\(\s*txn\.ai_usage_type\s*\|\|\s*txn\.operation_type\s*\)'))

class TestProfileJavaScriptSyntax(unittest.TestCase):
    """Catch browser-breaking JavaScript syntax errors in profile.html."""

    @classmethod
    def setUpClass(cls):
        import subprocess, tempfile, re, shutil, os

        # Check if Node.js is available
        cls.node_path = shutil.which("node") or shutil.which("nodejs")
        if cls.node_path is None:
            raise unittest.SkipTest("Node.js not available — skipping JS syntax check")

        html = _read_billing_source()

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
