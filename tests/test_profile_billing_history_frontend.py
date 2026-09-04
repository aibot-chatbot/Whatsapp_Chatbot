"""Static/frontend tests for the Profile billing history UI in profile.html.

These tests verify that the profile page contains the expected wiring
for subscription payment history display and interaction without
executing JavaScript in a browser.

The tests read the HTML file directly and check for expected element IDs,
event handler names, and API endpoint references.
"""

import os
import re
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
# ------------------------------------------------------------------------------



PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend",
    "profile.html",
)


class TestProfileHistorySectionPresence(unittest.TestCase):
    """Verify the Subscription Payment History HTML section exists."""

    @classmethod
    def setUpClass(cls):
        cls.html = _read_billing_source()

    def test_history_section_exists(self):
        self.assertIn("bl-orders-section", self.html)

    def test_history_loading_state(self):
        self.assertIn("bl-orders-loading", self.html)

    def test_history_content_state(self):
        self.assertIn("bl-orders-wrap", self.html)

    def test_history_empty_state(self):
        self.assertIn("bl-orders-empty", self.html)

    def test_history_error_state(self):
        self.assertIn("bl-orders-error", self.html)

    def test_history_table_exists(self):
        self.assertIn("bl-orders-tbody", self.html)

    def test_load_more_button_exists(self):
        self.assertIn("bl-orders-more", self.html)

    def test_table_headers_present(self):
        headers = ["Date", "Plan", "Amount", "Payment", "Activation", "Reference", "Action"]
        lower_html = self.html.lower()
        for header in headers:
            self.assertIn(header.lower(), lower_html)

    def test_detail_modal_exists(self):
        self.assertIn("bl-order-modal", self.html)


class TestProfileHistoryJavaScriptFunctions(unittest.TestCase):
    """Billing history rendering must never write backend data as markup.

    The old Profile page concatenated escaped values into innerHTML strings.
    The rewritten billing page builds DOM nodes through a single el() helper
    that assigns textContent, so injection is structurally impossible rather
    than merely escaped. These assertions guard that stronger property.
    """

    @classmethod
    def setUpClass(cls):
        cls.html = _read_billing_source()

    def test_orders_are_loaded_and_paginated(self):
        self.assertIn("function loadOrders", self.html)
        self.assertIn("function loadMoreOrders", self.html)

    def test_order_detail_and_retry_exist(self):
        self.assertIn("function openOrderDetail", self.html)
        self.assertIn("function closeOrderModal", self.html)
        self.assertIn("function retryOrder", self.html)

    def test_no_inner_html_anywhere(self):
        self.assertNotRegex(self.html, re.compile(r"\.innerHTML\s*="))

    def test_dom_helper_uses_text_content(self):
        self.assertIn("node.textContent = text;", _fn_body(self.html, "el"))

    def test_order_rows_render_backend_values_as_text(self):
        body = _fn_body(self.html, "orderRow")
        self.assertNotIn("innerHTML", body)
        self.assertIn("el(", body)

    def test_order_detail_rows_render_backend_values_as_text(self):
        body = _fn_body(self.html, "detailRow")
        self.assertNotIn("innerHTML", body)

    def test_status_fallbacks_are_clean(self):
        replacement_mojibake = chr(0xFFFD)
        for fn in ("paymentPill", "activationPill"):
            with self.subTest(fn=fn):
                body = _fn_body(self.html, fn)
                self.assertNotIn(replacement_mojibake, body)
        self.assertNotIn(replacement_mojibake, self.html)

    def test_mark_read_uses_event_listener_not_inline_handler(self):
        self.assertIn('addEventListener("click"', self.html)
        self.assertNotRegex(self.html, re.compile(r"onclick\s*="))

class TestProfileHistoryErrorHandling(unittest.TestCase):
    """Verify error handling in billing history code."""

    @classmethod
    def setUpClass(cls):
        cls.html = _read_billing_source()

    def test_network_error_handled(self):
        self.assertIn("Network error", self.html)

    def test_failed_load_handled(self):
        self.assertIn("Unable to load payment history", self.html)

    def test_no_backend_internal_error_exposed(self):
        """Ensure 'internal error text' or similar patterns are not present."""
        lower = self.html.lower()
        self.assertNotIn("traceback", lower)
        self.assertNotIn("stack trace", lower)


if __name__ == "__main__":
    unittest.main()
