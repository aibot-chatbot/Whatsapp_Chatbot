"""Frontend regressions for subscription management confirmation UX."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROFILE_HTML = ROOT / "frontend" / "profile.html"


class TestProfileSubscriptionConfirmationFrontend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PROFILE_HTML.read_text(encoding="utf-8", errors="replace")

    def _function(self, signature):
        match = re.search(
            rf"function {re.escape(signature)} \{{(?P<body>.*?)\n        \}}",
            self.html,
            flags=re.S,
        )
        self.assertIsNotNone(match, f"{signature} not found")
        return match.group("body")

    def test_undo_cancellation_button_opens_confirmation_before_api_call(self):
        self.assertIn('subConfirmUndoCancel()', self.html)
        self.assertNotIn(
            'buildSubActionButton("sub-action-undo-cancel", \'<i data-lucide="rotate-ccw" style="width:15px;height:15px;vertical-align:middle;margin-right:6px;"></i> Undo Cancellation\', "primary-bg", "subUndoCancel()")',
            self.html,
        )

        confirm_fn = self._function("subConfirmUndoCancel()")
        self.assertIn("subConfirmModal(", confirm_fn)
        self.assertIn("Your subscription will remain active and will not be cancelled at the end of the billing period.", confirm_fn)
        self.assertIn("subUndoCancel", confirm_fn)
        self.assertNotIn("authenticatedFetch", confirm_fn)

    def test_cancel_scheduled_downgrade_button_opens_confirmation_before_api_call(self):
        self.assertIn('subConfirmClearDowngrade()', self.html)
        self.assertNotIn(
            'buildSubActionButton("sub-action-clear-downgrade", \'<i data-lucide="x" style="width:15px;height:15px;vertical-align:middle;margin-right:6px;"></i> Cancel Scheduled Downgrade\', "ghost", "subClearDowngrade()")',
            self.html,
        )

        confirm_fn = self._function("subConfirmClearDowngrade()")
        self.assertIn("subConfirmModal(", confirm_fn)
        self.assertIn("Your current plan will remain active and the scheduled downgrade will be removed.", confirm_fn)
        self.assertIn("subClearDowngrade", confirm_fn)
        self.assertNotIn("authenticatedFetch", confirm_fn)

    def test_cancel_subscription_button_opens_confirmation_before_api_call(self):
        self.assertIn('subConfirmCancelSubscription()', self.html)
        self.assertIn(
            'buildSubActionButton("sub-action-cancel", \'<i data-lucide="x-circle" style="width:15px;height:15px;vertical-align:middle;margin-right:6px;"></i> Cancel Subscription\', "danger", "subConfirmCancelSubscription()")',
            self.html,
        )
        self.assertNotIn("subConfirmModal('Cancel Subscription'", self.html)

        confirm_fn = self._function("subConfirmCancelSubscription()")
        self.assertIn("subConfirmModal(", confirm_fn)
        self.assertIn(
            "Cancel your subscription? Your plan will remain active until the end of the current billing period.",
            confirm_fn,
        )
        self.assertIn("subCancelSubscription", confirm_fn)
        self.assertNotIn("authenticatedFetch", confirm_fn)

    def test_cancel_button_closes_subscription_modal_without_api_call(self):
        modal_fn = self._function("subConfirmModal(title, message, confirmLabel, confirmColor, onConfirm)")
        cancel_handler = re.search(
            r'document\.getElementById\("sub-modal-cancel"\)\.addEventListener\("click", function\(\) \{(?P<body>.*?)\}\);',
            modal_fn,
            flags=re.S,
        ).group("body")
        self.assertIn("document.body.removeChild(overlay);", cancel_handler)
        self.assertNotIn("onConfirm", cancel_handler)
        self.assertNotIn("authenticatedFetch", cancel_handler)

    def test_confirm_button_calls_existing_api_callback(self):
        modal_fn = self._function("subConfirmModal(title, message, confirmLabel, confirmColor, onConfirm)")
        confirm_handler = re.search(
            r'document\.getElementById\("sub-modal-confirm"\)\.addEventListener\("click", function\(\) \{(?P<body>.*?)\}\);',
            modal_fn,
            flags=re.S,
        ).group("body")
        self.assertIn("document.body.removeChild(overlay);", confirm_handler)
        self.assertIn("if (onConfirm) onConfirm();", confirm_handler)

        undo_fn = self._function("subUndoCancel()")
        clear_fn = self._function("subClearDowngrade()")
        cancel_fn = self._function("subCancelSubscription()")
        self.assertIn("/api/billing/subscription/undo-cancel", undo_fn)
        self.assertIn('/api/billing/subscription/downgrade", { method: "DELETE" }', clear_fn)
        self.assertIn("/api/billing/subscription/cancel", cancel_fn)


if __name__ == "__main__":
    unittest.main()
