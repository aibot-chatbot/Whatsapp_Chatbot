"""Tenant AI-credit analytics tests."""

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

if "google" not in sys.modules:
    _google = types.ModuleType("google")
    _google.genai = types.ModuleType("google.genai")
    _google.genai.Client = MagicMock()
    sys.modules["google"] = _google
    sys.modules["google.genai"] = _google.genai

if "fitz" not in sys.modules:
    sys.modules["fitz"] = types.ModuleType("fitz")


class TestAiCreditAnalyticsService(unittest.TestCase):
    def test_aggregates_spend_tokens_models_and_legacy_usage(self):
        from app.services import ai_credit_service

        usage_rows = [
            {
                "id": 10,
                "provider": "openrouter",
                "model": "openai/gpt-4.1",
                "operation_type": "chat_reply",
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "total_tokens": 140,
                "created_at": "2026-08-19T10:00:00+00:00",
            },
            {
                "id": 11,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "operation_type": "knowledge_extraction",
                "prompt_tokens": 25,
                "completion_tokens": 15,
                "total_tokens": 40,
                "created_at": "2026-08-19T11:00:00+00:00",
            },
        ]
        credit_rows = [
            {
                "transaction_type": "usage_debit",
                "customer_charge_micro_myr": 30000,
                "ai_usage_log_id": 10,
                "created_at": "2026-08-19T10:00:02+00:00",
            },
            {
                "transaction_type": "usage_debit",
                "included_delta_micro_myr": -7000,
                "topup_delta_micro_myr": -3000,
                "ai_usage_log_id": None,
                "created_at": "2026-08-18T10:00:02+00:00",
            },
        ]

        with patch.object(ai_credit_service, "_list_usage_by_range", return_value=usage_rows) as usage, \
             patch.object(ai_credit_service, "_list_transactions_by_range_strict", return_value=credit_rows) as txns, \
             patch.object(ai_credit_service, "_get_balance", return_value={
                 "included_balance_micro_myr": 1000000,
                 "topup_balance_micro_myr": 250000,
             }):
            result = ai_credit_service.get_company_ai_usage_analytics(42, days=30)

        usage.assert_called_once()
        txns.assert_called_once()
        self.assertEqual(result["summary"]["ai_spend_micro_myr"], 40000)
        self.assertEqual(result["summary"]["input_tokens"], 125)
        self.assertEqual(result["summary"]["output_tokens"], 55)
        self.assertEqual(result["summary"]["total_tokens"], 180)
        self.assertEqual(result["summary"]["most_used_model"], "openai/gpt-4.1")
        self.assertEqual(result["summary"]["request_count"], 2)
        self.assertEqual(result["summary"]["average_cost_per_million_tokens_micro_myr"], 222222222)
        self.assertEqual(result["summary"]["ai_credit_balance_micro_myr"], 1250000)
        self.assertEqual(result["request_trend"][-2]["request_count"], 2)
        self.assertEqual(result["legacy"]["legacy_spend_micro_myr"], 10000)
        self.assertEqual(result["models"][0]["customer_charge_micro_myr"], 30000)
        self.assertEqual(result["model_daily_usage"][0]["model"], "openai/gpt-4.1")
        self.assertEqual(result["model_daily_usage"][0]["days"][-2]["total_tokens"], 140)
        self.assertEqual(result["operations"][0]["operation_type"], "chat_reply")
        self.assertEqual(result["providers"][0]["input_tokens"], 100)

    def test_rejects_unapproved_period(self):
        from app.services.ai_credit_service import get_company_ai_usage_analytics

        with self.assertRaises(ValueError):
            get_company_ai_usage_analytics(42, days=365)

    def test_credit_ledger_query_failure_propagates(self):
        from app.services import ai_credit_service

        with patch.object(ai_credit_service, "_list_usage_by_range", return_value=[]), \
             patch.object(
                 ai_credit_service,
                 "_list_transactions_by_range_strict",
                 side_effect=RuntimeError("ledger unavailable"),
             ), \
             patch.object(ai_credit_service, "_get_balance", return_value=None):
            with self.assertRaises(RuntimeError):
                ai_credit_service.get_company_ai_usage_analytics(42, days=30)


class TestAiCreditAnalyticsRoute(unittest.TestCase):
    def setUp(self):
        with patch("app.database.db.supabase", MagicMock()):
            from app import create_app

            app = create_app()
            app.config["TESTING"] = True
            self.client = app.test_client()

    def _patch_jwt_decode(self, company_id=42):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": company_id, "user_id": 1, "role": "admin"},
        )

    def _patch_user_repo(self):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value={
                "id": 1,
                "company_id": 42,
                "role": "admin",
                "status": "active",
            },
        )

    def test_route_uses_authenticated_company_scope(self):
        payload = {
            "period": {"days": 30},
            "summary": {"ai_spend_micro_myr": 0},
            "spend_trend": [],
            "token_trend": [],
            "models": [],
            "providers": [],
            "legacy": {},
        }
        with self._patch_jwt_decode(company_id=42), self._patch_user_repo(), patch(
            "app.routes.billing_routes.get_company_ai_usage_analytics",
            return_value=payload,
        ) as analytics:
            resp = self.client.get(
                "/api/billing/ai-credit/analytics?days=30&company_id=99",
                headers={"Authorization": "Bearer test-token"},
            )

        self.assertEqual(resp.status_code, 200)
        analytics.assert_called_once_with(42, days=30)

    def test_route_rejects_invalid_period(self):
        with self._patch_jwt_decode(company_id=42), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/ai-credit/analytics?days=365",
                headers={"Authorization": "Bearer test-token"},
            )

        self.assertEqual(resp.status_code, 400)

    def test_route_returns_error_when_ledger_query_fails(self):
        with self._patch_jwt_decode(company_id=42), self._patch_user_repo(), patch(
            "app.routes.billing_routes.get_company_ai_usage_analytics",
            side_effect=RuntimeError("ledger unavailable"),
        ):
            resp = self.client.get(
                "/api/billing/ai-credit/analytics?days=30",
                headers={"Authorization": "Bearer test-token"},
            )

        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertEqual(body["status"], "error")
        self.assertIn("Unable to retrieve AI usage analytics", body["message"])


class TestProfileAiAnalyticsFrontend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("frontend/profile.html", "r", encoding="utf-8") as f:
            cls.html = f.read()

    def test_analytics_endpoint_and_period_selector_are_wired(self):
        self.assertIn("/api/billing/ai-credit/analytics?days=", self.html)
        self.assertIn('id="ai-analytics-period-select"', self.html)
        self.assertIn("Last 30 days", self.html)
        self.assertIn("Top Model by Tokens", self.html)

    def test_visualization_containers_exist(self):
        self.assertIn('id="ai-usage-analytics-section"', self.html)
        self.assertIn('id="ai-main-chart"', self.html)
        self.assertIn('id="ai-model-time-chart"', self.html)
        self.assertIn('id="ai-feature-chart"', self.html)
        self.assertIn('id="ai-provider-chart"', self.html)
        self.assertIn('id="ai-model-table-body"', self.html)

    def test_empty_and_legacy_copy_exists(self):
        self.assertIn("No AI usage recorded for this period", self.html)
        self.assertIn("Model information unavailable for legacy usage", self.html)


if __name__ == "__main__":
    unittest.main()
