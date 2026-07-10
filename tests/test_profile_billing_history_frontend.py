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


PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend",
    "profile.html",
)


class TestProfileHistorySectionPresence(unittest.TestCase):
    """Verify the Subscription Payment History HTML section exists."""

    @classmethod
    def setUpClass(cls):
        with open(PROFILE_PATH, "r", encoding="utf-8", errors="replace") as f:
            cls.html = f.read()

    def test_history_section_exists(self):
        self.assertIn("subscription-payment-history-section", self.html)

    def test_history_loading_state(self):
        self.assertIn("sph-loading", self.html)

    def test_history_content_state(self):
        self.assertIn("sph-content", self.html)

    def test_history_empty_state(self):
        self.assertIn("sph-empty", self.html)

    def test_history_error_state(self):
        self.assertIn("sph-error", self.html)

    def test_history_table_exists(self):
        self.assertIn("sph-tbody", self.html)

    def test_load_more_button_exists(self):
        self.assertIn("sph-load-more", self.html)

    def test_table_headers_present(self):
        headers = ["Date", "Plan", "Amount", "Payment", "Activation", "Reference", "Action"]
        lower_html = self.html.lower()
        for header in headers:
            self.assertIn(header.lower(), lower_html)

    def test_detail_modal_exists(self):
        self.assertIn("sph-order-detail-modal", self.html)


class TestProfileHistoryJavaScriptFunctions(unittest.TestCase):
    """Verify the JavaScript functions for billing history are defined."""

    @classmethod
    def setUpClass(cls):
        with open(PROFILE_PATH, "r", encoding="utf-8", errors="replace") as f:
            cls.html = f.read()

    def test_load_subscription_payment_history_function(self):
        self.assertIn("function loadSubscriptionPaymentHistory()", self.html)

    def test_show_order_detail_modal_function(self):
        self.assertIn("function showOrderDetailModal", self.html)

    def test_close_order_detail_modal_function(self):
        self.assertIn("function closeOrderDetailModal", self.html)

    def test_handle_retry_from_history_function(self):
        self.assertIn("function handleRetryFromHistory", self.html)

    def test_build_payment_status_badge_function(self):
        self.assertIn("function buildPaymentStatusBadge", self.html)

    def test_build_activation_status_badge_function(self):
        self.assertIn("function buildActivationStatusBadge", self.html)

    def test_list_endpoint_called(self):
        self.assertIn("api/billing/subscription/orders", self.html)

    def test_detail_endpoint_called(self):
        self.assertIn("api/billing/subscription/orders/", self.html)

    def test_receipt_endpoint_referenced(self):
        self.assertIn("/receipt", self.html)

    def test_retry_endpoint_referenced(self):
        self.assertIn("/retry", self.html)

    def test_init_calls_load_history(self):
        self.assertIn("loadSubscriptionPaymentHistory()", self.html)

    def test_load_more_wired(self):
        self.assertIn("loadSubscriptionPaymentHistory", self.html)

    def test_no_inner_html_for_backend_text(self):
        """Ensure backend-provided text uses textContent, not innerHTML."""
        lines = self.html.split("\n")
        for i, line in enumerate(lines):
            if "order_reference" in line.lower() and "innerhtml" in line.lower():
                self.fail(f"Potential unsafe innerHTML for backend data at line {i+1}: {line.strip()}")

    def test_format_billing_date_function_available(self):
        self.assertIn("function formatBillingDate", self.html)

    def test_payment_status_labels_present(self):
        labels = ["Pending", "Paid", "Completed", "Failed", "Expired", "Needs Attention"]
        for label in labels:
            self.assertIn(label, self.html)


class TestProfileHistoryErrorHandling(unittest.TestCase):
    """Verify error handling in billing history code."""

    @classmethod
    def setUpClass(cls):
        with open(PROFILE_PATH, "r", encoding="utf-8", errors="replace") as f:
            cls.html = f.read()

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
