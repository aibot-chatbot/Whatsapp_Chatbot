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


class _UsageQuery:
    def __init__(self):
        self.calls = []
        self.data = [{"id": 1}]

    def select(self, value):
        self.calls.append(("select", value))
        return self

    def eq(self, key, value):
        self.calls.append(("eq", key, value))
        return self

    def gte(self, key, value):
        self.calls.append(("gte", key, value))
        return self

    def lt(self, key, value):
        self.calls.append(("lt", key, value))
        return self

    def order(self, key, desc=False):
        self.calls.append(("order", key, desc))
        return self

    def execute(self):
        return types.SimpleNamespace(data=self.data)


class TestAiUsageRepositoryFilters(unittest.TestCase):
    def test_usage_range_query_applies_optional_filters(self):
        from app.database import ai_usage_repository

        query = _UsageQuery()
        supabase = MagicMock()
        supabase.table.return_value = query

        with patch.object(ai_usage_repository, "supabase", supabase):
            rows = ai_usage_repository.list_company_completed_usage_by_range(
                42,
                "2026-08-01T00:00:00+00:00",
                "2026-08-31T00:00:00+00:00",
                chatbot_id=7,
                provider="openrouter",
                model="openai/gpt-5.5",
                operation_type="chat_reply",
            )

        self.assertEqual(rows, [{"id": 1}])
        self.assertIn(("eq", "company_id", 42), query.calls)
        self.assertIn(("eq", "request_status", "completed"), query.calls)
        self.assertIn(("eq", "chatbot_id", 7), query.calls)
        self.assertIn(("eq", "provider", "openrouter"), query.calls)
        self.assertIn(("eq", "model", "openai/gpt-5.5"), query.calls)
        self.assertIn(("eq", "operation_type", "chat_reply"), query.calls)


class TestAiCreditAnalyticsService(unittest.TestCase):
    def test_aggregates_spend_tokens_models_and_legacy_usage(self):
        from app.services import ai_credit_service

        usage_rows = [
            {
                "id": 10,
                "chatbot_id": 7,
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
                "chatbot_id": 8,
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
             patch.object(ai_credit_service, "_list_bots_by_ids", return_value=[
                 {"id": 7, "bot_name": "Support Bot"},
                 {"id": 8, "bot_name": "Training Bot"},
             ]), \
             patch.object(ai_credit_service, "_get_balance", return_value={
                 "included_balance_micro_myr": 1000000,
                 "topup_balance_micro_myr": 250000,
             }):
            result = ai_credit_service.get_company_ai_usage_analytics(42, days=30)

        self.assertEqual(usage.call_count, 2)
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
        self.assertEqual(result["available_filters"]["chatbots"][0]["name"], "Support Bot")
        self.assertEqual(result["available_filters"]["providers"][0]["value"], "deepseek")

    def test_filters_are_passed_to_usage_query_and_legacy_spend_is_excluded(self):
        from app.services import ai_credit_service

        option_rows = [
            {
                "id": 10,
                "chatbot_id": 7,
                "provider": "openrouter",
                "model": "openai/gpt-5.5",
                "operation_type": "knowledge_extraction",
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "created_at": "2026-08-19T10:00:00+00:00",
            },
            {
                "id": 11,
                "chatbot_id": 8,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "operation_type": "test_bot",
                "prompt_tokens": 200,
                "completion_tokens": 80,
                "total_tokens": 280,
                "created_at": "2026-08-19T11:00:00+00:00",
            },
        ]
        filtered_rows = [option_rows[0]]
        credit_rows = [
            {
                "transaction_type": "usage_debit",
                "customer_charge_micro_myr": 25000,
                "ai_usage_log_id": 10,
                "created_at": "2026-08-19T10:00:01+00:00",
            },
            {
                "transaction_type": "usage_debit",
                "customer_charge_micro_myr": 99000,
                "ai_usage_log_id": 11,
                "created_at": "2026-08-19T11:00:01+00:00",
            },
            {
                "transaction_type": "usage_debit",
                "included_delta_micro_myr": -5000,
                "topup_delta_micro_myr": 0,
                "ai_usage_log_id": None,
                "created_at": "2026-08-18T11:00:01+00:00",
            },
        ]

        with patch.object(ai_credit_service, "_get_bot_by_id", return_value={"id": 7, "company_id": 42}), \
             patch.object(ai_credit_service, "_list_usage_by_range", side_effect=[option_rows, filtered_rows]) as usage, \
             patch.object(ai_credit_service, "_list_transactions_by_range_strict", return_value=credit_rows), \
             patch.object(ai_credit_service, "_list_bots_by_ids", return_value=[{"id": 7, "bot_name": "Support Bot"}]), \
             patch.object(ai_credit_service, "_get_balance", return_value=None):
            result = ai_credit_service.get_company_ai_usage_analytics(
                42,
                days=30,
                chatbot_id=7,
                provider="openrouter",
                model="openai/gpt-5.5",
                operation_type="knowledge_extraction",
            )

        filtered_call = usage.call_args_list[1]
        self.assertEqual(filtered_call.kwargs["chatbot_id"], 7)
        self.assertEqual(filtered_call.kwargs["provider"], "openrouter")
        self.assertEqual(filtered_call.kwargs["model"], "openai/gpt-5.5")
        self.assertEqual(filtered_call.kwargs["operation_type"], "knowledge_extraction")
        self.assertEqual(result["summary"]["ai_spend_micro_myr"], 25000)
        self.assertEqual(result["summary"]["request_count"], 1)
        self.assertEqual(result["summary"]["total_tokens"], 150)
        self.assertEqual(result["models"][0]["model"], "openai/gpt-5.5")
        self.assertEqual(result["operations"][0]["operation_type"], "knowledge_extraction")
        self.assertEqual(result["providers"][0]["provider"], "openrouter")
        self.assertEqual(result["legacy"]["legacy_spend_excluded_due_to_filters_micro_myr"], 5000)
        self.assertEqual(result["legacy"]["linked_spend_excluded_due_to_filters_micro_myr"], 99000)
        self.assertEqual(result["legacy"]["usage_debit_with_missing_usage_log_count"], 0)

    def test_deepseek_filter_does_not_infer_spend_without_linked_debits(self):
        from app.services import ai_credit_service

        deepseek_row = {
            "id": 20,
            "chatbot_id": 7,
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "operation_type": "test_bot",
            "prompt_tokens": 200,
            "completion_tokens": 80,
            "total_tokens": 280,
            "created_at": "2026-08-19T11:00:00+00:00",
        }

        with patch.object(ai_credit_service, "_list_usage_by_range", side_effect=[[deepseek_row], [deepseek_row]]), \
             patch.object(ai_credit_service, "_list_transactions_by_range_strict", return_value=[]), \
             patch.object(ai_credit_service, "_list_bots_by_ids", return_value=[{"id": 7, "bot_name": "Support Bot"}]), \
             patch.object(ai_credit_service, "_get_balance", return_value=None):
            result = ai_credit_service.get_company_ai_usage_analytics(42, days=30, provider="deepseek")

        self.assertEqual(result["summary"]["ai_spend_micro_myr"], 0)
        self.assertEqual(result["providers"][0]["provider"], "deepseek")
        self.assertEqual(result["providers"][0]["customer_charge_micro_myr"], 0)

    def test_invalid_or_cross_company_chatbot_is_rejected(self):
        from app.services import ai_credit_service

        with patch.object(ai_credit_service, "_get_bot_by_id", return_value=None):
            with self.assertRaises(ValueError):
                ai_credit_service.get_company_ai_usage_analytics(42, days=30, chatbot_id=999)

    def test_filter_options_keep_unavailable_historical_chatbots_unselectable(self):
        from app.services import ai_credit_service

        usage_rows = [
            {"id": 10, "chatbot_id": 7, "provider": "openrouter", "model": "openai/gpt-5.5", "operation_type": "chat_reply"},
            {"id": 11, "chatbot_id": 99, "provider": "deepseek", "model": "deepseek-v4-flash", "operation_type": "test_bot"},
        ]

        with patch.object(ai_credit_service, "_list_bots_by_ids", return_value=[
            {"id": 7, "bot_name": "Support Bot", "status": "archived"},
        ]):
            filters = ai_credit_service._build_available_filters(42, usage_rows)

        self.assertEqual(filters["chatbots"][0], {
            "id": 7,
            "name": "Support Bot",
            "available": True,
        })
        self.assertEqual(filters["chatbots"][1], {
            "id": 99,
            "name": "Deleted / unavailable chatbot",
            "available": False,
        })

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
        analytics.assert_called_once_with(
            42,
            days=30,
            chatbot_id=None,
            provider=None,
            model=None,
            operation_type=None,
        )

    def test_route_passes_valid_filters(self):
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
                "/api/billing/ai-credit/analytics?days=30&chatbot_id=7&provider=openrouter&model=openai%2Fgpt-5.5&operation_type=chat_reply&company_id=99",
                headers={"Authorization": "Bearer test-token"},
            )

        self.assertEqual(resp.status_code, 200)
        analytics.assert_called_once_with(
            42,
            days=30,
            chatbot_id=7,
            provider="openrouter",
            model="openai/gpt-5.5",
            operation_type="chat_reply",
        )

    def test_route_rejects_invalid_chatbot_filter(self):
        with self._patch_jwt_decode(company_id=42), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/ai-credit/analytics?days=30&chatbot_id=abc",
                headers={"Authorization": "Bearer test-token"},
            )

        self.assertEqual(resp.status_code, 400)

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
        self.assertIn("/api/billing/ai-credit/analytics?", self.html)
        self.assertIn('id="ai-analytics-period-select"', self.html)
        self.assertIn("Last 30 days", self.html)
        self.assertIn("Top Model by Tokens", self.html)

    def test_filter_controls_are_wired(self):
        self.assertIn('id="ai-analytics-chatbot-filter"', self.html)
        self.assertIn('id="ai-analytics-provider-filter"', self.html)
        self.assertIn('id="ai-analytics-model-filter"', self.html)
        self.assertIn('id="ai-analytics-feature-filter"', self.html)
        self.assertIn("Reset Filters", self.html)
        self.assertIn('"chatbot_id", "ai-analytics-chatbot-filter"', self.html)
        self.assertIn('"provider", "ai-analytics-provider-filter"', self.html)
        self.assertIn('"model", "ai-analytics-model-filter"', self.html)
        self.assertIn('"operation_type", "ai-analytics-feature-filter"', self.html)
        self.assertIn("No AI usage matches these filters for the selected period.", self.html)

    def test_unavailable_chatbot_options_are_disabled(self):
        self.assertIn("disabled: bot.available === false", self.html)
        self.assertIn("option.disabled ? ' disabled' : ''", self.html)
        self.assertIn("filter(function(option) { return !option.disabled; })", self.html)

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
