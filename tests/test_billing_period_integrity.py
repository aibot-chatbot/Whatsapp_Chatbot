import os
import sys
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pathlib
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

if "google" not in sys.modules:
    _g = types.ModuleType("google")
    _g.genai = types.ModuleType("google.genai")
    _g.genai.Client = MagicMock()
    sys.modules["google"] = _g
    sys.modules["google.genai"] = _g.genai
for _module in ("fitz", "tools", "_tools"):
    if _module not in sys.modules:
        sys.modules[_module] = types.ModuleType(_module)

from app.services.billing_period_service import (
    calculate_current_period_end,
    detect_current_period_anomaly,
    validate_current_period,
)


class TestBillingPeriodCalendarArithmetic(unittest.TestCase):
    def test_monthly_calendar_arithmetic_preserves_day_when_possible(self):
        start = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
        end = calculate_current_period_end(start, "monthly")
        self.assertEqual(end, datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc))

    def test_monthly_calendar_arithmetic_handles_short_february(self):
        start = datetime(2026, 1, 31, 12, 0, tzinfo=timezone.utc)
        end = calculate_current_period_end(start, "monthly")
        self.assertEqual(end, datetime(2026, 2, 28, 12, 0, tzinfo=timezone.utc))

    def test_monthly_calendar_arithmetic_handles_leap_year_february(self):
        start = datetime(2028, 1, 31, 12, 0, tzinfo=timezone.utc)
        end = calculate_current_period_end(start, "monthly")
        self.assertEqual(end, datetime(2028, 2, 29, 12, 0, tzinfo=timezone.utc))

    def test_monthly_period_rejects_one_year_end(self):
        with self.assertRaises(ValueError):
            validate_current_period(
                "2026-07-29T00:00:00+00:00",
                "2027-07-29T00:00:00+00:00",
                "monthly",
            )


class TestBillingPeriodReadDetection(unittest.TestCase):
    def setUp(self):
        self.subscription = {
            "id": 10,
            "company_id": 42,
            "plan_id": 4,
            "status": "active",
            "starts_at": "2026-07-29T00:00:00+00:00",
            "current_period_start": "2026-07-29T00:00:00+00:00",
            "current_period_end": "2027-07-29T00:00:00+00:00",
            "trial_ends_at": None,
            "cancelled_at": None,
            "ends_at": None,
            "payment_gateway": None,
            "created_at": "2026-07-29T00:00:00+00:00",
            "updated_at": "2026-07-29T00:00:00+00:00",
        }
        self.plan = {
            "id": 4,
            "code": "pro",
            "name": "Pro",
            "description": "Pro plan",
            "price": 169,
            "currency": "MYR",
            "billing_interval": "monthly",
            "chatbot_limit": 3,
            "team_member_limit": 5,
            "knowledge_file_limit": 75,
            "knowledge_storage_limit_bytes": 1073741824,
            "channel_limit": 2,
            "feature_flags": {},
            "included_ai_credit_micro_myr": 60000000,
            "model_access_tier": "premium",
        }

    def test_detector_identifies_historical_monthly_one_year_period(self):
        anomaly = detect_current_period_anomaly(self.subscription, self.plan)
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly["reason"], "period_interval_mismatch")
        self.assertEqual(
            anomaly["expected_current_period_end"],
            "2026-08-29T00:00:00+00:00",
        )

    @patch("app.services.billing_service.get_plan_by_id")
    @patch("app.services.billing_service._get_latest_company_subscription")
    @patch("app.services.billing_service._get_company_subscription")
    def test_get_current_subscription_reports_stored_period_without_normalizing(
        self, mock_current, mock_latest, mock_plan,
    ):
        from app.services.billing_service import get_current_subscription

        mock_current.return_value = self.subscription
        mock_latest.return_value = None
        mock_plan.return_value = self.plan

        with self.assertLogs("app.services.billing_period_service", level="WARNING"):
            result = get_current_subscription(42)

        self.assertEqual(result["current_period_end"], "2027-07-29T00:00:00+00:00")

    @patch("app.services.billing_service.sum_company_ai_usage_tokens")
    @patch("app.services.billing_service.sum_company_knowledge_storage")
    @patch("app.services.billing_service.count_company_knowledge_files")
    @patch("app.services.billing_service.list_company_channel_slots")
    @patch("app.services.billing_service.count_pending_company_invitations")
    @patch("app.services.billing_service.count_active_company_members")
    @patch("app.services.billing_service.count_company_chatbots")
    @patch("app.services.billing_service.get_plan_by_id")
    @patch("app.services.billing_service._get_company_subscription")
    def test_usage_reports_stored_period_and_logs_anomaly(
        self, mock_sub, mock_plan, mock_bots, mock_members, mock_invites,
        mock_channels, mock_files, mock_storage, mock_tokens,
    ):
        from app.services.billing_service import get_company_usage

        mock_sub.return_value = self.subscription
        mock_plan.return_value = self.plan
        mock_bots.return_value = 0
        mock_members.return_value = 0
        mock_invites.return_value = 0
        mock_channels.return_value = []
        mock_files.return_value = 0
        mock_storage.return_value = 0
        mock_tokens.return_value = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        with self.assertLogs("app.services.billing_period_service", level="WARNING"):
            result = get_company_usage(42)

        self.assertEqual(result["period"]["end"], "2027-07-29T00:00:00+00:00")
        self.assertEqual(result["period"]["end_source"], "stored")


if __name__ == "__main__":
    unittest.main()
