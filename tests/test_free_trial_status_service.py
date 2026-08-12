import unittest
from datetime import datetime, timezone, timedelta

from app.services.free_trial_status_service import (
    resolve_effective_subscription_status,
)


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


class TestFreeTrialEffectiveStatus(unittest.TestCase):
    def test_future_free_trial_is_trialing(self):
        result = resolve_effective_subscription_status(
            {
                "status": "active",
                "trial_ends_at": (NOW + timedelta(days=3)).isoformat(),
            },
            {"code": "free"},
            now=NOW,
        )

        self.assertEqual(result["effective_status"], "trialing")
        self.assertTrue(result["trial_active"])
        self.assertFalse(result["trial_expired"])
        self.assertEqual(result["trial_days_remaining"], 3)

    def test_expired_trialing_free_is_expired(self):
        result = resolve_effective_subscription_status(
            {
                "status": "trialing",
                "trial_ends_at": (NOW - timedelta(seconds=1)).isoformat(),
            },
            {"code": "free"},
            now=NOW,
        )

        self.assertEqual(result["effective_status"], "expired")
        self.assertTrue(result["trial_expired"])
        self.assertEqual(result["trial_days_remaining"], 0)

    def test_legacy_active_free_with_expired_trial_is_expired(self):
        result = resolve_effective_subscription_status(
            {
                "status": "active",
                "trial_ends_at": (NOW - timedelta(days=1)).isoformat(),
            },
            {"code": "free"},
            now=NOW,
        )

        self.assertEqual(result["effective_status"], "expired")
        self.assertTrue(result["trial_expired"])

    def test_legacy_active_free_missing_trial_fails_closed(self):
        result = resolve_effective_subscription_status(
            {"status": "active", "trial_ends_at": None},
            {"code": "free"},
            now=NOW,
        )

        self.assertEqual(result["effective_status"], "expired")
        self.assertTrue(result["trial_expired"])
        self.assertTrue(result["trial_missing"])

    def test_paid_plan_preserves_raw_status(self):
        result = resolve_effective_subscription_status(
            {"status": "active", "trial_ends_at": (NOW - timedelta(days=1)).isoformat()},
            {"code": "advanced"},
            now=NOW,
        )

        self.assertEqual(result["effective_status"], "active")
        self.assertFalse(result["is_free_trial"])
        self.assertFalse(result["trial_expired"])


if __name__ == "__main__":
    unittest.main()
