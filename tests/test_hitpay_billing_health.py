"""HitPay readiness checks use mocked storage and never contact the provider."""

import time
import unittest
from unittest.mock import MagicMock, patch

from app import create_app


class TestHitPayBillingHealth(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()
        self.environment = {
            "SECRET_KEY": "test-secret",
            "SUPABASE_URL": "https://test.invalid",
            "SUPABASE_SERVICE_ROLE_KEY": "test-service-key",
            "HITPAY_ENABLED": "true",
            "HITPAY_ENV": "sandbox",
            "HITPAY_API_KEY": "test-api-key",
            "HITPAY_WEBHOOK_SALT": "test-salt",
            "HITPAY_REDIRECT_URL": "https://app.example/return",
            "HITPAY_WEBHOOK_URL": "https://app.example/webhook",
            "BILLING_SCHEDULER_ENABLED": "true",
        }

    def health(self, overrides=None, missing_orders=False):
        database = MagicMock()

        def table(name):
            if missing_orders and name == "company_subscription_orders":
                raise RuntimeError("order storage unavailable")
            return MagicMock()

        database.table.side_effect = table
        with (
            patch.dict("os.environ", {**self.environment, **(overrides or {})}),
            patch("app.routes.billing_routes.get_subscription_payment_gateway", return_value="hitpay"),
            patch("app.services.billing_scheduler_service.get_last_successful_run", return_value=time.monotonic()),
            patch("app.database.db.supabase", database),
        ):
            response = self.client.get("/api/billing/health")

        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_valid_configuration_and_order_storage_are_healthy(self):
        result = self.health()
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["checks"]["hitpay_checkout_config_valid"])
        self.assertTrue(result["checks"]["hitpay_order_storage"])
        self.assertNotIn("test-api-key", str(result))
        self.assertNotIn("https://app.example", str(result))

    def test_invalid_checkout_or_webhook_url_is_degraded(self):
        for name, value in (
            ("HITPAY_REDIRECT_URL", "http://app.example/return"),
            ("HITPAY_WEBHOOK_URL", "not-a-url"),
        ):
            with self.subTest(name=name):
                result = self.health({name: value})
                self.assertEqual(result["status"], "degraded")
                self.assertFalse(result["checks"]["hitpay_checkout_config_valid"])

    def test_missing_order_storage_is_degraded_even_when_plans_are_reachable(self):
        result = self.health(missing_orders=True)
        self.assertEqual(result["status"], "degraded")
        self.assertTrue(result["checks"]["supabase_connectivity"])
        self.assertFalse(result["checks"]["hitpay_order_storage"])
