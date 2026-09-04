"""test_subscription_expiry_and_renewal.py

Unit tests for Phase 4B: subscription expiry processing and renewal behavior.
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
from unittest.mock import patch, MagicMock, PropertyMock
import types
from datetime import datetime, timezone, timedelta

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
_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
_sb.rpc.return_value.execute.return_value = MagicMock(data=[])

with patch("app.database.db.supabase", _sb):
    from app.services.subscription_lifecycle_service import (
        process_subscription_expiry,
        process_due_subscriptions,
        ALLOWED_TRANSITIONS,
    )
    from app.database.company_subscription_repository import (
        get_due_subscriptions,
        get_latest_company_subscription,
    )

NOW = datetime.now(timezone.utc)
NOW_ISO = NOW.isoformat()

HOUR_AGO = (NOW - timedelta(hours=1)).isoformat()
HOUR_AHEAD = (NOW + timedelta(hours=1)).isoformat()

MONTH_AGO = (NOW - timedelta(days=31)).isoformat()
MONTH_AHEAD = (NOW + timedelta(days=31)).isoformat()


def _mk_sub(overrides=None):
    """Create a minimal subscription dict."""
    sub = {
        "id": 1,
        "company_id": 42,
        "plan_id": 2,
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


# =============================================================================
# Tests: get_due_subscriptions
# =============================================================================



class TestProcessSubscriptionExpiry(unittest.TestCase):
    """Tests for process_subscription_expiry."""

    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    @patch("app.services.subscription_lifecycle_service._update_status_conditional")
    def test_trial_expired(self, mock_update, mock_latest):
        """Trialing subscription with expired trial transitions to expired."""
        mock_latest.return_value = _mk_sub({
            "id": 1, "company_id": 42, "status": "trialing",
            "trial_ends_at": HOUR_AGO,
        })
        mock_update.return_value = _mk_sub({
            "id": 1, "company_id": 42, "status": "expired",
        })

        result = process_subscription_expiry(42, now=NOW)
        self.assertTrue(result["processed"])
        self.assertEqual(result["from_status"], "trialing")
        self.assertEqual(result["to_status"], "expired")
        self.assertEqual(result["reason"], "Trial period ended")
        mock_update.assert_called_once_with(
            subscription_id=1, company_id=42,
            expected_status="trialing", target_status="expired",
        )

    @patch("app.services.subscription_lifecycle_service.get_grace_period_days")
    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    @patch("app.services.subscription_lifecycle_service._update_status_conditional")
    def test_active_to_past_due_grace(self, mock_grace, mock_latest, mock_update):
        """Active subscription past period end transitions to past_due (grace period)."""
        mock_grace.return_value = 3
        mock_latest.return_value = _mk_sub({
            "id": 1, "company_id": 42, "status": "active",
            "current_period_end": HOUR_AGO,
        })
        mock_update.return_value = _mk_sub({
            "id": 1, "company_id": 42, "status": "past_due",
        })

        result = process_subscription_expiry(42, now=NOW)
        self.assertTrue(result["processed"])
        self.assertEqual(result["from_status"], "active")
        self.assertEqual(result["to_status"], "past_due")
        self.assertTrue(result["grace_period_used"])
        self.assertEqual(result["reason"], "Billing period ended; grace period started")

    @patch("app.services.subscription_lifecycle_service.get_grace_period_days")
    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    @patch("app.services.subscription_lifecycle_service._update_status_conditional")
    def test_past_due_expired_after_grace(self, mock_grace, mock_latest, mock_update):
        """Past_due subscription with expired grace period transitions to expired."""
        mock_grace.return_value = 3
        period_end = (NOW - timedelta(days=5)).isoformat()
        mock_latest.return_value = _mk_sub({
            "id": 1, "company_id": 42, "status": "past_due",
            "current_period_end": period_end,
        })
        mock_update.return_value = _mk_sub({
            "id": 1, "company_id": 42, "status": "expired",
        })

        result = process_subscription_expiry(42, now=NOW)
        self.assertTrue(result["processed"])
        self.assertEqual(result["from_status"], "past_due")
        self.assertEqual(result["to_status"], "expired")
        self.assertIn(result["reason"], ("Grace period ended", "Billing period ended"))
        self.assertTrue(result["processed"])

    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    def test_future_period_idempotent(self, mock_latest):
        """Active subscription with future period end is not expired."""
        mock_latest.return_value = _mk_sub({
            "id": 1, "company_id": 42, "status": "active",
            "current_period_end": HOUR_AHEAD,
        })
        result = process_subscription_expiry(42, now=NOW)
        self.assertFalse(result["processed"])
        self.assertTrue(result["idempotent"])

    @patch("app.database.company_subscription_order_repository.list_subscription_orders_for_company")
    @patch("app.services.subscription_lifecycle_service.get_plan_by_id")
    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    @patch("app.services.subscription_lifecycle_service._update_status_conditional")
    def test_active_free_with_expired_trial_transitions_to_expired(
        self,
        mock_update,
        mock_latest,
        mock_plan,
        mock_orders,
    ):
        """Legacy active Free rows with expired trial_ends_at are trial-expired."""
        mock_plan.return_value = {"id": 1, "code": "free"}
        mock_orders.return_value = []
        mock_latest.return_value = _mk_sub({
            "id": 1,
            "company_id": 42,
            "plan_id": 1,
            "status": "active",
            "trial_ends_at": HOUR_AGO,
            "current_period_end": MONTH_AHEAD,
        })
        mock_update.return_value = _mk_sub({"status": "expired"})

        result = process_subscription_expiry(42, now=NOW)

        self.assertTrue(result["processed"])
        self.assertEqual(result["from_status"], "active")
        self.assertEqual(result["to_status"], "expired")
        self.assertEqual(result["reason"], "Trial period ended")
        mock_update.assert_called_once_with(
            subscription_id=1,
            company_id=42,
            expected_status="active",
            target_status="expired",
        )

    @patch("app.database.company_subscription_order_repository.list_subscription_orders_for_company")
    @patch("app.services.subscription_lifecycle_service.get_plan_by_id")
    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    @patch("app.services.subscription_lifecycle_service._update_status_conditional")
    def test_active_free_expiry_deferred_for_live_payable_checkout(
        self,
        mock_update,
        mock_latest,
        mock_plan,
        mock_orders,
    ):
        """Lifecycle does not mutate source status under a live checkout."""
        sub = _mk_sub({
            "id": 5,
            "company_id": 29,
            "plan_id": 1,
            "status": "active",
            "trial_ends_at": HOUR_AGO,
            "current_period_start": MONTH_AGO,
            "current_period_end": MONTH_AHEAD,
        })
        mock_plan.return_value = {"id": 1, "code": "free"}
        mock_latest.return_value = sub
        mock_orders.return_value = [{
            "id": 15,
            "company_id": 29,
            "subscription_id": 5,
            "status": "pending",
            "activation_status": None,
            "reconciliation_required": False,
            "paid_at": None,
            "credited_at": None,
            "gateway_order_id": "bill-123",
            "checkout_url": "https://pay.example/checkout",
            "expires_at": HOUR_AHEAD,
            "source_plan_id": 1,
            "source_status": "active",
            "source_period_start": MONTH_AGO,
            "source_period_end": MONTH_AHEAD,
        }]

        result = process_subscription_expiry(29, now=NOW)

        self.assertFalse(result["processed"])
        self.assertTrue(result["idempotent"])
        self.assertTrue(result["protected_by_pending_checkout"])
        self.assertEqual(result["to_status"], "active")
        mock_update.assert_not_called()

    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    def test_already_expired_idempotent(self, mock_latest):
        """Already expired subscription returns idempotent."""
        mock_latest.return_value = _mk_sub({
            "id": 1, "company_id": 42, "status": "expired",
        })
        result = process_subscription_expiry(42, now=NOW)
        self.assertFalse(result["processed"])
        self.assertTrue(result["idempotent"])
        self.assertEqual(result["from_status"], "expired")

    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    def test_cancelled_idempotent(self, mock_latest):
        """Cancelled subscription returns idempotent (not transitioned)."""
        mock_latest.return_value = _mk_sub({
            "id": 1, "company_id": 42, "status": "cancelled",
        })
        result = process_subscription_expiry(42, now=NOW)
        self.assertFalse(result["processed"])
        self.assertTrue(result["idempotent"])

    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    def test_repeated_processing_idempotent(self, mock_latest):
        """Calling expiry twice on same subscription is idempotent."""
        mock_latest.return_value = _mk_sub({
            "id": 1, "company_id": 42, "status": "expired",
        })
        result1 = process_subscription_expiry(42, now=NOW)
        result2 = process_subscription_expiry(42, now=NOW)
        self.assertFalse(result1["processed"])
        self.assertFalse(result2["processed"])
        self.assertTrue(result1["idempotent"])
        self.assertTrue(result2["idempotent"])


# =============================================================================
# Tests: process_due_subscriptions
# =============================================================================

class TestProcessDueSubscriptions(unittest.TestCase):
    """Tests for batch process_due_subscriptions."""

    @patch("app.database.company_subscription_repository.get_due_subscriptions")
    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    @patch("app.services.subscription_lifecycle_service._update_status_conditional")
    def test_processes_due_subscriptions(self, mock_update, mock_latest, mock_due):
        """Batch processing processes all due subscriptions."""
        mock_due.return_value = [
            {"id": 1, "company_id": 1, "status": "trialing", "trial_ends_at": HOUR_AGO},
            {"id": 2, "company_id": 2, "status": "active", "current_period_end": HOUR_AGO},
        ]
        mock_latest.side_effect = [
            {"id": 1, "company_id": 1, "status": "trialing", "trial_ends_at": HOUR_AGO},
            {"id": 2, "company_id": 2, "status": "active", "current_period_end": HOUR_AGO},
        ]
        mock_update.return_value = {}

        result = process_due_subscriptions(now=NOW, batch_size=100)
        self.assertEqual(result["total_processed"], 2)
        self.assertEqual(len(result["errors"]), 0)

    @patch("app.database.company_subscription_repository.get_due_subscriptions")
    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    @patch("app.services.subscription_lifecycle_service._update_status_conditional")
    def test_continues_after_error(self, mock_update, mock_latest, mock_due):
        """Batch processing continues after a single company fails."""
        mock_due.return_value = [
            {"id": 1, "company_id": 1, "status": "active", "current_period_end": HOUR_AGO},
            {"id": 2, "company_id": 2, "status": "active", "current_period_end": HOUR_AGO},
        ]
        mock_latest.side_effect = [
            {"id": 1, "company_id": 1, "status": "active", "current_period_end": HOUR_AGO},
            ValueError("Simulated error"),
        ]

        result = process_due_subscriptions(now=NOW, batch_size=100)
        self.assertGreaterEqual(result["total_processed"], 0)
        self.assertIsInstance(result, dict)

    @patch("app.database.company_subscription_repository.get_due_subscriptions")
    def test_empty_due_returns_zero(self, mock_due):
        """No due subscriptions returns zero processed."""
        mock_due.return_value = []
        result = process_due_subscriptions(now=NOW, batch_size=100)
        self.assertEqual(result["total_processed"], 0)
        self.assertEqual(result["due_count"], 0)


# =============================================================================
# Tests: Transition validation
# =============================================================================

class TestTransitionValidation(unittest.TestCase):
    """Tests that allowed transitions are correct."""

    def test_trialing_to_expired_allowed(self):
        self.assertIn("expired", ALLOWED_TRANSITIONS["trialing"])

    def test_active_to_expired_allowed(self):
        self.assertIn("expired", ALLOWED_TRANSITIONS["active"])

    def test_past_due_to_expired_allowed(self):
        self.assertIn("expired", ALLOWED_TRANSITIONS["past_due"])

    def test_expired_not_to_trialing(self):
        self.assertNotIn("trialing", ALLOWED_TRANSITIONS.get("expired", set()))

    def test_cancelled_not_to_trialing(self):
        self.assertNotIn("trialing", ALLOWED_TRANSITIONS.get("cancelled", set()))


# =============================================================================
# Tests: Renewal checkout protections
# =============================================================================

class TestRenewalCheckout(unittest.TestCase):
    """Tests that checkout service allows renewal for expired/past_due."""

    @patch("app.database.company_subscription_order_repository.list_subscription_orders_for_company")
    @patch("app.services.subscription_checkout_service.get_subscription_order_by_activation_sequence_key")
    @patch("app.services.subscription_checkout_service.create_bill")
    @patch("app.services.subscription_checkout_service.ToyyibPayConfig")
    @patch("app.services.subscription_checkout_service.create_subscription_order")
    @patch("app.services.subscription_checkout_service.get_plan_by_code")
    @patch("app.services.subscription_checkout_service.get_current_subscription")
    @patch("app.services.subscription_checkout_service.update_subscription_order_status")
    def test_expired_can_renew(
        self, mock_update_status, mock_get_sub, mock_get_plan,
        mock_create_order, mock_config, mock_create_bill, mock_get_sequence,
        mock_list_orders
    ):
        mock_list_orders.return_value = []
        mock_get_sequence.return_value = None
        """Expired subscription can create checkout for same plan."""
        mock_get_sub.return_value = {
            "id": 1, "company_id": 42, "plan_id": 2, "status": "expired",
            "current_period_start": "2026-06-08T12:00:00Z",
            "current_period_end": "2026-07-08T12:00:00Z",
            "trial_ends_at": None,
            "plan": {"code": "essential", "name": "Essential"},
        }
        mock_get_plan.return_value = {"id": 2, "code": "essential", "is_active": True}
        mock_create_order.return_value = {"order_reference": "test-ref", "status": "pending"}
        mock_create_bill.return_value = {"billcode": "bill-001", "checkout_url": "https://pay.example.com/checkout"}
        mock_config.return_value = MagicMock()

        from app.services.subscription_checkout_service import create_subscription_checkout
        result = create_subscription_checkout(
            company_id=42, user_id=1, plan_code="essential",
            customer_name="Test", customer_email="test@example.com",
        )
        self.assertIsNotNone(result)
        # order_reference is auto-generated as UUID; verify structure
        self.assertIn("order_reference", result)
        self.assertIn("checkout_url", result)
        self.assertEqual(result["checkout_url"], "https://pay.example.com/checkout")

    @patch("app.services.subscription_checkout_service.create_bill")
    @patch("app.services.subscription_checkout_service.ToyyibPayConfig")
    @patch("app.services.subscription_checkout_service.create_subscription_order")
    @patch("app.services.subscription_checkout_service.get_plan_by_code")
    @patch("app.services.subscription_checkout_service.get_current_subscription")
    def test_active_same_plan_rejected(
        self, mock_get_sub, mock_get_plan,
        mock_create_order, mock_config, mock_create_bill
    ):
        """Active subscription cannot purchase same plan."""
        mock_get_sub.return_value = {
            "id": 1, "company_id": 42, "plan_id": 2, "status": "active",
            "plan": {"code": "essential", "name": "Essential"},
        }
        mock_get_plan.return_value = {"id": 2, "code": "essential", "is_active": True}

        from app.services.subscription_checkout_service import create_subscription_checkout
        with self.assertRaises(ValueError) as ctx:
            create_subscription_checkout(
                company_id=42, user_id=1, plan_code="essential",
                customer_name="Test", customer_email="test@example.com",
            )
        self.assertIn("already subscribed", str(ctx.exception).lower())


# =============================================================================
# Tests: Subscription API renewal fields
# =============================================================================

class TestSubscriptionAPIRenewalFields(unittest.TestCase):
    """Tests for can_renew and renewal_required fields."""

    @patch("app.services.billing_service.get_plan_by_id")
    def test_expired_has_renewal_fields(self, mock_plan):
        """Expired subscription returns can_renew=True, renewal_required=True."""
        mock_plan.return_value = {
            "id": 3, "code": "pro", "name": "Pro", "price": "169",
            "currency": "MYR", "billing_interval": "month",
            "chatbot_limit": 10, "team_member_limit": 5,
            "knowledge_file_limit": 75, "knowledge_storage_limit_bytes": 1000000000,
            "channel_limit": 10, "feature_flags": {},
            "included_ai_credit_micro_myr": 60000000, "model_access_tier": "premium",
        }
        with patch(
            "app.services.billing_service._get_company_subscription",
            return_value=None,
        ), patch(
            "app.services.billing_service._get_latest_company_subscription",
            return_value={
                "id": 1, "company_id": 42, "plan_id": 3, "status": "expired",
                "trial_ends_at": None, "cancelled_at": None, "ends_at": None,
                "payment_gateway": None, "created_at": NOW_ISO, "updated_at": NOW_ISO,
                "current_period_start": MONTH_AGO, "current_period_end": MONTH_AGO,
            },
        ):
            from app.services.billing_service import get_current_subscription
            sub = get_current_subscription(42)
            self.assertIsNotNone(sub)
            self.assertTrue(sub["can_renew"])
            self.assertTrue(sub["renewal_required"])
            self.assertEqual(sub["status"], "expired")
            self.assertEqual(sub["plan"]["code"], "pro")

    @patch("app.services.billing_service.get_plan_by_id")
    def test_active_no_renewal_required(self, mock_plan):
        """Active subscription returns can_renew=False, renewal_required=False."""
        mock_plan.return_value = {
            "id": 3, "code": "pro", "name": "Pro", "price": "169",
            "currency": "MYR", "billing_interval": "month",
            "chatbot_limit": 10, "team_member_limit": 5,
            "knowledge_file_limit": 75, "knowledge_storage_limit_bytes": 1000000000,
            "channel_limit": 10, "feature_flags": {},
            "included_ai_credit_micro_myr": 60000000, "model_access_tier": "premium",
        }
        with patch(
            "app.services.billing_service._get_company_subscription",
            return_value={
                "id": 1, "company_id": 42, "plan_id": 3, "status": "active",
                "trial_ends_at": None, "cancelled_at": None, "ends_at": None,
                "payment_gateway": None, "created_at": NOW_ISO, "updated_at": NOW_ISO,
                "current_period_start": MONTH_AGO, "current_period_end": MONTH_AHEAD,
            },
        ):
            from app.services.billing_service import get_current_subscription
            sub = get_current_subscription(42)
            self.assertIsNotNone(sub)
            self.assertFalse(sub["can_renew"])
            self.assertFalse(sub["renewal_required"])
            self.assertEqual(sub["status"], "active")


# =============================================================================
# Tests: Access enforcement for expired subscriptions
# =============================================================================

class TestExpiredAccessEnforcement(unittest.TestCase):
    """Tests that expired subscriptions are denied AI access."""

    def test_expired_denies_ai(self):
        """Expired status blocks AI generation."""
        from app.services.ai_access_policy import resolve_ai_access
        expired_sub = {
            "plan_id": 3, "status": "expired",
        }
        with patch(
            "app.services.ai_access_policy._get_company_subscription",
            return_value=expired_sub,
        ), patch(
            "app.services.ai_access_policy.get_plan_by_id",
            return_value={"code": "pro", "name": "Pro"},
        ):
            policy = resolve_ai_access(42)
            self.assertFalse(policy.allowed)
            self.assertIn("expired", policy.denial_reason.lower())

    def test_expired_plan_code_preserved(self):
        """Expired subscription retains its paid plan code."""
        from app.services.ai_access_policy import resolve_ai_access
        expired_sub = {
            "plan_id": 3, "status": "expired",
        }
        with patch(
            "app.services.ai_access_policy._get_company_subscription",
            return_value=expired_sub,
        ), patch(
            "app.services.ai_access_policy.get_plan_by_id",
            return_value={"code": "pro", "name": "Pro"},
        ):
            policy = resolve_ai_access(42)
            self.assertFalse(policy.allowed)
            self.assertEqual(policy.access_state, "unknown")



# =============================================================================
# Tests: Grace period & renewal status (Phase 4I)
# =============================================================================


class TestGracePeriod(unittest.TestCase):
    """Tests for grace period behavior in process_subscription_expiry."""

    def _mk_sub(self, overrides=None):
        sub = {
            "id": 1, "company_id": 42, "plan_id": 3, "status": "active",
            "current_period_start": MONTH_AGO, "current_period_end": MONTH_AHEAD,
            "trial_ends_at": None, "cancelled_at": None,
            "cancellation_scheduled_at": None, "cancellation_effective_at": None,
            "pending_plan_id": None, "plan_change_effective_at": None,
        }
        if overrides:
            sub.update(overrides)
        return sub

    @patch("app.services.subscription_lifecycle_service.get_grace_period_days")
    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    def test_past_due_stays_in_grace(self, mock_latest, mock_grace):
        """Past_due subscription within grace period does not expire."""
        mock_grace.return_value = 10
        period_end = (NOW - timedelta(days=2)).isoformat()
        mock_latest.return_value = self._mk_sub({
            "status": "past_due", "current_period_end": period_end,
        })
        result = process_subscription_expiry(42, now=NOW)
        self.assertFalse(result["processed"])
        self.assertEqual(result["from_status"], "past_due")
        self.assertEqual(result["to_status"], "past_due")

    @patch("app.services.subscription_lifecycle_service.get_grace_period_days")
    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    @patch("app.services.subscription_lifecycle_service._update_status_conditional")
    def test_full_lifecycle_active_to_expired(self, mock_update, mock_latest, mock_grace):
        """Full lifecycle: active -> past_due -> expired through grace period."""
        mock_grace.return_value = 3
        period_end = (NOW - timedelta(days=7)).isoformat()

        # First pass: active -> past_due
        mock_latest.return_value = self._mk_sub({
            "status": "active", "current_period_end": period_end,
        })
        mock_update.return_value = self._mk_sub({"status": "past_due"})
        result = process_subscription_expiry(42, now=NOW)
        self.assertTrue(result["processed"])
        self.assertEqual(result["from_status"], "active")
        self.assertEqual(result["to_status"], "past_due")

        # Second pass: past_due -> expired (grace period exceeded)
        mock_latest.return_value = self._mk_sub({
            "status": "past_due", "current_period_end": period_end,
        })
        mock_update.return_value = self._mk_sub({"status": "expired"})
        result = process_subscription_expiry(42, now=NOW)
        self.assertTrue(result["processed"])
        self.assertEqual(result["from_status"], "past_due")
        self.assertEqual(result["to_status"], "expired")


class TestGracePeriodConfig(unittest.TestCase):
    """Tests for get_grace_period_days."""

    @patch.dict("app.services.subscription_lifecycle_service.os.environ", {"BILLING_GRACE_PERIOD_DAYS": "7"})
    def test_custom_grace_period(self):
        from app.services.subscription_lifecycle_service import get_grace_period_days
        self.assertEqual(get_grace_period_days(), 7)

    @patch.dict("app.services.subscription_lifecycle_service.os.environ", {})
    def test_default_grace_period(self):
        from app.services.subscription_lifecycle_service import get_grace_period_days
        self.assertEqual(get_grace_period_days(), 3)

    @patch.dict("app.services.subscription_lifecycle_service.os.environ", {"BILLING_GRACE_PERIOD_DAYS": "invalid"})
    def test_invalid_grace_fallback(self):
        from app.services.subscription_lifecycle_service import get_grace_period_days
        self.assertEqual(get_grace_period_days(), 3)


class TestRenewalStatusService(unittest.TestCase):
    """Tests for get_subscription_renewal_status."""

    def _make_sub(self, overrides=None):
        sub = {
            "id": 1, "company_id": 42, "plan_id": 3, "status": "active",
            "current_period_start": MONTH_AGO, "current_period_end": MONTH_AHEAD,
            "trial_ends_at": None, "cancelled_at": None,
            "cancellation_scheduled_at": None, "cancellation_effective_at": None,
            "pending_plan_id": None, "plan_change_effective_at": None,
        }
        if overrides:
            sub.update(overrides)
        return sub

    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    @patch("app.database.company_subscription_order_repository.list_subscription_orders_for_company")
    def test_active_no_renewal(self, mock_orders, mock_latest):
        """Active subscription with far expiry shows renewal not required."""
        mock_latest.return_value = self._make_sub()
        mock_orders.return_value = []
        from app.services.subscription_lifecycle_service import get_subscription_renewal_status
        status = get_subscription_renewal_status(42)
        self.assertEqual(status["subscription_status"], "active")
        self.assertFalse(status["renewal_required"])
        self.assertFalse(status["renewal_allowed"])
        self.assertTrue(status["days_until_expiry"] > 0)

    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    @patch("app.database.company_subscription_order_repository.list_subscription_orders_for_company")
    def test_expired_renewal_required(self, mock_orders, mock_latest):
        """Expired subscription shows renewal required."""
        mock_latest.return_value = self._make_sub({"status": "expired", "current_period_end": HOUR_AGO})
        mock_orders.return_value = []
        from app.services.subscription_lifecycle_service import get_subscription_renewal_status
        status = get_subscription_renewal_status(42)
        self.assertEqual(status["subscription_status"], "expired")
        self.assertTrue(status["renewal_required"])
        self.assertTrue(status["renewal_allowed"])

    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    @patch("app.database.company_subscription_order_repository.list_subscription_orders_for_company")
    def test_pending_renewal_order_detected(self, mock_orders, mock_latest):
        """Pending renewal order is detected."""
        mock_latest.return_value = self._make_sub({"status": "expired"})
        mock_orders.return_value = [{
            "order_reference": "abc-123", "activation_type": "renewal",
            "created_at": NOW_ISO, "expires_at": MONTH_AHEAD,
        }]
        from app.services.subscription_lifecycle_service import get_subscription_renewal_status
        status = get_subscription_renewal_status(42)
        self.assertIsNotNone(status["pending_renewal_order"])
        self.assertEqual(status["pending_renewal_order"]["order_reference"], "abc-123")

    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    def test_no_subscription_raises(self, mock_latest):
        """Company without subscription raises ValueError."""
        mock_latest.return_value = None
        from app.services.subscription_lifecycle_service import get_subscription_renewal_status
        with self.assertRaises(ValueError):
            get_subscription_renewal_status(99)

    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    @patch("app.database.company_subscription_order_repository.list_subscription_orders_for_company")
    @patch("app.database.subscription_plan_repository.get_plan_by_id")
    def test_scheduled_next_plan(self, mock_plan, mock_orders, mock_latest):
        """Scheduled downgrade shows next plan."""
        mock_plan.return_value = {"id": 2, "code": "essential", "name": "Essential"}
        mock_latest.return_value = self._make_sub({"pending_plan_id": 2})
        mock_orders.return_value = []
        from app.services.subscription_lifecycle_service import get_subscription_renewal_status
        status = get_subscription_renewal_status(42)
        self.assertIsNotNone(status["scheduled_next_plan"])
        self.assertEqual(status["scheduled_next_plan"]["code"], "essential")

    @patch("app.services.subscription_lifecycle_service._get_latest_sub")
    @patch("app.database.company_subscription_order_repository.list_subscription_orders_for_company")
    def test_near_expiry_message(self, mock_orders, mock_latest):
        """Active subscription near expiry shows message."""
        period_end = (NOW + timedelta(days=5)).isoformat()
        mock_latest.return_value = self._make_sub({"current_period_end": period_end})
        mock_orders.return_value = []
        from app.services.subscription_lifecycle_service import get_subscription_renewal_status
        status = get_subscription_renewal_status(42)
        self.assertIn("expires", status["message"].lower())
        self.assertTrue(status["days_until_expiry"] >= 4)
