"""test_trial_ai_credit_initialisation.py

Tests for trial AI-credit initialisation and lazy preflight recovery.
"""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("AI_CREDIT_ENFORCEMENT_ENABLED", "true")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import sys
sys.path.insert(0, r"C:\Users\User\PycharmProjects\python-whatsapp-bot-main")

import unittest
from unittest.mock import patch, MagicMock, call
import types

# Mock broken dependencies before any app import
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

# Patch supabase at module level before any repo imports resolve
_sb = MagicMock()
_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
_sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
_sb.rpc.return_value.execute.return_value = MagicMock(data=[])
with patch("app.database.db.supabase", _sb):
    from app.services.billing_service import ensure_default_company_subscription
    from app.services.ai_credit_service import ensure_company_ai_credit, get_company_ai_credit_summary
    from app.services.ai_router import _check_ai_credit_before_provider
    from app.services.billing_guard import BillingLimitError


class TestTrialAiCreditInitialisation(unittest.TestCase):
    """Tests for trial AI-credit initialisation during subscription creation."""

    def setUp(self):
        # Patch repository-level dependencies that make network calls.
        # The module-level supabase mock prevents ConnectErrors, but the
        # repository functions that use supabase.table(...).execute() still
        # go through the httpx client. We must also patch the HTTP-level
        # execute to return empty data so get_plan_by_code can work.
        # Patch supabase in all repository modules that may have their own reference.
        # The module-level patch in the import section handles first import,
        # but setUp needs to re-patch because subscription_plan_repository
        # has its own module-level `from app.database.db import supabase`.
        self.su_plan_patch = patch("app.database.subscription_plan_repository.supabase")
        self.su_billing_patch = patch("app.services.billing_service.supabase", None)
        self.mock_su_plan = self.su_plan_patch.start()
        self.mock_su_plan.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        self.mock_su_plan.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
        self.mock_su_plan.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        self.mock_su_plan.rpc.return_value.execute.return_value = MagicMock(data=[])

        self.get_latest_patch = patch("app.services.billing_service._get_latest_company_subscription")
        self.get_cur_patch = patch("app.services.billing_service._get_company_subscription")
        self.create_sub_patch = patch("app.services.billing_service._create_company_subscription")
        self.get_plan_patch = patch("app.services.billing_service.get_plan_by_code", return_value={
            "id": 1, "code": "free", "name": "Free",
            "included_ai_credit_micro_myr": 1000000,
        })
        self.mock_get_latest = self.get_latest_patch.start()
        self.mock_get_cur = self.get_cur_patch.start()
        self.mock_create_sub = self.create_sub_patch.start()
        self.mock_get_plan = self.get_plan_patch.start()
        self.mock_get_latest.return_value = None
        self.mock_get_cur.return_value = None
        self.mock_create_sub.return_value = {
            "id": 100, "company_id": 99, "plan_id": 1,
            "status": "trialing", "starts_at": "now", "current_period_start": "now",
            "current_period_end": "future", "trial_ends_at": "future",
        }

    def tearDown(self):
        self.get_latest_patch.stop()
        self.get_cur_patch.stop()
        self.create_sub_patch.stop()
        self.get_plan_patch.stop()
        self.su_plan_patch.stop()
        self.su_billing_patch.stop()

    @patch("app.services.billing_service.ensure_company_ai_credit")
    def test_new_trial_subscription_initialises_credit(self, mock_init):
        """New trial subscription triggers AI-credit initialisation."""
        result = ensure_default_company_subscription(99)
        mock_init.assert_called_once_with(99)

    @patch("app.services.billing_service.ensure_company_ai_credit")
    def test_existing_subscription_skips_credit_init(self, mock_init):
        """Company with existing subscription skips credit init."""
        self.mock_get_latest.return_value = {"id": 50, "company_id": 99, "status": "active"}
        with patch("app.services.billing_service.get_current_subscription") as gcs:
            gcs.return_value = {"id": 50, "status": "active"}
            result = ensure_default_company_subscription(99)
            mock_init.assert_not_called()

    @patch("app.services.billing_service.ensure_company_ai_credit")
    def test_credit_init_failure_does_not_abort_registration(self, mock_init):
        """AI-credit init failure does not prevent subscription creation success."""
        mock_init.side_effect = RuntimeError("Database connection failed")
        with patch("app.services.billing_service.get_current_subscription") as gcs:
            gcs.return_value = {"id": 100, "status": "trialing", "company_id": 99}
            result = ensure_default_company_subscription(99)
        self.assertIsNotNone(result)

    @patch("app.services.billing_service.ensure_company_ai_credit")
    def test_repeated_init_is_idempotent(self, mock_init):
        """Multiple calls to ensure_default_company_subscription are safe."""
        # First call: no existing sub
        r1 = ensure_default_company_subscription(99)
        mock_init.assert_called_once_with(99)
        # Second call: existing sub exists (created by first call)
        self.mock_get_latest.return_value = {"id": 100, "company_id": 99, "status": "trialing"}
        with patch("app.services.billing_service.get_current_subscription") as gcs:
            gcs.return_value = {"id": 100, "status": "trialing"}
            r2 = ensure_default_company_subscription(99)
            # init should not be called again
            mock_init.assert_called_once_with(99)


class TestLazyPreflightRecovery(unittest.TestCase):
    """Tests for lazy AI-credit initialisation in preflight check."""

    def setUp(self):
        self.company_id = 42

    @patch("app.services.ai_router.is_ai_credit_enforcement_enabled")
    @patch("app.services.ai_router.get_ai_retail_markup_basis_points")
    @patch("app.services.ai_router.get_ai_usd_to_myr_rate_micro_myr_per_usd")
    @patch("app.services.ai_router.get_company_ai_credit_summary")
    @patch("app.services.ai_router.ensure_company_ai_credit")
    def test_lazy_init_called_when_balance_missing(
        self, mock_ensure, mock_summary, mock_fx, mock_markup, mock_enabled
    ):
        """Missing balance triggers lazy init before RuntimeError."""
        mock_enabled.return_value = True
        mock_markup.return_value = 2500
        mock_fx.return_value = 4500000
        # First call: not initialised
        first_summary = {
            "initialised": False,
            "included_balance_micro_myr": None,
            "topup_balance_micro_myr": None,
            "total_balance_micro_myr": None,
        }
        # Second call (after lazy init): initialised with trial credit
        second_summary = {
            "initialised": True,
            "included_balance_micro_myr": 1000000,
            "topup_balance_micro_myr": 0,
            "total_balance_micro_myr": 1000000,
        }
        mock_summary.side_effect = [first_summary, second_summary]
        mock_ensure.return_value = {"status": "ok"}
        # Should not raise - lazy init recovered
        _check_ai_credit_before_provider(self.company_id)
        mock_ensure.assert_called_once_with(self.company_id)
        self.assertEqual(mock_summary.call_count, 2)

    @patch("app.services.ai_router.is_ai_credit_enforcement_enabled")
    @patch("app.services.ai_router.get_ai_retail_markup_basis_points")
    @patch("app.services.ai_router.get_ai_usd_to_myr_rate_micro_myr_per_usd")
    @patch("app.services.ai_router.get_company_ai_credit_summary")
    @patch("app.services.ai_router.ensure_company_ai_credit")
    def test_runtime_error_when_init_still_fails(
        self, mock_ensure, mock_summary, mock_fx, mock_markup, mock_enabled
    ):
        """RuntimeError raised when lazy init does not resolve the missing balance."""
        mock_enabled.return_value = True
        mock_markup.return_value = 2500
        mock_fx.return_value = 4500000
        uninit_summary = {
            "initialised": False,
            "included_balance_micro_myr": None,
            "topup_balance_micro_myr": None,
            "total_balance_micro_myr": None,
        }
        mock_summary.side_effect = [uninit_summary, uninit_summary]
        mock_ensure.return_value = {"status": "ok"}
        with self.assertRaises(RuntimeError) as ctx:
            _check_ai_credit_before_provider(self.company_id)
        self.assertIn("initialised", str(ctx.exception))

    @patch("app.services.ai_router.is_ai_credit_enforcement_enabled")
    @patch("app.services.ai_router.get_ai_retail_markup_basis_points")
    @patch("app.services.ai_router.get_ai_usd_to_myr_rate_micro_myr_per_usd")
    @patch("app.services.ai_router.get_company_ai_credit_summary")
    @patch("app.services.ai_router.ensure_company_ai_credit")
    @patch("app.services.ai_router._is_free_plan_company")
    def test_billing_limit_error_when_balance_depleted(
        self, mock_is_free, mock_ensure, mock_summary, mock_fx, mock_markup, mock_enabled
    ):
        """BillingLimitError raised with top-up message for paid plan when balance is zero."""
        mock_enabled.return_value = True
        mock_markup.return_value = 2500
        mock_fx.return_value = 4500000
        mock_ensure.return_value = {"status": "ok"}
        mock_is_free.return_value = False
        summary = {
            "initialised": True,
            "included_balance_micro_myr": 0,
            "topup_balance_micro_myr": 0,
            "total_balance_micro_myr": 0,
        }
        mock_summary.return_value = summary
        with self.assertRaises(BillingLimitError) as ctx:
            _check_ai_credit_before_provider(self.company_id)
        self.assertIn("top up", str(ctx.exception))

    @patch("app.services.ai_router.is_ai_credit_enforcement_enabled")
    @patch("app.services.ai_router.get_ai_retail_markup_basis_points")
    @patch("app.services.ai_router.get_ai_usd_to_myr_rate_micro_myr_per_usd")
    @patch("app.services.ai_router.get_company_ai_credit_summary")
    @patch("app.services.ai_router.ensure_company_ai_credit")
    def test_existing_balance_skips_init(
        self, mock_ensure, mock_summary, mock_fx, mock_markup, mock_enabled
    ):
        """Already initialised balance skips lazy init call."""
        mock_enabled.return_value = True
        mock_markup.return_value = 2500
        mock_fx.return_value = 4500000
        summary = {
            "initialised": True,
            "included_balance_micro_myr": 1000000,
            "topup_balance_micro_myr": 0,
            "total_balance_micro_myr": 1000000,
        }
        mock_summary.return_value = summary
        _check_ai_credit_before_provider(self.company_id)
        mock_ensure.assert_not_called()
        self.assertEqual(mock_summary.call_count, 1)

    @patch("app.services.ai_router.is_ai_credit_enforcement_enabled")
    @patch("app.services.ai_router.get_ai_retail_markup_basis_points")
    @patch("app.services.ai_router.get_ai_usd_to_myr_rate_micro_myr_per_usd")
    @patch("app.services.ai_router.get_company_ai_credit_summary")
    def test_positive_balance_passes(
        self, mock_summary, mock_fx, mock_markup, mock_enabled
    ):
        """Preflight passes with positive balance."""
        mock_enabled.return_value = True
        mock_markup.return_value = 2500
        mock_fx.return_value = 4500000
        summary = {
            "initialised": True,
            "included_balance_micro_myr": 500000,
            "topup_balance_micro_myr": 0,
            "total_balance_micro_myr": 500000,
        }
        mock_summary.return_value = summary
        _check_ai_credit_before_provider(self.company_id)
        self.assertEqual(mock_summary.call_count, 1)

    @patch("app.services.ai_router.is_ai_credit_enforcement_enabled")
    @patch("app.services.ai_router.get_company_ai_credit_summary")
    def test_returns_when_enforcement_disabled(
        self, mock_summary, mock_enabled
    ):
        """Preflight returns immediately when enforcement is disabled."""
        mock_enabled.return_value = False
        _check_ai_credit_before_provider(self.company_id)
        mock_summary.assert_not_called()


    @patch("app.services.ai_router.is_ai_credit_enforcement_enabled")
    @patch("app.services.ai_router.get_ai_retail_markup_basis_points")
    @patch("app.services.ai_router.get_ai_usd_to_myr_rate_micro_myr_per_usd")
    @patch("app.services.ai_router.get_company_ai_credit_summary")
    @patch("app.services.ai_router.ensure_company_ai_credit")
    @patch("app.services.ai_router._is_free_plan_company")
    def test_trial_depleted_message_contains_upgrade(
        self, mock_is_free, mock_ensure, mock_summary, mock_fx, mock_markup, mock_enabled
    ):
        """Free trial depleted balance raises BillingLimitError with upgrade message."""
        mock_enabled.return_value = True
        mock_markup.return_value = 2500
        mock_fx.return_value = 4500000
        mock_ensure.return_value = {"status": "ok"}
        mock_is_free.return_value = True
        summary = {
            "initialised": True,
            "included_balance_micro_myr": 0,
            "topup_balance_micro_myr": 0,
            "total_balance_micro_myr": 0,
        }
        mock_summary.return_value = summary
        with self.assertRaises(BillingLimitError) as ctx:
            _check_ai_credit_before_provider(self.company_id)
        self.assertIn("trial AI credit", str(ctx.exception))
        self.assertIn("upgrade", str(ctx.exception).lower())
        self.assertNotIn("top up", str(ctx.exception).lower())

    @patch("app.services.ai_router.is_ai_credit_enforcement_enabled")
    @patch("app.services.ai_router.get_ai_retail_markup_basis_points")
    @patch("app.services.ai_router.get_ai_usd_to_myr_rate_micro_myr_per_usd")
    @patch("app.services.ai_router.get_company_ai_credit_summary")
    @patch("app.services.ai_router.ensure_company_ai_credit")
    @patch("app.services.ai_router._is_free_plan_company")
    def test_lookup_failure_defaults_to_paid_message(
        self, mock_is_free, mock_ensure, mock_summary, mock_fx, mock_markup, mock_enabled
    ):
        """When trial-status lookup raises, defaults to paid message and still raises."""
        mock_enabled.return_value = True
        mock_markup.return_value = 2500
        mock_fx.return_value = 4500000
        mock_ensure.return_value = {"status": "ok"}
        mock_is_free.side_effect = RuntimeError("DB connection lost")
        summary = {
            "initialised": True,
            "included_balance_micro_myr": 0,
            "topup_balance_micro_myr": 0,
            "total_balance_micro_myr": 0,
        }
        mock_summary.return_value = summary
        with self.assertRaises(BillingLimitError) as ctx:
            _check_ai_credit_before_provider(self.company_id)
        self.assertIn("top up", str(ctx.exception).lower())
        self.assertNotIn("trial", str(ctx.exception).lower())


class TestAuthRouteImports(unittest.TestCase):
    """verify_otp must be able to call ensure_default_company_subscription."""

    def test_ensure_default_company_subscription_imported_in_auth_routes(self):
        """The import exists and the function is callable."""
        from app.routes.auth_routes import ensure_default_company_subscription
        self.assertTrue(callable(ensure_default_company_subscription))

if __name__ == "__main__":
    unittest.main()
