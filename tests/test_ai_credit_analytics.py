"""Tenant AI-credit analytics tests."""

import os
import sys
import types
import re
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone


# --- Billing moved out of profile.html (2026-09) -------------------------------
# The billing surface now lives on its own page, split across markup, logic and
# styles. These assertions guard the billing guarantees, so they read all three
# parts of that page as one source rather than a single monolithic file.
def _read_billing_source():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _parts = []
    for _rel in (("billing.html",), ("assets", "js", "billing.js"), ("assets", "css", "billing.css")):
        _path = os.path.join(_root, "frontend", *_rel)
        with open(_path, "r", encoding="utf-8", errors="replace") as _fh:
            _parts.append(_fh.read())
    return chr(10).join(_parts)


def _fn_body(source, name):
    """Return the brace-matched body of a JS function declaration."""
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\(", source)
    if not m:
        raise AssertionError("function %s not found in billing source" % name)
    start = source.index("{", m.end() - 1)
    depth = 0
    for j in range(start, len(source)):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[start:j + 1]
    raise AssertionError("unbalanced braces in %s" % name)
# ------------------------------------------------------------------------------



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

        # The service asks for a rolling ``days=30`` window ending today, so
        # fixture rows pinned to fixed calendar dates silently age out of it --
        # this test started failing on 2026-09-18 for that reason alone, with
        # nothing in the code having changed. Anchoring to today keeps the two
        # days inside any window of three days or more.
        active_day = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
        prior_day = (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()

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
                "created_at": f"{active_day}T10:00:00+00:00",
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
                "created_at": f"{active_day}T11:00:00+00:00",
            },
        ]
        credit_rows = [
            {
                "transaction_type": "usage_debit",
                "customer_charge_micro_myr": 30000,
                "ai_usage_log_id": 10,
                "created_at": f"{active_day}T10:00:02+00:00",
            },
            {
                "transaction_type": "usage_debit",
                "included_delta_micro_myr": -7000,
                "topup_delta_micro_myr": -3000,
                "ai_usage_log_id": None,
                "created_at": f"{prior_day}T10:00:02+00:00",
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
        active_request_days = [
            row for row in result["request_trend"]
            if row["date"] == active_day
        ]
        self.assertEqual(active_request_days[0]["request_count"], 2)
        self.assertEqual(result["legacy"]["legacy_spend_micro_myr"], 10000)
        self.assertEqual(result["models"][0]["customer_charge_micro_myr"], 30000)
        self.assertEqual(result["model_daily_usage"][0]["model"], "openai/gpt-4.1")
        active_model_days = [
            row for row in result["model_daily_usage"][0]["days"]
            if row["date"] == active_day
        ]
        self.assertEqual(active_model_days[0]["total_tokens"], 140)
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

    def test_historical_guide_assistant_usage_remains_reportable(self):
        from app.services import ai_credit_service

        usage_rows = [{
            "id": 31,
            "chatbot_id": 7,
            "provider": "deepseek",
            "model": "deepseek-chat",
            "operation_type": "guide_assistant",
            "prompt_tokens": 90,
            "completion_tokens": 30,
            "total_tokens": 120,
            "created_at": "2026-08-19T10:00:00+00:00",
        }]
        credit_rows = [{
            "transaction_type": "usage_debit",
            "customer_charge_micro_myr": 12000,
            "ai_usage_log_id": 31,
            "created_at": "2026-08-19T10:00:01+00:00",
        }]

        with patch.object(ai_credit_service, "_list_usage_by_range", side_effect=[usage_rows, usage_rows]), \
             patch.object(ai_credit_service, "_list_transactions_by_range_strict", return_value=credit_rows), \
             patch.object(ai_credit_service, "_list_bots_by_ids", return_value=[{"id": 7, "bot_name": "Legacy Bot"}]), \
             patch.object(ai_credit_service, "_get_balance", return_value=None):
            result = ai_credit_service.get_company_ai_usage_analytics(42, days=30)

        self.assertEqual(result["summary"]["request_count"], 1)
        self.assertEqual(result["summary"]["ai_spend_micro_myr"], 12000)
        self.assertEqual(result["operations"][0]["operation_type"], "guide_assistant")
        self.assertEqual(result["operations"][0]["total_tokens"], 120)


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
        cls.html = _read_billing_source()

    def test_analytics_endpoint_and_period_selector_are_wired(self):
        self.assertIn("/api/billing/ai-credit/analytics?", self.html)
        self.assertIn('id="bl-analytics-period"', self.html)
        self.assertIn("Last 30 days", self.html)
        self.assertIn("Top Model by Tokens", self.html)

    def test_filter_controls_are_wired(self):
        self.assertIn('id="bl-filter-chatbot"', self.html)
        self.assertIn('id="bl-filter-provider"', self.html)
        self.assertIn('id="bl-filter-model"', self.html)
        self.assertIn('id="bl-filter-feature"', self.html)
        self.assertIn("Reset Filters", self.html)
        self.assertIn('"chatbot_id", "bl-filter-chatbot"', self.html)
        self.assertIn('"provider", "bl-filter-provider"', self.html)
        self.assertIn('"model", "bl-filter-model"', self.html)
        self.assertIn('"operation_type", "bl-filter-feature"', self.html)
        self.assertIn("No AI usage matches these filters for the selected period.", self.html)

    def test_unavailable_chatbot_options_are_disabled(self):
        """Unavailable chatbots appear as disabled options and are excluded
        from the available set used to validate the current selection."""
        body = _fn_body(self.html, "populateFilter")
        self.assertRegex(body, re.compile(r"if \(\w+\.disabled\)\s*\w+\.disabled = true;"))
        self.assertRegex(body, re.compile(r"filter\(function \(\w+\) \{ return !\w+\.disabled; \}\)"))

    def test_visualization_containers_exist(self):
        self.assertIn('id="bl-analytics"', self.html)
        self.assertIn('id="bl-main-chart"', self.html)
        self.assertIn('id="bl-model-chart"', self.html)
        self.assertIn('id="bl-feature-chart"', self.html)
        self.assertIn('id="bl-provider-chart"', self.html)
        self.assertIn('id="bl-model-table"', self.html)

    def test_empty_and_legacy_copy_exists(self):
        self.assertIn("No AI usage recorded for this period", self.html)
        self.assertIn("Model information unavailable for legacy usage", self.html)


if __name__ == "__main__":
    unittest.main()
