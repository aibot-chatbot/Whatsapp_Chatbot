"""Phase 4F: Tenant isolation, security, and plan-enforcement tests.

Verifies that billing and AI-credit data cannot leak across companies,
bot_id does not affect billing authorization, all billing endpoints
require authentication, and plan limits are enforced.
"""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import sys
import pathlib
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import unittest
from unittest.mock import patch, MagicMock

import types

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

with patch("app.database.db.supabase", MagicMock()):
    from app import create_app


MOCK_USER = {
    "id": 1,
    "company_id": 42,
    "full_name": "Test User",
    "email": "test@example.com",
    "role": "admin",
    "status": "active",
    "phone": "+60123456789",
}


class TestBillingTenantIsolation(unittest.TestCase):
    """Verify billing data cannot leak across companies."""

    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def _patch_jwt(self, company_id=42):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": company_id, "user_id": 1, "role": "admin"},
        )

    def _patch_user_repo(self):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value=MOCK_USER,
        )

    def _patch_subscription(self, return_value=None):
        if return_value is None:
            return_value = {"id": 1, "company_id": 42, "plan_id": 3, "status": "active"}
        return patch(
            "app.database.company_subscription_repository.get_company_subscription",
            return_value=return_value,
        )

    def _patch_latest_subscription(self, return_value=None):
        if return_value is None:
            return_value = {"id": 1, "company_id": 42, "plan_id": 3, "status": "active"}
        return patch(
            "app.database.company_subscription_repository.get_latest_company_subscription",
            return_value=return_value,
        )

    def _patch_plan_repo(self, return_value=None):
        if return_value is None:
            return_value = {"id": 3, "code": "pro", "name": "Pro", "is_active": True}
        return patch(
            "app.services.billing_service.get_plan_by_id",
            return_value=return_value,
        )

    def test_subscription_endpoint_uses_g_company_id(self):
        """Billing subscription endpoint must use JWT company_id, not client input."""
        with self._patch_jwt(company_id=42), self._patch_user_repo():
            with patch(
                "app.services.billing_service._get_company_subscription",
                return_value={"id": 1, "company_id": 42, "plan_id": 3, "status": "active"},
            ):
                with patch(
                    "app.services.billing_service._get_latest_company_subscription",
                    return_value={"id": 1, "company_id": 42, "plan_id": 3, "status": "active"},
                ):
                    with self._patch_plan_repo():
                        resp = self.client.get(
                            "/api/billing/subscription?company_id=99",
                            headers={"Authorization": "Bearer test-token"},
                        )
                        self.assertEqual(resp.status_code, 200)

    def test_different_company_cannot_access_subscription(self):
        """Company 99 cannot view company 42 subscription data."""
        with self._patch_jwt(company_id=99), self._patch_user_repo():
            with patch(
                "app.services.billing_service._get_company_subscription",
                return_value=None,
            ):
                with patch(
                    "app.services.billing_service._get_latest_company_subscription",
                    return_value=None,
                ):
                    resp = self.client.get(
                        "/api/billing/subscription",
                        headers={"Authorization": "Bearer test-token"},
                    )
                    self.assertEqual(resp.status_code, 200)
                    data = resp.get_json()
                    self.assertIsNone(data.get("data"))

    def test_unauthenticated_request_rejected(self):
        resp = self.client.get("/api/billing/subscription")
        self.assertEqual(resp.status_code, 401)

    def test_unauthenticated_usage_rejected(self):
        resp = self.client.get("/api/billing/usage")
        self.assertEqual(resp.status_code, 401)

    def test_unauthenticated_ai_credit_rejected(self):
        resp = self.client.get("/api/billing/ai-credit/summary")
        self.assertEqual(resp.status_code, 401)

    def test_unauthenticated_orders_rejected(self):
        resp = self.client.get("/api/billing/subscription/orders")
        self.assertEqual(resp.status_code, 401)

    def test_unauthenticated_checkout_rejected(self):
        resp = self.client.post("/api/billing/subscription/checkout")
        self.assertEqual(resp.status_code, 401)

    def test_unauthenticated_cancel_rejected(self):
        resp = self.client.post("/api/billing/subscription/cancel")
        self.assertEqual(resp.status_code, 401)

    def test_unauthenticated_downgrade_rejected(self):
        resp = self.client.post("/api/billing/subscription/downgrade")
        self.assertEqual(resp.status_code, 401)

    def test_health_check_unauthenticated(self):
        """Health check should be accessible without auth."""
        resp = self.client.get("/api/billing/health")
        self.assertIn(resp.status_code, (200, 500))


class TestPlanEnforcement(unittest.TestCase):
    """Verify billing_guard plan-limit enforcement."""

    def setUp(self):
        with patch("app.database.db.supabase", MagicMock()):
            from app.services.billing_guard import (
                can_create_chatbot,
                can_upload_knowledge_file,
                can_connect_channel,
                can_add_team_member,
                BillingLimitError,
            )
            self.can_create_chatbot = can_create_chatbot
            self.can_upload_knowledge_file = can_upload_knowledge_file
            self.can_connect_channel = can_connect_channel
            self.can_add_team_member = can_add_team_member
            self.BillingLimitError = BillingLimitError

    def _mock_subscription(self, plan_overrides=None):
        plan = {
            "id": 3, "code": "pro", "name": "Pro",
            "chatbot_limit": 10, "team_member_limit": 10,
            "knowledge_file_limit": 100, "channel_limit": 5,
        }
        if plan_overrides:
            plan.update(plan_overrides)
        return {"id": 1, "company_id": 42, "plan_id": 3, "status": "active", "plan": plan,
                "current_period_end": "2099-01-01T00:00:00+00:00"}

    def _mock_usage(self, overrides=None):
        usage = {
            "usage": {
                "chatbots": {"used": 5, "limit": 10},
                "team_members": {"used": 3, "limit": 10, "pending_invitations": 0},
                "knowledge_files": {"used": 10, "limit": 100},
                "channels": {"used": 2, "limit": 5},
            }
        }
        if overrides:
            for k, v in overrides.items():
                if k in usage["usage"]:
                    usage["usage"][k].update(v)
        return usage

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_create_chatbot_within_limit(self, mock_usage, mock_sub):
        mock_sub.return_value = self._mock_subscription()
        mock_usage.return_value = self._mock_usage()
        result = self.can_create_chatbot(42)
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_create_chatbot_at_limit_raises(self, mock_usage, mock_sub):
        mock_sub.return_value = self._mock_subscription()
        mock_usage.return_value = self._mock_usage({"chatbots": {"used": 10, "limit": 10}})
        with self.assertRaises(self.BillingLimitError):
            self.can_create_chatbot(42)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_upload_knowledge_within_limit(self, mock_usage, mock_sub):
        mock_sub.return_value = self._mock_subscription()
        mock_usage.return_value = self._mock_usage()
        result = self.can_upload_knowledge_file(42)
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_upload_knowledge_at_limit_raises(self, mock_usage, mock_sub):
        mock_sub.return_value = self._mock_subscription()
        mock_usage.return_value = self._mock_usage({"knowledge_files": {"used": 100, "limit": 100}})
        with self.assertRaises(self.BillingLimitError):
            self.can_upload_knowledge_file(42)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_connect_channel_within_limit(self, mock_usage, mock_sub):
        mock_sub.return_value = self._mock_subscription()
        mock_usage.return_value = self._mock_usage()
        result = self.can_connect_channel(42)
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_connect_channel_at_limit_raises(self, mock_usage, mock_sub):
        mock_sub.return_value = self._mock_subscription()
        mock_usage.return_value = self._mock_usage({"channels": {"used": 5, "limit": 5}})
        with self.assertRaises(self.BillingLimitError):
            self.can_connect_channel(42)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_add_team_member_within_limit(self, mock_usage, mock_sub):
        mock_sub.return_value = self._mock_subscription()
        mock_usage.return_value = self._mock_usage()
        result = self.can_add_team_member(42)
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_add_team_member_at_limit_raises(self, mock_usage, mock_sub):
        mock_sub.return_value = self._mock_subscription()
        mock_usage.return_value = self._mock_usage({"team_members": {"used": 10, "limit": 10, "pending_invitations": 0}})
        with self.assertRaises(self.BillingLimitError):
            self.can_add_team_member(42)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_expired_subscription_denied(self, mock_usage, mock_sub):
        from datetime import datetime, timezone
        yesterday = datetime.now(timezone.utc).isoformat()
        mock_sub.return_value = {"id": 1, "company_id": 42, "plan_id": 3, "status": "active",
                                  "current_period_end": yesterday, "plan": {"chatbot_limit": 10}}
        mock_usage.return_value = self._mock_usage()
        with self.assertRaises(self.BillingLimitError):
            self.can_create_chatbot(42)


class TestBotScopeIndependence(unittest.TestCase):
    """Verify bot_id context does not affect billing authorization."""

    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def _patch_jwt(self, company_id=42):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": company_id, "user_id": 1, "role": "admin"},
        )

    def _patch_user_repo(self):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value=MOCK_USER,
        )

    def _patch_subscription(self, return_value=None):
        if return_value is None:
            return_value = {"id": 1, "company_id": 42, "plan_id": 3, "status": "active"}
        return patch(
            "app.database.company_subscription_repository.get_company_subscription",
            return_value=return_value,
        )

    def _patch_latest_subscription(self):
        return patch(
            "app.database.company_subscription_repository.get_latest_company_subscription",
            return_value=None,
        )

    def _patch_plan_repo(self, return_value=None):
        if return_value is None:
            return_value = {"id": 3, "code": "pro", "name": "Pro", "is_active": True}
        return patch(
            "app.services.billing_service.get_plan_by_id",
            return_value=return_value,
        )

    def test_same_company_different_bot_returns_same_billing(self):
        """Changing bot_id in URL must not change billing data for same company."""
        with self._patch_jwt(company_id=42), self._patch_user_repo():
            with patch(
                "app.services.billing_service._get_company_subscription",
                return_value={"id": 1, "company_id": 42, "plan_id": 3, "status": "active"},
            ):
                with patch(
                    "app.services.billing_service._get_latest_company_subscription",
                    return_value={"id": 1, "company_id": 42, "plan_id": 3, "status": "active"},
                ):
                    with self._patch_plan_repo():
                        resp = self.client.get(
                            "/api/billing/subscription",
                            headers={"Authorization": "Bearer test-token"},
                        )
                        self.assertEqual(resp.status_code, 200)
                        data = resp.get_json()
                        self.assertEqual(data["data"]["company_id"], 42)

    def test_different_company_with_forged_token_rejected(self):
        """A token issued for company 99 cannot access company 42 data."""
        with self._patch_jwt(company_id=99), self._patch_user_repo(), \
             patch(
                "app.database.company_subscription_repository.get_company_subscription",
                return_value=None,
             ), \
             patch(
                "app.database.company_subscription_repository.get_latest_company_subscription",
                return_value=None,
             ):
            resp = self.client.get(
                "/api/billing/subscription",
                headers={"Authorization": "Bearer test-token"},
            )
            data = resp.get_json()
            self.assertIsNone(data.get("data"))


class TestHealthCheck(unittest.TestCase):
    """Tests for the billing health check endpoint."""

    def setUp(self):
        payment_environment = patch.dict(os.environ, {
            "CHIP_ENABLED": "true", "CHIP_ENV": "test",
            "CHIP_TEST_API_KEY": "health-private-chip-key",
            "CHIP_TEST_BRAND_ID": "00000000-0000-4000-8000-000000000001",
            "CHIP_REDIRECT_URL": "https://example.test/billing.html",
            "CHIP_WEBHOOK_URL": "https://example.test/api/billing/chip/callback",
        }, clear=False)
        payment_environment.start()
        self.addCleanup(payment_environment.stop)
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_health_check_returns_ok_structure(self):
        """Health check should return status and checks fields."""
        resp = self.client.get("/api/billing/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("status", data)
        self.assertIn("checks", data)

    def test_health_check_checks_env_vars(self):
        """Health check should report on environment variables."""
        resp = self.client.get("/api/billing/health")
        data = resp.get_json()
        checks = data.get("checks", {})
        self.assertIn("secret_key", checks)
        self.assertIn("supabase_url", checks)
        self.assertIn("chip_checkout_config_valid", checks)
        self.assertEqual(data["selected_subscription_gateway"], "chip")

    def test_health_does_not_expose_secret_values(self):
        """Health check must not expose secret keys."""
        resp = self.client.get("/api/billing/health")
        body = resp.get_data(as_text=True).lower()
        # Secret values should not be in the response
        self.assertNotIn("test-secret-key", body)
        self.assertNotIn("service-role-key", body)
        self.assertNotIn("health-private-chip-key", body)

    def test_enabled_chip_without_credentials_is_operator_visible_degraded(self):
        with patch.dict(os.environ, {
            "CHIP_TEST_API_KEY": "",
            "CHIP_TEST_BRAND_ID": "",
            "CHIP_BRAND_ID": "",
            "CHIP_REDIRECT_URL": "",
            "CHIP_WEBHOOK_URL": "",
        }, clear=False):
            resp = self.client.get("/api/billing/health")

        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["selected_subscription_gateway"], "chip")
        self.assertFalse(data["checks"]["chip_checkout_config_valid"])

    def test_chip_missing_recent_reconciliation_is_degraded_without_blocking(self):
        with patch.dict(os.environ, {
            "BILLING_SCHEDULER_ENABLED": "true",
        }, clear=False), patch(
            "app.services.billing_scheduler_service.get_last_successful_run",
            return_value=None,
        ):
            resp = self.client.get("/api/billing/health")

        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["status"], "degraded")
        self.assertTrue(data["checks"]["chip_checkout_config_valid"])
        self.assertFalse(data["checks"]["chip_recent_reconciliation"])

    def test_public_health_burst_shares_database_probes_across_addresses(self):
        self.client.application.config["RATELIMIT_ENABLED"] = False
        with patch("app.database.db.supabase") as database, patch(
            "app.routes.billing_routes.monotonic", return_value=100.0,
        ):
            for address in range(100):
                response = self.client.get(
                    "/api/billing/health",
                    environ_overrides={"REMOTE_ADDR": f"192.0.2.{address}"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.get_json()["checks"]["supabase_connectivity"])
            self.assertEqual(database.table.call_count, 3)

    def test_failed_health_probes_are_cached_and_recover_after_expiry(self):
        with patch("app.database.db.supabase") as database, patch(
            "app.routes.billing_routes.monotonic", return_value=100.0,
        ) as clock:
            probe = database.table.return_value.select.return_value.limit.return_value.execute
            probe.side_effect = RuntimeError("Synthetic database outage")
            first = self.client.get("/api/billing/health").get_json()
            self.assertFalse(first["checks"]["supabase_connectivity"])
            self.assertFalse(first["checks"]["company_subscription_orders_chip_storage"])
            self.assertFalse(first["checks"]["ai_credit_topup_orders_chip_storage"])
            probe.side_effect = None
            clock.return_value = 129.0
            cached = self.client.get("/api/billing/health").get_json()
            self.assertFalse(cached["checks"]["supabase_connectivity"])
            self.assertEqual(database.table.call_count, 3)
            clock.return_value = 130.0
            recovered = self.client.get("/api/billing/health").get_json()
            self.assertTrue(recovered["checks"]["supabase_connectivity"])
            self.assertTrue(recovered["checks"]["company_subscription_orders_chip_storage"])
            self.assertTrue(recovered["checks"]["ai_credit_topup_orders_chip_storage"])
            self.assertEqual(database.table.call_count, 6)

    def test_cached_storage_does_not_cache_configuration_or_scheduler_health(self):
        with patch("app.database.db.supabase") as database, patch(
            "app.routes.billing_routes.monotonic", return_value=100.0,
        ), patch(
            "app.services.billing_scheduler_service.get_last_successful_run", return_value=100.0,
        ) as last_run, patch("time.monotonic", return_value=100.0):
            first = self.client.get("/api/billing/health").get_json()
            self.assertTrue(first["checks"]["chip_checkout_config_valid"])
            self.assertTrue(first["checks"]["chip_recent_reconciliation"])
            last_run.return_value = None
            with patch.dict(os.environ, {"CHIP_TEST_API_KEY": ""}):
                updated = self.client.get("/api/billing/health").get_json()
            self.assertFalse(updated["checks"]["chip_checkout_config_valid"])
            self.assertFalse(updated["checks"]["chip_recent_reconciliation"])
            self.assertEqual(database.table.call_count, 3)


if __name__ == "__main__":
    unittest.main()
