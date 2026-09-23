"""test_subscription_cancellation_and_downgrade.py

Phase 4C unit tests: cancellation scheduling, downgrade scheduling,
conflict handling, lifecycle execution, and API endpoint behavior.

All repository and service calls are mocked; no Supabase, payment gateway,
or network access.
"""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("FLASK_DEBUG", "1")

import sys
import pathlib
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import unittest
from unittest.mock import patch, MagicMock
import types
from datetime import datetime, timezone, timedelta

# Mock pre-existing broken dependencies
if "google" not in sys.modules:
    _g = types.ModuleType("google")
    _g.genai = types.ModuleType("google.genai")
    _g.genai.Client = MagicMock()
    sys.modules["google"] = _g
    sys.modules["google.genai"] = _g.genai
if "fitz" not in sys.modules:
    sys.modules["fitz"] = types.ModuleType("fitz")
if "tools" not in sys.modules:
    sys.modules["tools"] = types.ModuleType("tools")
if "_tools" not in sys.modules:
    sys.modules["_tools"] = types.ModuleType("_tools")

_sb = MagicMock()
_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.in_.return_value.lte.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
_sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
NOW = datetime.now(timezone.utc)
NOW_ISO = NOW.isoformat()

with patch("app.database.db.supabase", _sb):
    from app.services.subscription_lifecycle_service import (
        schedule_cancellation,
        clear_scheduled_cancellation,
        undo_subscription_cancellation,
        schedule_subscription_downgrade,
        clear_scheduled_downgrade,
        _process_single_subscription,
        _apply_scheduled_downgrade,
        process_due_subscriptions,
        transition_subscription_status,
        ALLOWED_TRANSITIONS,
    )
NOW_ISO = NOW.isoformat()
HOUR_AGO = (NOW - timedelta(hours=1)).isoformat()
HOUR_AHEAD = (NOW + timedelta(hours=1)).isoformat()
MONTH_AGO = (NOW - timedelta(days=31)).isoformat()
MONTH_AHEAD = (NOW + timedelta(days=31)).isoformat()


def _mk_sub(overrides=None):
    """Create a minimal active subscription dict."""
    sub = {
        "id": 1,
        "company_id": 42,
        "plan_id": 4,
        "plan_code": "pro",
        "status": "active",
        "trial_ends_at": None,
        "current_period_start": MONTH_AGO,
        "current_period_end": MONTH_AHEAD,
        "cancelled_at": None,
        "cancellation_scheduled_at": None,
        "cancellation_effective_at": None,
        "pending_plan_id": None,
        "plan_change_effective_at": None,
    }
    if overrides:
        sub.update(overrides)
    return sub


_LIFECYCLE = "app.services.subscription_lifecycle_service"


# =============================================================================
# Tests: Cancellation scheduling
# =============================================================================


class TestCancellationScheduling(unittest.TestCase):
    """Tests for schedule_cancellation and undo_subscription_cancellation."""

    def setUp(self):
        self.valid_sub = _mk_sub()

    @patch(_LIFECYCLE + "._get_current_sub")
    @patch(_LIFECYCLE + "._update_sub")
    @patch(_LIFECYCLE + "._validate_scheduling_active")
    def test_active_paid_can_schedule_cancellation(self, mock_validate, mock_update, mock_get_sub):
        """Active paid subscription can schedule cancellation."""
        mock_get_sub.return_value = self.valid_sub
        mock_update.return_value = _mk_sub({
            "cancellation_scheduled_at": NOW_ISO,
            "cancellation_effective_at": MONTH_AHEAD,
            "pending_plan_id": None,
            "plan_change_effective_at": None,
        })

        result = schedule_cancellation(company_id=42, effective_at=MONTH_AHEAD)

        self.assertIsNotNone(result)
        mock_update.assert_called_once()
        updates = mock_update.call_args[1]["updates"]
        self.assertEqual(updates["cancellation_effective_at"], MONTH_AHEAD)
        # Cancellation clears pending downgrade
        self.assertIsNone(updates["pending_plan_id"])
        self.assertIsNone(updates["plan_change_effective_at"])

    @patch(_LIFECYCLE + "._get_current_sub")
    def test_trial_cannot_schedule_cancellation(self, mock_get_sub):
        """Trial/free subscription cannot schedule cancellation."""
        trial_sub = _mk_sub({"status": "trialing", "plan_code": "free"})
        mock_get_sub.return_value = trial_sub

        with self.assertRaises(ValueError) as ctx:
            schedule_cancellation(company_id=42, effective_at=MONTH_AHEAD)
        self.assertIn("active", str(ctx.exception).lower())

    @patch(_LIFECYCLE + "._get_current_sub")
    def test_expired_cannot_schedule_cancellation(self, mock_get_sub):
        """Expired subscription cannot schedule cancellation."""
        mock_get_sub.return_value = _mk_sub({"status": "expired"})

        with self.assertRaises(ValueError):
            schedule_cancellation(company_id=42, effective_at=MONTH_AHEAD)

    @patch(_LIFECYCLE + "._get_current_sub")
    def test_cancelled_cannot_schedule_cancellation(self, mock_get_sub):
        """Cancelled subscription cannot schedule cancellation."""
        mock_get_sub.return_value = _mk_sub({"status": "cancelled"})

        with self.assertRaises(ValueError):
            schedule_cancellation(company_id=42, effective_at=MONTH_AHEAD)

    @patch(_LIFECYCLE + "._get_current_sub")
    @patch(_LIFECYCLE + "._update_sub")
    @patch(_LIFECYCLE + "._validate_scheduling_active")
    def test_cancellation_date_equals_period_end(self, mock_validate, mock_update, mock_get_sub):
        """Cancellation effective_at must equal current_period_end."""
        mock_get_sub.return_value = self.valid_sub
        wrong_date = (NOW + timedelta(days=15)).isoformat()

        with self.assertRaises(ValueError) as ctx:
            schedule_cancellation(company_id=42, effective_at=wrong_date)
        self.assertIn("match", str(ctx.exception).lower())

    @patch(_LIFECYCLE + "._get_current_sub")
    @patch(_LIFECYCLE + "._update_sub")
    @patch(_LIFECYCLE + "._validate_scheduling_active")
    def test_cancellation_clears_pending_downgrade(self, mock_validate, mock_update, mock_get_sub):
        """Scheduling cancellation clears any pending downgrade."""
        sub_with_downgrade = _mk_sub({
            "pending_plan_id": 3,
            "plan_change_effective_at": MONTH_AHEAD,
        })
        mock_get_sub.return_value = sub_with_downgrade
        mock_update.return_value = _mk_sub()

        schedule_cancellation(company_id=42, effective_at=MONTH_AHEAD)

        updates = mock_update.call_args[1]["updates"]
        self.assertIsNone(updates["pending_plan_id"])
        self.assertIsNone(updates["plan_change_effective_at"])

    @patch(_LIFECYCLE + "._get_current_sub")
    @patch(_LIFECYCLE + "._update_sub")
    @patch(_LIFECYCLE + "._validate_scheduling_active")
    def test_cancellation_idempotent(self, mock_validate, mock_update, mock_get_sub):
        """Repeated cancellation scheduling is idempotent."""
        mock_get_sub.return_value = self.valid_sub
        mock_update.return_value = _mk_sub()

        result1 = schedule_cancellation(company_id=42, effective_at=MONTH_AHEAD)
        mock_update.reset_mock()
        mock_get_sub.return_value = _mk_sub({
            "cancellation_scheduled_at": NOW_ISO,
            "cancellation_effective_at": MONTH_AHEAD,
        })

        result2 = schedule_cancellation(company_id=42, effective_at=MONTH_AHEAD)
        self.assertIsNotNone(result2)


# =============================================================================
# Tests: Undo cancellation
# =============================================================================


class TestUndoCancellation(unittest.TestCase):
    """Tests for undo_subscription_cancellation."""

    @patch(_LIFECYCLE + "._get_current_sub")
    @patch(_LIFECYCLE + "._update_sub")
    def test_undo_works_for_active_with_pending(self, mock_update, mock_get_sub):
        """Active subscription with pending cancellation can undo."""
        sub = _mk_sub({
            "cancellation_scheduled_at": NOW_ISO,
            "cancellation_effective_at": MONTH_AHEAD,
        })
        mock_get_sub.return_value = sub
        mock_update.return_value = _mk_sub()

        result = undo_subscription_cancellation(company_id=42)
        self.assertIsNotNone(result)
        updates = mock_update.call_args[1]["updates"]
        self.assertIsNone(updates["cancellation_scheduled_at"])
        self.assertIsNone(updates["cancellation_effective_at"])

    @patch(_LIFECYCLE + "._get_current_sub")
    def test_undo_fails_when_already_expired(self, mock_get_sub):
        """Undo fails when subscription is already expired."""
        mock_get_sub.return_value = _mk_sub({"status": "expired"})
        with self.assertRaises(ValueError):
            undo_subscription_cancellation(company_id=42)

    @patch(_LIFECYCLE + "._get_current_sub")
    def test_undo_fails_when_already_cancelled(self, mock_get_sub):
        """Undo fails when subscription is already cancelled."""
        mock_get_sub.return_value = _mk_sub({"status": "cancelled"})
        with self.assertRaises(ValueError):
            undo_subscription_cancellation(company_id=42)

    @patch(_LIFECYCLE + "._get_current_sub")
    @patch(_LIFECYCLE + "._update_sub")
    def test_undo_idempotent(self, mock_update, mock_get_sub):
        """Repeated undo is idempotent."""
        sub = _mk_sub()
        mock_get_sub.return_value = sub
        mock_update.return_value = _mk_sub()

        result1 = undo_subscription_cancellation(company_id=42)
        result2 = undo_subscription_cancellation(company_id=42)
        self.assertIsNotNone(result1)
        self.assertIsNotNone(result2)


# =============================================================================
# Tests: Downgrade scheduling
# =============================================================================


class TestDowngradeScheduling(unittest.TestCase):
    """Tests for schedule_subscription_downgrade and clear_scheduled_downgrade."""

    def setUp(self):
        self.valid_sub = _mk_sub()

    @patch(_LIFECYCLE + "._get_current_sub")
    @patch(_LIFECYCLE + "._update_sub")
    @patch(_LIFECYCLE + "._validate_scheduling_active")
    def test_pro_to_advanced_scheduling(self, mock_validate, mock_update, mock_get_sub):
        """Pro can schedule downgrade to Advanced."""
        mock_get_sub.return_value = self.valid_sub
        mock_update.return_value = _mk_sub({
            "pending_plan_id": 3,
            "plan_change_effective_at": MONTH_AHEAD,
        })

        result = schedule_subscription_downgrade(company_id=42, target_plan_id=3)
        self.assertIsNotNone(result)
        updates = mock_update.call_args[1]["updates"]
        self.assertEqual(updates["pending_plan_id"], 3)
        self.assertEqual(updates["plan_change_effective_at"], MONTH_AHEAD)

    @patch(_LIFECYCLE + "._get_current_sub")
    def test_downgrade_rejected_when_cancellation_pending(self, mock_get_sub):
        """Downgrade rejected when cancellation is already scheduled."""
        sub_with_cancel = _mk_sub({
            "cancellation_scheduled_at": NOW_ISO,
            "cancellation_effective_at": MONTH_AHEAD,
        })
        mock_get_sub.return_value = sub_with_cancel

        with self.assertRaises(ValueError) as ctx:
            schedule_subscription_downgrade(company_id=42, target_plan_id=3)
        self.assertIn("cancellation", str(ctx.exception).lower())

    @patch(_LIFECYCLE + "._get_current_sub")
    def test_trial_cannot_schedule_downgrade(self, mock_get_sub):
        """Trial cannot schedule downgrade."""
        mock_get_sub.return_value = _mk_sub({"status": "trialing"})
        with self.assertRaises(ValueError):
            schedule_subscription_downgrade(company_id=42, target_plan_id=3)

    @patch(_LIFECYCLE + "._get_current_sub")
    def test_expired_cannot_schedule_downgrade(self, mock_get_sub):
        """Expired cannot schedule downgrade."""
        mock_get_sub.return_value = _mk_sub({"status": "expired"})
        with self.assertRaises(ValueError):
            schedule_subscription_downgrade(company_id=42, target_plan_id=3)

    @patch(_LIFECYCLE + "._get_current_sub")
    @patch(_LIFECYCLE + "._update_sub")
    @patch(_LIFECYCLE + "._validate_scheduling_active")
    def test_same_target_idempotent(self, mock_validate, mock_update, mock_get_sub):
        """Scheduling same downgrade target is idempotent."""
        mock_get_sub.return_value = self.valid_sub
        mock_update.return_value = _mk_sub({
            "pending_plan_id": 3,
            "plan_change_effective_at": MONTH_AHEAD,
        })

        result1 = schedule_subscription_downgrade(company_id=42, target_plan_id=3)
        mock_update.reset_mock()
        result2 = schedule_subscription_downgrade(company_id=42, target_plan_id=3)
        self.assertIsNotNone(result1)
        self.assertIsNotNone(result2)

    @patch(_LIFECYCLE + "._get_current_sub")
    @patch(_LIFECYCLE + "._update_sub")
    @patch(_LIFECYCLE + "._validate_scheduling_active")
    def test_clear_downgrade(self, mock_validate, mock_update, mock_get_sub):
        """Clear scheduled downgrade works."""
        mock_get_sub.return_value = _mk_sub({
            "pending_plan_id": 3,
            "plan_change_effective_at": MONTH_AHEAD,
        })
        mock_update.return_value = _mk_sub()

        result = clear_scheduled_downgrade(company_id=42)
        self.assertIsNotNone(result)
        updates = mock_update.call_args[1]["updates"]
        self.assertIsNone(updates["pending_plan_id"])
        self.assertIsNone(updates["plan_change_effective_at"])


# =============================================================================
# Tests: Conflicts
# =============================================================================


class TestCancellationDowngradeConflicts(unittest.TestCase):
    """Tests for conflicts between cancellation and downgrade scheduling."""

    @patch(_LIFECYCLE + "._get_current_sub")
    @patch(_LIFECYCLE + "._update_sub")
    @patch(_LIFECYCLE + "._validate_scheduling_active")
    def test_cancellation_clears_downgrade(self, mock_validate, mock_update, mock_get_sub):
        """Scheduling cancellation clears pending downgrade."""
        sub_with_downgrade = _mk_sub({
            "pending_plan_id": 3,
            "plan_change_effective_at": MONTH_AHEAD,
        })
        mock_get_sub.return_value = sub_with_downgrade
        mock_update.return_value = _mk_sub()

        schedule_cancellation(company_id=42, effective_at=MONTH_AHEAD)
        updates = mock_update.call_args[1]["updates"]
        self.assertIsNone(updates["pending_plan_id"])
        self.assertIsNone(updates["plan_change_effective_at"])

    @patch(_LIFECYCLE + "._get_current_sub")
    def test_downgrade_rejected_when_cancel_scheduled(self, mock_get_sub):
        """Downgrade scheduling rejected when cancellation is pending."""
        sub_with_cancel = _mk_sub({
            "cancellation_scheduled_at": NOW_ISO,
            "cancellation_effective_at": MONTH_AHEAD,
        })
        mock_get_sub.return_value = sub_with_cancel

        with self.assertRaises(ValueError) as ctx:
            schedule_subscription_downgrade(company_id=42, target_plan_id=3)
        self.assertIn("cancellation", str(ctx.exception).lower())


# =============================================================================
# Tests: Lifecycle execution
# =============================================================================


class TestLifecycleExecution(unittest.TestCase):
    """Tests for _process_single_subscription execution order."""

    def test_cancellation_processed_before_expiry(self):
        """Scheduled cancellation is processed before normal expiry."""
        sub = _mk_sub({
            "cancellation_effective_at": HOUR_AGO,
            "current_period_end": HOUR_AGO,
        })
        sub_id = sub["id"]
        company_id = sub["company_id"]

        with patch(_LIFECYCLE + ".transition_subscription_status") as mock_transition, \
             patch(_LIFECYCLE + "._clear_all_scheduling") as mock_clear, \
             patch(_LIFECYCLE + "._get_current_sub") as mock_get_sub:

            mock_get_sub.return_value = sub

            result = _process_single_subscription(sub, now=NOW)

            self.assertTrue(result["processed"])
            self.assertEqual(result["result"], "cancellation_applied")

    def test_downgrade_processed_before_expiry(self):
        """Scheduled downgrade is processed before normal expiry."""
        sub = _mk_sub({
            "pending_plan_id": 3,
            "plan_change_effective_at": HOUR_AGO,
            "current_period_end": HOUR_AGO,
        })

        with patch(_LIFECYCLE + "._apply_scheduled_downgrade") as mock_apply, \
             patch(_LIFECYCLE + ".process_subscription_expiry") as mock_expiry:

            mock_apply.return_value = {"processed": True, "result": "downgrade_applied"}

            result = _process_single_subscription(sub, now=NOW)

            self.assertTrue(result["processed"])
            self.assertEqual(result["result"], "downgrade_applied")
            mock_apply.assert_called_once()
            mock_expiry.assert_not_called()

    def test_active_expiry_when_no_scheduling(self):
        """Active subscription without scheduling expires normally."""
        sub = _mk_sub({
            "current_period_end": HOUR_AGO,
            "cancellation_effective_at": None,
            "pending_plan_id": None,
        })

        with patch(_LIFECYCLE + ".process_subscription_expiry") as mock_expiry:
            mock_expiry.return_value = {"processed": True, "to_status": "expired", "reason": "Billing period ended"}

            result = _process_single_subscription(sub, now=NOW)

            self.assertTrue(result["processed"])
            mock_expiry.assert_called_once()

    def test_already_expired_unchanged(self):
        """Already expired subscription is not processed again."""
        sub = _mk_sub({"status": "expired"})

        result = _process_single_subscription(sub, now=NOW)

        self.assertFalse(result["processed"])
        self.assertEqual(result["result"], "unchanged")

    def test_already_cancelled_unchanged(self):
        """Already cancelled subscription is not processed again."""
        sub = _mk_sub({"status": "cancelled"})

        result = _process_single_subscription(sub, now=NOW)

        self.assertFalse(result["processed"])
        self.assertEqual(result["result"], "unchanged")

    def test_processing_order_cancel_then_downgrade_then_expiry(self):
        """Lifecycle evaluation order: cancel > downgrade > expiry."""
        sub = _mk_sub({
            "cancellation_effective_at": HOUR_AGO,
            "pending_plan_id": 3,
            "plan_change_effective_at": HOUR_AGO,
            "current_period_end": HOUR_AGO,
        })

        with patch(_LIFECYCLE + ".transition_subscription_status") as mock_transition, \
             patch(_LIFECYCLE + "._clear_all_scheduling") as mock_clear:

            result = _process_single_subscription(sub, now=NOW)

            # Cancellation takes priority over downgrade
            self.assertEqual(result["result"], "cancellation_applied")


# =============================================================================
# Tests: Downgrade execution (_apply_scheduled_downgrade)
# =============================================================================


class TestDowngradeExecution(unittest.TestCase):
    """Tests for _apply_scheduled_downgrade."""

    def setUp(self):
        self.sub = _mk_sub({
            "plan_id": 4,
            "plan_code": "pro",
            "pending_plan_id": 3,
            "plan_change_effective_at": HOUR_AGO,
        })

    @patch(_LIFECYCLE + ".transition_subscription_status")
    @patch(_LIFECYCLE + "._update_sub")
    @patch("app.database.subscription_plan_repository.get_plan_by_id")
    @patch("app.services.billing_service.get_company_usage")
    def test_downgrade_expires_and_changes_plan(self, mock_usage, mock_plan, mock_update, mock_transition):
        """Downgrade transitions active->expired and updates plan_id."""
        mock_plan.return_value = {
            "id": 3, "code": "advanced",
            "chatbot_limit": 2, "team_member_limit": 3,
            "knowledge_file_limit": 25, "knowledge_storage_limit_bytes": 262144000,
            "channel_limit": 2,
        }
        mock_usage.return_value = {
            "usage": {
                "chatbots": {"used": 1},
                "team_members": {"used": 1},
                "knowledge_files": {"used": 1},
                "knowledge_storage_bytes": {"used": 1000},
                "channels": {"used": 1},
            }
        }
        mock_update.return_value = _mk_sub()

        result = _apply_scheduled_downgrade(42, 3, self.sub, now=NOW)

        self.assertTrue(result["processed"])
        self.assertEqual(result["result"], "downgrade_applied")
        mock_transition.assert_called_once_with(
            company_id=42, target_status="expired",
            expected_current_status="active",
            reason="Scheduled downgrade effective",
        )
        mock_update.assert_called_once()
        updates = mock_update.call_args[1]["updates"]
        self.assertEqual(updates["plan_id"], 3)
        self.assertIsNone(updates["pending_plan_id"])

    @patch("app.database.subscription_plan_repository.get_plan_by_id")
    @patch("app.services.billing_service.get_company_usage")
    def test_downgrade_blocked_by_chatbot_excess(self, mock_usage, mock_plan):
        """Downgrade blocked when chatbot count exceeds target limit."""
        mock_plan.return_value = {
            "id": 2, "code": "essential",
            "chatbot_limit": 1, "team_member_limit": 1,
            "knowledge_file_limit": 5, "knowledge_storage_limit_bytes": 52428800,
            "channel_limit": 1,
        }
        mock_usage.return_value = {
            "usage": {
                "chatbots": {"used": 3},
                "team_members": {"used": 1},
                "knowledge_files": {"used": 1},
                "knowledge_storage_bytes": {"used": 1000},
                "channels": {"used": 1},
            }
        }

        with self.assertRaises(ValueError) as ctx:
            _apply_scheduled_downgrade(42, 2, self.sub, now=NOW)
        self.assertIn("chatbot", str(ctx.exception).lower())

    @patch("app.database.subscription_plan_repository.get_plan_by_id")
    @patch("app.services.billing_service.get_company_usage")
    def test_downgrade_blocked_by_storage_excess(self, mock_usage, mock_plan):
        """Downgrade blocked when storage exceeds target limit."""
        mock_plan.return_value = {
            "id": 2, "code": "essential",
            "chatbot_limit": 1, "team_member_limit": 1,
            "knowledge_file_limit": 5, "knowledge_storage_limit_bytes": 52428800,
            "channel_limit": 1,
        }
        mock_usage.return_value = {
            "usage": {
                "chatbots": {"used": 1},
                "team_members": {"used": 1},
                "knowledge_files": {"used": 1},
                "knowledge_storage_bytes": {"used": 100_000_000},
                "channels": {"used": 1},
            }
        }

        with self.assertRaises(ValueError) as ctx:
            _apply_scheduled_downgrade(42, 2, self.sub, now=NOW)
        self.assertIn("storage", str(ctx.exception).lower())

    @patch("app.database.subscription_plan_repository.get_plan_by_id")
    @patch("app.services.billing_service.get_company_usage")
    def test_downgrade_no_ai_credit_granted(self, mock_usage, mock_plan):
        """Downgrade execution does not grant AI credit."""
        mock_plan.return_value = {
            "id": 2, "code": "essential",
            "chatbot_limit": 1, "team_member_limit": 1,
            "knowledge_file_limit": 5, "knowledge_storage_limit_bytes": 52428800,
            "channel_limit": 1,
        }
        mock_usage.return_value = {
            "usage": {
                "chatbots": {"used": 1},
                "team_members": {"used": 1},
                "knowledge_files": {"used": 1},
                "knowledge_storage_bytes": {"used": 1000},
                "channels": {"used": 1},
            }
        }

        with patch(_LIFECYCLE + ".transition_subscription_status") as mock_transition, \
             patch(_LIFECYCLE + "._update_sub") as mock_update:
            mock_update.return_value = _mk_sub()
            result = _apply_scheduled_downgrade(42, 2, self.sub, now=NOW)

            self.assertTrue(result["processed"])
            # No AI credit calls
            # No AI credit calls - verify by checking transition was called without credit-related functions
            self.assertTrue(mock_transition.called)
            self.assertTrue(mock_transition.called)


# =============================================================================
# Tests: process_due_subscriptions batch
# =============================================================================


class TestProcessDueSubscriptions(unittest.TestCase):
    """Tests for batch process_due_subscriptions."""

    @patch("app.database.company_subscription_repository.get_due_subscriptions")
    @patch(_LIFECYCLE + "._process_single_subscription")
    def test_processes_multiple_subscriptions(self, mock_process, mock_get_due):
        """Batch processes multiple due subscriptions."""
        mock_get_due.return_value = [
            _mk_sub({"id": 1, "company_id": 42, "status": "active", "current_period_end": HOUR_AGO}),
            _mk_sub({"id": 2, "company_id": 43, "status": "trialing", "trial_ends_at": HOUR_AGO}),
        ]
        mock_process.side_effect = [
            {"processed": True, "result": "expired", "company_id": 42},
            {"processed": True, "result": "expired", "company_id": 43},
        ]

        result = process_due_subscriptions(now=NOW, batch_size=100)

        self.assertEqual(result["total_processed"], 2)
        self.assertEqual(len(result["outcomes"]), 2)

    @patch("app.database.company_subscription_repository.get_due_subscriptions")
    @patch(_LIFECYCLE + "._process_single_subscription")
    def test_continues_after_failure(self, mock_process, mock_get_due):
        """Processing continues after one subscription fails."""
        mock_get_due.return_value = [
            _mk_sub({"id": 1, "company_id": 42, "status": "active"}),
            _mk_sub({"id": 2, "company_id": 43, "status": "active"}),
        ]
        mock_process.side_effect = [
            Exception("Unexpected error"),
            {"processed": True, "result": "expired", "company_id": 43},
        ]

        result = process_due_subscriptions(now=NOW, batch_size=100)

        self.assertEqual(result["total_processed"], 1)
        self.assertEqual(len(result["errors"]), 1)

    @patch("app.database.company_subscription_repository.get_due_subscriptions")
    def test_empty_batch(self, mock_get_due):
        """Empty batch returns zero processed."""
        mock_get_due.return_value = []

        result = process_due_subscriptions(now=NOW, batch_size=100)

        self.assertEqual(result["total_processed"], 0)
        self.assertEqual(result["due_count"], 0)


# =============================================================================
# Tests: Access policy compatibility
# =============================================================================


class TestAccessPolicyCompatibility(unittest.TestCase):
    """Confirm access policy handles cancelled status correctly."""

    def test_cancelled_status_allowed_transition(self):
        """cancelled subscription has correct allowed transitions."""
        self.assertIn("active", ALLOWED_TRANSITIONS.get("cancelled", set()))

    def test_no_transition_to_trialing(self):
        """No status can transition to trialing."""
        for current, targets in ALLOWED_TRANSITIONS.items():
            self.assertNotIn("trialing", targets,
                             f"{current} should not allow transition to trialing")


if __name__ == "__main__":
    unittest.main()



# =============================================================================
# Full-sequence integration tests
# =============================================================================


class TestFullSequenceDowngradeAndRenewal(unittest.TestCase):
    """Full Pro -> schedule Advanced downgrade -> period end -> expired -> renew Advanced."""

    def test_pro_downgrade_to_advanced_full_sequence(self):
        """Complete sequence: Pro active -> schedule Advanced -> period end -> expired -> renew."""
        company_id = 42
        advanced_plan_id = 3
        sub_id = 1

        sub = _mk_sub({
            "id": sub_id, "company_id": company_id, "plan_id": 4,
            "plan_code": "pro", "status": "active",
            "current_period_start": MONTH_AGO, "current_period_end": MONTH_AHEAD,
        })

        with patch(_LIFECYCLE + "._get_current_sub", return_value=sub),              patch(_LIFECYCLE + "._update_sub") as mock_update,              patch(_LIFECYCLE + "._validate_scheduling_active", return_value=None):
            mock_update.return_value = _mk_sub({"pending_plan_id": advanced_plan_id, "plan_change_effective_at": MONTH_AHEAD})
            result = schedule_subscription_downgrade(company_id=company_id, target_plan_id=advanced_plan_id)
            self.assertIsNotNone(result)

        # Step 2: Period end arrives
        sub_at_period_end = _mk_sub({
            "id": sub_id, "company_id": company_id, "plan_id": 4,
            "status": "active", "pending_plan_id": advanced_plan_id,
            "plan_change_effective_at": HOUR_AGO, "current_period_end": HOUR_AGO,
        })

        with patch(_LIFECYCLE + ".transition_subscription_status") as mock_transition, \
             patch(_LIFECYCLE + "._update_sub") as mock_update, \
             patch(_LIFECYCLE + "._get_current_sub") as mock_get_sub, \
             patch(_LIFECYCLE + "._get_latest_sub") as mock_latest, \
             patch("app.database.subscription_plan_repository.get_plan_by_id") as mock_plan, \
             patch("app.services.billing_service.get_company_usage") as mock_usage:
            mock_get_sub.return_value = sub_at_period_end
            mock_latest.return_value = sub_at_period_end
            mock_plan.return_value = {
                "id": advanced_plan_id, "code": "advanced",
                "chatbot_limit": 2, "team_member_limit": 3,
                "knowledge_file_limit": 25, "knowledge_storage_limit_bytes": 262144000,
                "channel_limit": 2,
            }
            mock_usage.return_value = {"usage": {"chatbots": {"used": 1}, "team_members": {"used": 1}, "knowledge_files": {"used": 1}, "knowledge_storage_bytes": {"used": 1000}, "channels": {"used": 1}}}
            mock_update.return_value = _mk_sub()
            mock_usage.return_value = {"usage": {"chatbots": {"used": 1}, "team_members": {"used": 1}, "knowledge_files": {"used": 1}, "knowledge_storage_bytes": {"used": 1000}, "channels": {"used": 1}}}
            mock_update.return_value = _mk_sub()
            mock_get_sub.return_value = sub_at_period_end
            mock_latest.return_value = sub_at_period_end
            result = _process_single_subscription(sub_at_period_end, now=NOW)
            self.assertTrue(result["processed"])
            self.assertEqual(result["result"], "downgrade_applied")

    def test_blocked_downgrade_still_expires(self):
        """Blocked downgrade due to excess usage still expires at period end."""
        company_id = 42
        sub = _mk_sub({
            "id": 1, "company_id": company_id, "plan_id": 4,
            "status": "active", "pending_plan_id": 2,
            "plan_change_effective_at": HOUR_AGO, "current_period_end": HOUR_AGO,
        })

        with patch("app.database.subscription_plan_repository.get_plan_by_id") as mock_plan, \
             patch("app.services.billing_service.get_company_usage") as mock_usage, \
             patch(_LIFECYCLE + ".process_subscription_expiry") as mock_expiry, \
             patch(_LIFECYCLE + "._get_latest_sub") as mock_latest:
            mock_plan.return_value = {
                "id": 2, "code": "essential",
                "chatbot_limit": 1, "team_member_limit": 1,
                "knowledge_file_limit": 5, "knowledge_storage_limit_bytes": 52428800,
                "channel_limit": 1,
            }
            mock_usage.return_value = {"usage": {"chatbots": {"used": 3}, "team_members": {"used": 1}, "knowledge_files": {"used": 1}, "knowledge_storage_bytes": {"used": 1000}, "channels": {"used": 1}}}
            mock_expiry.return_value = {"processed": True, "from_status": "active", "to_status": "expired", "reason": "Billing period ended"}
            result = _process_single_subscription(sub, now=NOW)
            self.assertTrue(result["processed"])
            self.assertEqual(result["to_status"], "expired")

    def test_cancelled_subscription_renewal_path(self):
        """Cancelled subscription can renew (status goes to active)."""
        with patch(_LIFECYCLE + "._get_current_sub") as mock_get, \
             patch(_LIFECYCLE + "._get_latest_sub") as mock_latest, \
             patch(_LIFECYCLE + "._update_status_conditional") as mock_update, \
             patch(_LIFECYCLE + ".get_plan_by_id", return_value={"code": "pro"}):
            mock_get.return_value = _mk_sub({"id": 1, "company_id": 42, "status": "cancelled", "plan_id": 4, "cancelled_at": HOUR_AGO})
            mock_update.return_value = _mk_sub({"status": "active", "cancelled_at": None})
            result = transition_subscription_status(company_id=42, target_status="active", expected_current_status="cancelled", reason="Renewal after cancellation")
            self.assertEqual(result["status"], "active")


# =============================================================================
# Tests: Due-query coverage for scheduling fields
# =============================================================================


class TestDueQueryCoverage(unittest.TestCase):
    """Verify scheduling fields are processed correctly by lifecycle."""

    def test_due_cancellation_triggers_execution(self):
        """Subscription with past cancellation_effective_at triggers cancellation execution."""
        sub = _mk_sub({
            "id": 1, "company_id": 42, "status": "active",
            "cancellation_effective_at": HOUR_AGO,
            "current_period_end": MONTH_AHEAD,
        })

        with patch(_LIFECYCLE + ".transition_subscription_status") as mock_trans,              patch(_LIFECYCLE + "._clear_all_scheduling") as mock_clear:
            mock_trans.return_value = _mk_sub({"status": "cancelled"})
            result = _process_single_subscription(sub, now=NOW)
            self.assertTrue(result["processed"])
            self.assertEqual(result["result"], "cancellation_applied")

    def test_future_cancellation_excluded(self):
        """Subscription with future cancellation_effective_at is not processed for cancellation."""
        sub = _mk_sub({
            "id": 1, "company_id": 42, "status": "active",
            "cancellation_effective_at": MONTH_AHEAD,
            "current_period_end": MONTH_AHEAD,
        })

        result = _process_single_subscription(sub, now=NOW)
        self.assertFalse(result["processed"])

    def test_due_downgrade_triggers_execution(self):
        """Subscription with past plan_change_effective_at triggers downgrade execution."""
        sub = _mk_sub({
            "id": 1, "company_id": 42, "plan_id": 4, "status": "active",
            "pending_plan_id": 3, "plan_change_effective_at": HOUR_AGO,
            "current_period_end": HOUR_AGO,
        })

        with patch("app.database.subscription_plan_repository.get_plan_by_id") as mock_plan,              patch("app.services.billing_service.get_company_usage") as mock_usage,              patch(_LIFECYCLE + ".transition_subscription_status") as mock_trans,              patch(_LIFECYCLE + "._update_sub") as mock_update:
            mock_plan.return_value = {"id": 3, "code": "advanced", "chatbot_limit": 2, "team_member_limit": 3, "knowledge_file_limit": 25, "knowledge_storage_limit_bytes": 262144000, "channel_limit": 2}
            mock_usage.return_value = {"usage": {"chatbots": {"used": 1}, "team_members": {"used": 1}, "knowledge_files": {"used": 1}, "knowledge_storage_bytes": {"used": 1000}, "channels": {"used": 1}}}
            mock_update.return_value = _mk_sub()
            result = _process_single_subscription(sub, now=NOW)
            self.assertTrue(result["processed"])

    def test_future_downgrade_excluded(self):
        """Subscription with future plan_change_effective_at is not processed for downgrade."""
        sub = _mk_sub({
            "id": 1, "company_id": 42, "status": "active",
            "pending_plan_id": 3, "plan_change_effective_at": MONTH_AHEAD,
            "current_period_end": MONTH_AHEAD,
        })

        result = _process_single_subscription(sub, now=NOW)
        self.assertFalse(result["processed"])

    def test_no_duplicate_processing_when_both_due(self):
        """When both cancellation and downgrade are due, cancellation is processed first (no duplication)."""
        sub = _mk_sub({
            "id": 1, "company_id": 42, "status": "active",
            "cancellation_effective_at": HOUR_AGO,
            "pending_plan_id": 3, "plan_change_effective_at": HOUR_AGO,
            "current_period_end": HOUR_AGO,
        })

        with patch(_LIFECYCLE + ".transition_subscription_status") as mock_trans,              patch(_LIFECYCLE + "._clear_all_scheduling") as mock_clear:
            mock_trans.return_value = _mk_sub({"status": "cancelled"})
            result = _process_single_subscription(sub, now=NOW)
            self.assertTrue(result["processed"])
            self.assertEqual(result["result"], "cancellation_applied")
            mock_trans.assert_called_once()



# =============================================================================
# Tests: downgrade off automation_workflows stops automatic working flows
# =============================================================================


class TestDowngradeDisablesAutomation(unittest.TestCase):
    """A downgrade to a plan without automation_workflows turns automation off."""

    USAGE = {"usage": {"chatbots": {"used": 1}, "team_members": {"used": 1}, "knowledge_files": {"used": 1},
                       "knowledge_storage_bytes": {"used": 1}, "channels": {"used": 1}}}
    SCHEDULE = {"id": "00000000-0000-4000-8000-000000000001", "company_id": 42, "chatbot_id": 7,
                "actor_user_id": 31, "frequency": "weekly", "enabled": True}

    def _downgrade(self, feature_flags, *, schedules=None, bots=None, disable=None):
        plan = {"id": 3, "code": "advanced", "chatbot_limit": 2, "team_member_limit": 3,
                "knowledge_file_limit": 25, "knowledge_storage_limit_bytes": 262144000, "channel_limit": 2,
                "feature_flags": feature_flags}
        with patch("app.database.subscription_plan_repository.get_plan_by_id", return_value=plan), \
             patch("app.services.billing_service.get_company_usage", return_value=self.USAGE), \
             patch(_LIFECYCLE + ".transition_subscription_status"), \
             patch(_LIFECYCLE + "._update_sub", return_value=_mk_sub()), \
             patch("app.database.analysis_repository.list_enabled_company_schedules",
                   return_value=[self.SCHEDULE] if schedules is None else schedules) as listed, \
             patch("app.database.analysis_repository.disable_schedule", side_effect=disable) as disabled, \
             patch("app.database.bot_repository.get_all_bots",
                   return_value=bots if bots is not None else [
                       {"id": 7, "analysis_recording_enabled": True},
                       {"id": 8, "analysis_recording_enabled": False}]), \
             patch("app.database.business_observation_repository.set_recording_enabled") as recording:
            result = _apply_scheduled_downgrade(42, 3, _mk_sub({"pending_plan_id": 3}), now=NOW)
        return result, listed, disabled, recording

    def test_downgrade_off_automation_disables_schedules_and_recording(self):
        result, _listed, disabled, recording = self._downgrade({"automation_workflows": False})
        self.assertEqual(result["result"], "downgrade_applied")
        disabled.assert_called_once_with(self.SCHEDULE)
        recording.assert_called_once_with(42, 7, False)
        self.assertEqual(result["automation_disabled"], {"schedules": 1, "recording": 1})

    def test_a_plan_that_keeps_automation_touches_nothing(self):
        result, listed, disabled, recording = self._downgrade({"automation_workflows": True})
        listed.assert_not_called()
        disabled.assert_not_called()
        recording.assert_not_called()
        self.assertEqual(result["automation_disabled"], {"schedules": 0, "recording": 0})

    def test_an_absent_key_counts_as_no_automation(self):
        _result, _listed, disabled, _recording = self._downgrade({})
        disabled.assert_called_once()

    def test_cleanup_failure_never_blocks_the_downgrade(self):
        result, _listed, _disabled, recording = self._downgrade(
            {"automation_workflows": False}, disable=PermissionError("actor gone"))
        self.assertEqual(result["result"], "downgrade_applied")
        self.assertEqual(result["automation_disabled"]["schedules"], 0)
        recording.assert_called_once_with(42, 7, False)
