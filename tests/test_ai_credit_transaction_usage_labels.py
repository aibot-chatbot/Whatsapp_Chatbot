"""AI-credit transaction operation-type enrichment regressions."""

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


class _Response:
    def __init__(self, data=None):
        self.data = data or []


class _Query:
    def __init__(self, rows):
        self.rows = list(rows)

    def select(self, *args, **kwargs):
        return self

    def eq(self, field, value):
        self.rows = [row for row in self.rows if row.get(field) == value]
        return self

    def in_(self, field, values):
        allowed = set(values or [])
        self.rows = [row for row in self.rows if row.get(field) in allowed]
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, limit):
        self.rows = self.rows[:limit]
        return self

    def execute(self):
        return _Response(self.rows)


class _FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, table_name):
        return _Query(self.tables.get(table_name, []))


class TestAiCreditTransactionUsageTypeEnrichment(unittest.TestCase):
    def test_repository_attaches_usage_operation_type(self):
        from app.database import ai_credit_repository

        fake_supabase = _FakeSupabase({
            "ai_credit_transactions": [
                {
                    "id": 1,
                    "company_id": 42,
                    "transaction_type": "usage_debit",
                    "ai_usage_log_id": 10,
                },
            ],
            "ai_usage_logs": [
                {"id": 10, "operation_type": "knowledge_extraction"},
            ],
        })

        with patch.object(ai_credit_repository, "supabase", fake_supabase):
            rows = ai_credit_repository.list_company_credit_transactions(42, limit=20)

        self.assertEqual(rows[0]["ai_usage_type"], "knowledge_extraction")

    def test_missing_usage_log_does_not_break_transactions(self):
        from app.database import ai_credit_repository

        fake_supabase = _FakeSupabase({
            "ai_credit_transactions": [
                {
                    "id": 1,
                    "company_id": 42,
                    "transaction_type": "usage_debit",
                    "ai_usage_log_id": 999,
                },
            ],
            "ai_usage_logs": [],
        })

        with patch.object(ai_credit_repository, "supabase", fake_supabase):
            rows = ai_credit_repository.list_company_credit_transactions(42, limit=20)

        self.assertEqual(rows[0]["id"], 1)
        self.assertNotIn("ai_usage_type", rows[0])


class TestAiCreditTransactionsRouteUsageType(unittest.TestCase):
    def setUp(self):
        with patch("app.database.db.supabase", MagicMock()):
            from app import create_app

            app = create_app()
            app.config["TESTING"] = True
            self.client = app.test_client()

    def _patch_jwt_decode(self):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 42, "user_id": 1, "role": "admin"},
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

    def test_api_response_includes_ai_usage_type(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), patch(
            "app.routes.billing_routes.list_credit_transactions",
            return_value=[
                {
                    "id": 1,
                    "transaction_type": "usage_debit",
                    "ai_usage_type": "knowledge_extraction",
                    "ai_usage_log_id": 10,
                },
            ],
        ):
            resp = self.client.get(
                "/api/billing/ai-credit/transactions?limit=20",
                headers={"Authorization": "Bearer test-token"},
            )

        self.assertEqual(resp.status_code, 200)
        txn = resp.get_json()["data"]["transactions"][0]
        self.assertEqual(txn["ai_usage_type"], "knowledge_extraction")


if __name__ == "__main__":
    unittest.main()
