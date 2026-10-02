"""Regression tests for subscription checkout activation-sequence conflicts."""

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
for _name in ("fitz", "tools", "_tools"):
    sys.modules.setdefault(_name, types.ModuleType(_name))


_SVC = "app.services.subscription_checkout_service"
_REPO = "app.database.company_subscription_order_repository"


class TestSubscriptionCheckoutActivationSequence(unittest.TestCase):
    def setUp(self):
        from app.services.chip_service import ChipConfig
        self.chip_config = ChipConfig(enabled=True, environment="test", api_key="mock-api-key",
            brand_id="00000000-0000-4000-8000-000000000001",
            redirect_url="https://app.example/profile", webhook_url="https://app.example/api/billing/chip/callback")
        config_patch = patch(_SVC + ".ChipConfig.from_env", return_value=self.chip_config)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        state_patch = patch(_SVC + ".update_subscription_order_activation_state")
        state_patch.start()
        self.addCleanup(state_patch.stop)
        self.subscription = {
            "id": 5,
            "company_id": 29,
            "plan_id": 1,
            "status": "active",
            "current_period_start": "2026-07-16T02:12:51.880632+00:00",
            "current_period_end": "2026-08-16T02:12:51.880632+00:00",
            "trial_ends_at": None,
            "plan": {"id": 1, "code": "free", "name": "Free"},
        }
        self.advanced_plan = {
            "id": 6,
            "code": "advanced",
            "name": "Advanced",
            "is_active": True,
        }
        self.essential_plan = {
            "id": 4,
            "code": "essential",
            "name": "Essential",
            "is_active": True,
        }
        self.existing_sequence_order = {
            "id": 12,
            "payment_gateway": "chip",
            "gateway_environment": "test",
            "gateway_brand_id": "00000000-0000-4000-8000-000000000001",
            "currency": "MYR",
            "order_reference": "existing-ref",
            "company_id": 29,
            "subscription_id": 5,
            "source_plan_id": 1,
            "new_plan_id": 6,
            "amount_sen": 8900,
            "status": "pending",
            "activation_status": None,
            "activation_type": "upgrade",
            "activation_sequence_key": (
                "company:29:upgrade-from:1:"
                "period:2026-07-16T02:12:51.880632+00:00"
            ),
        }
        self.future_expires_at = "2099-01-01T00:00:00+00:00"
        self.past_expires_at = "2000-01-01T00:00:00+00:00"

    def _call_checkout(self, plan_code="advanced"):
        from app.services.subscription_checkout_service import create_subscription_checkout

        return create_subscription_checkout(
            company_id=29,
            user_id=1,
            plan_code=plan_code,
            customer_name="Test User",
            customer_email="test@example.com",
        )

    def test_same_plan_pending_order_remains_rejected(self):
        with (
            patch(_SVC + ".get_current_subscription", return_value=self.subscription),
            patch(_SVC + ".get_plan_by_code", return_value=self.essential_plan),
            patch(_SVC + ".get_subscription_order_by_activation_sequence_key", return_value=None) as mock_seq,
            patch(
                _REPO + ".list_subscription_orders_for_company",
                return_value=[{"new_plan_id": self.essential_plan["id"], "status": "pending"}],
            ),
            patch(_SVC + ".create_subscription_order") as mock_create,
        ):
            with self.assertRaises(ValueError) as ctx:
                self._call_checkout("essential")

        self.assertIn("pending order already exists for this plan", str(ctx.exception).lower())
        mock_seq.assert_called_once()
        mock_create.assert_not_called()

    def test_existing_pending_same_sequence_with_valid_checkout_is_reused(self):
        existing_order = dict(self.existing_sequence_order)
        existing_order["gateway_order_id"] = "bill-advanced-1"
        existing_order["checkout_url"] = "https://gate.chip-in.asia/bill-advanced-1"
        existing_order["expires_at"] = self.future_expires_at

        with (
            patch(_SVC + ".get_current_subscription", return_value=self.subscription),
            patch(_SVC + ".get_plan_by_code", return_value=self.advanced_plan),
            patch(_SVC + ".get_subscription_order_by_activation_sequence_key", return_value=existing_order),
            patch(_REPO + ".list_subscription_orders_for_company") as mock_list,
            patch(_SVC + ".create_subscription_order") as mock_create,
            patch(_SVC + ".create_purchase") as mock_bill,
        ):
            result = self._call_checkout("advanced")

        self.assertEqual(result["order_reference"], "existing-ref")
        self.assertEqual(result["checkout_url"], "https://gate.chip-in.asia/bill-advanced-1")
        self.assertEqual(result["amount_sen"], 8900)
        self.assertEqual(result["expires_at"], self.future_expires_at)
        self.assertTrue(result["existing_order"])
        mock_list.assert_not_called()
        mock_create.assert_not_called()
        mock_bill.assert_not_called()

    def test_existing_pending_same_sequence_with_stale_amount_is_not_reused(self):
        existing_order = dict(self.existing_sequence_order)
        existing_order["amount_sen"] = 16900
        existing_order["gateway_order_id"] = "bill-advanced-1"
        existing_order["checkout_url"] = "https://gate.chip-in.asia/bill-advanced-1"
        existing_order["expires_at"] = self.future_expires_at

        with (
            patch(_SVC + ".get_current_subscription", return_value=self.subscription),
            patch(_SVC + ".get_plan_by_code", return_value=self.advanced_plan),
            patch(_SVC + ".get_subscription_order_by_activation_sequence_key", return_value=existing_order),
            patch(_SVC + ".create_subscription_order") as mock_create,
            patch(_SVC + ".create_purchase") as mock_bill,
        ):
            with self.assertRaises(ValueError) as ctx:
                self._call_checkout("advanced")

        self.assertIn("outdated price", str(ctx.exception).lower())
        mock_create.assert_not_called()
        mock_bill.assert_not_called()

    def test_existing_pending_different_target_plan_with_valid_checkout_is_blocked(self):
        existing_order = dict(self.existing_sequence_order)
        existing_order["new_plan_id"] = self.essential_plan["id"]
        existing_order["gateway_order_id"] = "bill-essential-1"
        existing_order["checkout_url"] = "https://gate.chip-in.asia/bill-essential-1"
        existing_order["expires_at"] = self.future_expires_at

        with (
            patch(_SVC + ".get_current_subscription", return_value=self.subscription),
            patch(_SVC + ".get_plan_by_code", return_value=self.advanced_plan),
            patch(_SVC + ".get_subscription_order_by_activation_sequence_key", return_value=existing_order),
            patch(_SVC + ".create_subscription_order") as mock_create,
            patch(_SVC + ".create_purchase") as mock_bill,
        ):
            with self.assertRaises(ValueError) as ctx:
                self._call_checkout("advanced")

        self.assertIn("pending subscription checkout already exists", str(ctx.exception).lower())
        mock_create.assert_not_called()
        mock_bill.assert_not_called()

    def test_existing_pending_same_sequence_missing_expiry_is_not_reused(self):
        existing_order = dict(self.existing_sequence_order)
        existing_order["gateway_order_id"] = "bill-advanced-1"
        existing_order["checkout_url"] = "https://gate.chip-in.asia/bill-advanced-1"
        existing_order["expires_at"] = None

        with (
            patch(_SVC + ".get_current_subscription", return_value=self.subscription),
            patch(_SVC + ".get_plan_by_code", return_value=self.advanced_plan),
            patch(_SVC + ".get_subscription_order_by_activation_sequence_key", return_value=existing_order),
            patch(_SVC + ".create_subscription_order") as mock_create,
            patch(_SVC + ".create_purchase") as mock_bill,
        ):
            with self.assertRaises(ValueError) as ctx:
                self._call_checkout("advanced")

        self.assertIn("pending subscription checkout already exists", str(ctx.exception).lower())
        mock_create.assert_not_called()
        mock_bill.assert_not_called()

    def test_provider_confirmed_expired_same_sequence_allows_fresh_checkout(self):
        existing_order = dict(self.existing_sequence_order)
        existing_order["gateway_order_id"] = "bill-advanced-1"
        existing_order["checkout_url"] = "https://gate.chip-in.asia/bill-advanced-1"
        existing_order["expires_at"] = self.past_expires_at

        fixed_now = datetime(2026, 8, 12, 0, 0, 0, tzinfo=timezone.utc)
        with (
            patch(_SVC + "._now_utc", return_value=fixed_now),
            patch(_SVC + ".get_current_subscription", return_value=self.subscription),
            patch(_SVC + ".get_plan_by_code", return_value=self.advanced_plan),
            patch(_SVC + ".get_subscription_order_by_activation_sequence_key", return_value=existing_order),
            patch(_REPO + ".list_subscription_orders_for_company", return_value=[]),
            patch(_SVC + "._expire_existing_pending_checkout_if_needed", return_value=True) as mock_expire,
            patch(
                _SVC + ".create_subscription_order",
                return_value={"order_reference": "order-1", "status": "pending"},
            ) as mock_create,
            patch(
                _SVC + ".create_purchase",
                return_value={"gateway_order_id": "bill-1", "is_test": True, "brand_id": "00000000-0000-4000-8000-000000000001", "checkout_url": "https://gate.chip-in.asia/p/1/"},
            ) as mock_bill,
            patch(_SVC + ".attach_pending_subscription_gateway_details"),
        ):
            result = self._call_checkout("advanced")

        self.assertEqual(result["checkout_url"], "https://gate.chip-in.asia/p/1/")
        self.assertEqual(result["expires_at"], "2026-08-13T00:00:00+00:00")
        mock_expire.assert_called_once()
        mock_expire.assert_called_once_with(existing_order, existing_order["activation_sequence_key"])
        mock_create.assert_called_once()
        mock_bill.assert_called_once()

    def test_provider_confirmed_expired_same_plan_allows_fresh_checkout(self):
        expired_same_plan = {
            "id": 20,
            "order_reference": "expired-ref",
            "new_plan_id": self.advanced_plan["id"],
            "status": "pending",
            "activation_status": None,
            "reconciliation_required": False,
            "activation_sequence_key": "company:29:upgrade-from:1:period:old",
            "expires_at": self.past_expires_at,
        }

        with (
            patch(_SVC + ".get_current_subscription", return_value=self.subscription),
            patch(_SVC + ".get_plan_by_code", return_value=self.advanced_plan),
            patch(_SVC + ".get_subscription_order_by_activation_sequence_key", return_value=None),
            patch(_REPO + ".list_subscription_orders_for_company", return_value=[expired_same_plan]),
            patch(_SVC + "._expire_existing_pending_checkout_if_needed", return_value=True) as mock_expire,
            patch(
                _SVC + ".create_subscription_order",
                return_value={"order_reference": "order-1", "status": "pending"},
            ) as mock_create,
            patch(
                _SVC + ".create_purchase",
                return_value={"gateway_order_id": "bill-1", "is_test": True, "brand_id": "00000000-0000-4000-8000-000000000001", "checkout_url": "https://gate.chip-in.asia/p/1/"},
            ),
            patch(_SVC + ".attach_pending_subscription_gateway_details"),
        ):
            self._call_checkout("advanced")

        mock_expire.assert_called_once()
        mock_create.assert_called_once()

    def test_incomplete_pending_same_sequence_is_business_error(self):
        with (
            patch(_SVC + ".get_current_subscription", return_value=self.subscription),
            patch(_SVC + ".get_plan_by_code", return_value=self.advanced_plan),
            patch(
                _SVC + ".get_subscription_order_by_activation_sequence_key",
                return_value=self.existing_sequence_order,
            ) as mock_seq,
            patch(_SVC + ".create_subscription_order") as mock_create,
        ):
            with self.assertRaises(ValueError) as ctx:
                self._call_checkout("advanced")

        message = str(ctx.exception)
        self.assertIn("payment link is not available", message.lower())
        self.assertNotIn("idx_cso_activation_sequence_key", message)
        self.assertNotIn("duplicate key", message.lower())
        mock_seq.assert_called_once_with(
            "company:29:upgrade-from:1:period:2026-07-16T02:12:51.880632+00:00"
        )
        mock_create.assert_not_called()

    def test_gateway_persistence_failure_does_not_return_untracked_checkout_url(self):
        with (
            patch(_SVC + ".get_current_subscription", return_value=self.subscription),
            patch(_SVC + ".get_plan_by_code", return_value=self.advanced_plan),
            patch(_REPO + ".list_subscription_orders_for_company", return_value=[]),
            patch(_SVC + ".get_subscription_order_by_activation_sequence_key", return_value=None),
            patch(
                _SVC + ".create_subscription_order",
                return_value={"order_reference": "order-1", "status": "pending"},
            ),
            patch(
                _SVC + ".create_purchase",
                return_value={"gateway_order_id": "bill-1", "is_test": True, "brand_id": "00000000-0000-4000-8000-000000000001", "checkout_url": "https://gate.chip-in.asia/bill-1"},
            ),
            patch(
                _SVC + ".attach_pending_subscription_gateway_details",
                side_effect=RuntimeError("db unavailable"),
            ),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                self._call_checkout("advanced")

        self.assertIn("could not be recorded safely", str(ctx.exception).lower())
        self.assertNotIn("db unavailable", str(ctx.exception))

    def test_definite_gateway_rejection_releases_activation_key(self):
        from app.services.chip_service import ChipRequestRejectedError

        with (
            patch(_SVC + ".get_current_subscription", return_value=self.subscription),
            patch(_SVC + ".get_plan_by_code", return_value=self.advanced_plan),
            patch(_REPO + ".list_subscription_orders_for_company", return_value=[]),
            patch(_SVC + ".get_subscription_order_by_activation_sequence_key", return_value=None),
            patch(_SVC + ".uuid.uuid4", return_value="order-1"),
            patch(
                _SVC + ".create_subscription_order",
                return_value={"id": 14, "order_reference": "order-1", "status": "pending"},
            ),
            patch(_SVC + ".create_purchase", side_effect=ChipRequestRejectedError("provider raw secret detail")),
            patch(_SVC + ".fail_pending_subscription_order_without_gateway_and_release_key") as mock_release,
            patch(_SVC + ".update_subscription_order_activation_state") as mock_update,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                self._call_checkout("advanced")

        self.assertEqual(
            str(ctx.exception),
            "Payment gateway purchase creation failed. Please try again later.",
        )
        mock_release.assert_called_once()
        _, kwargs = mock_release.call_args
        self.assertEqual(kwargs["order_reference"], "order-1")
        self.assertEqual(
            kwargs["activation_sequence_key"],
            "company:29:upgrade-from:1:period:2026-07-16T02:12:51.880632+00:00",
        )
        self.assertEqual(
            kwargs["released_activation_sequence_key"],
            "released:gateway-create-rejected:order:14:"
            "company:29:upgrade-from:1:period:2026-07-16T02:12:51.880632+00:00",
        )
        mock_update.assert_not_called()

    def test_ambiguous_gateway_failure_keeps_activation_key_for_support_review(self):
        with (
            patch(_SVC + ".get_current_subscription", return_value=self.subscription),
            patch(_SVC + ".get_plan_by_code", return_value=self.advanced_plan),
            patch(_REPO + ".list_subscription_orders_for_company", return_value=[]),
            patch(_SVC + ".get_subscription_order_by_activation_sequence_key", return_value=None),
            patch(_SVC + ".uuid.uuid4", return_value="order-ambiguous"),
            patch(
                _SVC + ".create_subscription_order",
                return_value={"id": 15, "order_reference": "order-ambiguous", "status": "pending"},
            ),
            patch(_SVC + ".create_purchase", side_effect=RuntimeError("timeout after send")),
            patch(_SVC + ".fail_pending_subscription_order_without_gateway_and_release_key") as mock_release,
            patch(_SVC + ".update_subscription_order_activation_state") as mock_update,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                self._call_checkout("advanced")

        self.assertEqual(
            str(ctx.exception),
            "Payment gateway checkout outcome is pending verification. Please do not retry yet.",
        )
        mock_release.assert_not_called()
        mock_update.assert_called_once()
        kwargs = mock_update.call_args.kwargs
        self.assertEqual(kwargs["order_reference"], "order-ambiguous")
        self.assertEqual(kwargs["activation_error_code"], "gateway_create_ambiguous")
        self.assertTrue(kwargs["reconciliation_required"])

    def test_duplicate_activation_sequence_insert_never_becomes_generic_500(self):
        duplicate_error = RuntimeError(
            'duplicate key value violates unique constraint "idx_cso_activation_sequence_key"'
        )
        with (
            patch(_SVC + ".get_current_subscription", return_value=self.subscription),
            patch(_SVC + ".get_plan_by_code", return_value=self.advanced_plan),
            patch(_REPO + ".list_subscription_orders_for_company", return_value=[]),
            patch(_SVC + ".get_subscription_order_by_activation_sequence_key", return_value=None),
            patch(_SVC + ".create_subscription_order", side_effect=duplicate_error),
        ):
            with self.assertRaises(ValueError) as ctx:
                self._call_checkout("advanced")

        message = str(ctx.exception)
        self.assertIn("subscription checkout already exists", message.lower())
        self.assertNotIn("idx_cso_activation_sequence_key", message)
        self.assertNotIn("duplicate key", message.lower())

    def test_allowed_checkout_still_creates_order(self):
        with (
            patch(_SVC + ".get_current_subscription", return_value=self.subscription),
            patch(_SVC + ".get_plan_by_code", return_value=self.advanced_plan),
            patch(_REPO + ".list_subscription_orders_for_company", return_value=[]),
            patch(_SVC + ".get_subscription_order_by_activation_sequence_key", return_value=None),
            patch(
                _SVC + ".create_subscription_order",
                return_value={"order_reference": "order-1", "status": "pending"},
            ) as mock_create,
            patch(
                _SVC + ".create_purchase",
                return_value={"gateway_order_id": "bill-1", "is_test": True, "brand_id": "00000000-0000-4000-8000-000000000001", "checkout_url": "https://gate.chip-in.asia/p/1/"},
            ) as mock_bill,
            patch(_SVC + ".attach_pending_subscription_gateway_details"),
        ):
            result = self._call_checkout("advanced")

        self.assertEqual(result["checkout_url"], "https://gate.chip-in.asia/p/1/")
        self.assertIn("expires_at", result)
        _, kwargs = mock_create.call_args
        self.assertIsNotNone(kwargs["expires_at"])
        self.assertEqual(kwargs["activation_type"], "upgrade")
        self.assertEqual(
            kwargs["activation_sequence_key"],
            "company:29:upgrade-from:1:period:2026-07-16T02:12:51.880632+00:00",
        )
        _, bill_kwargs = mock_bill.call_args
        self.assertEqual(bill_kwargs["due"], int(datetime.fromisoformat(kwargs["expires_at"]).timestamp()))

    def test_expired_free_trial_can_still_create_upgrade_checkout(self):
        expired_free = dict(self.subscription)
        expired_free["status"] = "active"
        expired_free["trial_ends_at"] = "2026-07-23T02:12:51.880632+00:00"

        with (
            patch(_SVC + ".get_current_subscription", return_value=expired_free),
            patch(_SVC + ".get_plan_by_code", return_value=self.advanced_plan),
            patch(_REPO + ".list_subscription_orders_for_company", return_value=[]),
            patch(_SVC + ".get_subscription_order_by_activation_sequence_key", return_value=None),
            patch(
                _SVC + ".create_subscription_order",
                return_value={"order_reference": "order-1", "status": "pending"},
            ) as mock_create,
            patch(
                _SVC + ".create_purchase",
                return_value={"gateway_order_id": "bill-1", "is_test": True, "brand_id": "00000000-0000-4000-8000-000000000001", "checkout_url": "https://gate.chip-in.asia/p/1/"},
            ),
            patch(_SVC + ".attach_pending_subscription_gateway_details"),
        ):
            result = self._call_checkout("advanced")

        self.assertEqual(result["checkout_url"], "https://gate.chip-in.asia/p/1/")
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs["source_status"], "active")
        self.assertEqual(kwargs["activation_type"], "upgrade")

    def test_checkout_expiry_days_aligns_app_and_gateway(self):
        from app.services import subscription_checkout_service as svc

        fixed_now = datetime(2026, 8, 12, 1, 30, 0, tzinfo=timezone.utc)
        with patch.dict(os.environ, {"SUBSCRIPTION_CHECKOUT_EXPIRY_DAYS": "3"}, clear=False):
            expires_at = svc._build_checkout_expires_at(fixed_now)
            gateway_days = svc._checkout_expiry_days()

        self.assertEqual(gateway_days, 3)
        self.assertEqual(expires_at, "2026-08-15T01:30:00+00:00")

    def test_naive_checkout_time_is_interpreted_as_utc(self):
        from app.services import subscription_checkout_service as svc
        with patch.dict(os.environ, {"SUBSCRIPTION_CHECKOUT_EXPIRY_DAYS": "1"}):
            self.assertEqual(svc._build_checkout_expires_at(datetime(2026, 8, 12)), "2026-08-13T00:00:00+00:00")

    def test_create_app_import_succeeds_with_timezone_dependency_available(self):
        from app import create_app

        app = create_app()

        self.assertIsNotNone(app)

    def test_legacy_hour_expiry_config_fails_closed(self):
        from app.services import subscription_checkout_service as svc

        for hours in ("1", "23", "25", "36"):
            with self.subTest(hours=hours):
                with patch.dict(os.environ, {"SUBSCRIPTION_CHECKOUT_EXPIRY_HOURS": hours}, clear=False):
                    with self.assertRaises(RuntimeError):
                        svc._checkout_expiry_days()

    def test_invalid_day_expiry_config_fails_closed(self):
        from app.services import subscription_checkout_service as svc

        for days in ("0", "101", "1.5", "bad"):
            with self.subTest(days=days):
                with patch.dict(os.environ, {"SUBSCRIPTION_CHECKOUT_EXPIRY_DAYS": days}, clear=False):
                    with self.assertRaises(RuntimeError):
                        svc._checkout_expiry_days()

    def test_duplicate_fresh_checkout_after_concurrent_release_does_not_create_bill(self):
        existing_order = dict(self.existing_sequence_order)
        existing_order["gateway_order_id"] = "bill-advanced-1"
        existing_order["checkout_url"] = "https://gate.chip-in.asia/bill-advanced-1"
        existing_order["expires_at"] = self.past_expires_at

        duplicate_error = RuntimeError(
            'duplicate key value violates unique constraint "idx_cso_activation_sequence_key"'
        )
        with (
            patch(_SVC + ".get_current_subscription", return_value=self.subscription),
            patch(_SVC + ".get_plan_by_code", return_value=self.advanced_plan),
            patch(_SVC + ".get_subscription_order_by_activation_sequence_key", return_value=existing_order),
            patch(_REPO + ".list_subscription_orders_for_company", return_value=[]),
            patch(_SVC + "._expire_existing_pending_checkout_if_needed", return_value=True),
            patch(_SVC + ".create_subscription_order", side_effect=duplicate_error),
            patch(_SVC + ".create_purchase") as mock_bill,
        ):
            with self.assertRaises(ValueError):
                self._call_checkout("advanced")

        mock_bill.assert_not_called()

    def test_terminal_prior_order_for_same_sequence_is_cleanly_blocked(self):
        terminal_order = dict(self.existing_sequence_order)
        terminal_order["status"] = "failed"
        with (
            patch(_SVC + ".get_current_subscription", return_value=self.subscription),
            patch(_SVC + ".get_plan_by_code", return_value=self.advanced_plan),
            patch(_REPO + ".list_subscription_orders_for_company", return_value=[]),
            patch(
                _SVC + ".get_subscription_order_by_activation_sequence_key",
                return_value=terminal_order,
            ),
            patch(_SVC + ".create_subscription_order") as mock_create,
        ):
            with self.assertRaises(ValueError) as ctx:
                self._call_checkout("advanced")

        self.assertIn("already exists for this billing period", str(ctx.exception).lower())
        mock_create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
