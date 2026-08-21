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

    def test_unknown_activation_status_uses_clean_fallback(self):
        self.assertIn('">Unknown</span>', self.html)
        replacement_mojibake = "\u00c3\u00af\u00c2\u00bf\u00c2\u00bd"
        self.assertNotIn('">' + replacement_mojibake + '</span>', self.html)

    def test_subscription_history_plan_fallback_is_clean(self):
        self.assertIn('planTd.textContent = (o.plan && o.plan.name) || "\\u2014";', self.html)
        replacement_mojibake = "\u00c3\u00af\u00c2\u00bf\u00c2\u00bd"
        self.assertNotIn('(o.plan && o.plan.name) || "' + replacement_mojibake + '"', self.html)

    def test_order_detail_fallbacks_are_clean(self):
        expected = [
            'appendOrderDetailRow(body, "Plan", plan.name',
            'appendOrderDetailRow(body, "Order Ref", d.order_reference',
            'appendOrderDetailRow(body, "Payment Ref", d.payment_reference',
            'appendOrderDetailRow(body, "Gateway Ref", d.gateway_order_id',
            'appendOrderDetailRow(body, "Created", d.created_at ? new Date(d.created_at).toLocaleString() : "\\u2014"',
        ]
        for snippet in expected:
            self.assertIn(snippet, self.html)
        replacement_mojibake = "\u00c3\u00af\u00c2\u00bf\u00c2\u00bd"
        self.assertNotIn('"' + replacement_mojibake + '"', self.html)

    def test_order_detail_backend_values_use_text_content(self):
        modal_start = self.html.index("async function showOrderDetailModal")
        modal_end = self.html.index("async function handleRetryFromHistory", modal_start)
        modal_source = self.html[modal_start:modal_end]

        self.assertIn("function appendOrderDetailRow", self.html)
        self.assertIn('valueWrap.textContent = value || "\\u2014";', self.html)
        self.assertIn("messageDiv.textContent = d.message;", modal_source)
        self.assertIn("retryButton.addEventListener(\"click\"", modal_source)
        self.assertNotIn("var html = '';", modal_source)
        self.assertNotIn("body.innerHTML = html", modal_source)
        self.assertNotIn("' + (plan.name", modal_source)
        self.assertNotIn("' + (d.order_reference", modal_source)
        self.assertNotIn("' + (d.payment_reference", modal_source)
        self.assertNotIn("' + (d.gateway_order_id", modal_source)
        self.assertNotIn("' + d.message + '", modal_source)

    def test_order_detail_malicious_examples_are_not_interpolated(self):
        malicious_examples = [
            "<img src=x onerror=alert(1)>",
            "<script>alert(1)</script>",
            "\"><svg onload=alert(1)>",
        ]
        modal_start = self.html.index("async function showOrderDetailModal")
        modal_end = self.html.index("async function handleRetryFromHistory", modal_start)
        modal_source = self.html[modal_start:modal_end]

        for example in malicious_examples:
            self.assertNotIn(example, self.html)
        self.assertIn("textContent", modal_source)
        self.assertNotIn("insertAdjacentHTML", modal_source)
        self.assertNotIn("outerHTML", modal_source)

    def test_unknown_payment_and_billing_statuses_are_neutral(self):
        self.assertIn('var label = labelMap[status] || "Unknown";', self.html)
        self.assertIn('return map[status] || "Unknown";', self.html)
        self.assertNotIn("labelMap[status] || status", self.html)
        self.assertNotIn("return map[status] || status", self.html)

    def test_pending_plan_name_is_rendered_as_text(self):
        self.assertIn("function renderScheduledDowngradeTarget", self.html)
        self.assertIn('strong.textContent = planName || "\\u2014";', self.html)
        self.assertIn("renderScheduledDowngradeTarget(", self.html)
        self.assertNotIn('"Target: <strong>" + pendingPlan.name', self.html)

    def test_billing_notifications_mark_read_uses_event_listener(self):
        start = self.html.index("async function loadBillingNotifications")
        end = self.html.index("async function markSingleNotificationRead", start)
        source = self.html[start:end]

        self.assertIn('titleEl.textContent = n.title || "";', source)
        self.assertIn('messageEl.textContent = n.message || "";', source)
        self.assertIn('severityEl.textContent = n.severity || "";', source)
        self.assertIn("markReadBtn.addEventListener(\"click\"", source)
        self.assertIn("markSingleNotificationRead(id);", source)
        self.assertNotIn('onclick="markSingleNotificationRead(', source)
        self.assertNotIn("' + n.id + '", source)

    def test_payment_polling_copy_has_no_mojibake(self):
        self.assertIn("Please wait - your balance will update once payment is verified.", self.html)
        self.assertIn("Please wait - your subscription will update once payment is verified.", self.html)
        self.assertNotIn("Please wait " + "\u00c3\u0192\u00c2\u00a2", self.html)

    def test_profile_html_has_no_known_mojibake_literals(self):
        markers = ["\u00c3", "\u00c2", "\u00e2\u20ac", "\ufffd", "\u00c3\u00af", "\u00c3\u0192"]
        for marker in markers:
            self.assertNotIn(marker, self.html)


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
