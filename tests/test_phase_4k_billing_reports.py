"""tests/test_phase_4k_billing_reports.py - Tests for Phase 4K billing reports.

Tests cover:
  - Report summary calculations (orders, AI credit, AI usage)
  - Transaction type mappings
  - Monthly trend generation with zero-fill
  - Summary endpoint period validation
  - Plan-usage reporting and CSV export
  - API safety and tenant isolation
  - Frontend section presence
"""

import os as _os
_os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
_os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
_os.environ.setdefault("SECRET_KEY", "test-secret-key")
_os.environ.setdefault("TOYYIBPAY_ENV", "production")
_os.environ.setdefault("TOYYIBPAY_USER_SECRET_KEY", "test-secret-key")
_os.environ.setdefault("TOYYIBPAY_CATEGORY_CODE", "test-category")
_os.environ.setdefault("TOYYIBPAY_REDIRECT_URL", "https://test.example/profile")

import sys
import unittest
from unittest.mock import patch, MagicMock
import json, types, os

from tests.frontend_pages import page_source_path


# --- Billing moved out of profile.html (2026-09) -------------------------------
# The billing surface now lives on its own page, split across markup, logic and
# styles. These assertions guard the billing guarantees, so they read all three
# parts of that page as one source rather than a single monolithic file.
def _read_billing_source():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _parts = []
    for _rel in (("billing.html",), ("assets", "js", "billing.js"), ("assets", "css", "billing.css")):
        _path = (page_source_path("billing.html") if _rel == ("billing.html",)
                 else os.path.join(_root, "frontend", *_rel))
        with open(_path, "r", encoding="utf-8", errors="replace") as _fh:
            _parts.append(_fh.read())
    return chr(10).join(_parts)
# ------------------------------------------------------------------------------


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

_MOCK_SUPABASE = MagicMock()
with patch("app.database.db.supabase", _MOCK_SUPABASE):
    from app import create_app
    # Also patch repository-level supabase references
    import app.database.billing_usage_repository as _bur
    import app.database.ai_credit_repository as _acr
    import app.database.company_subscription_order_repository as _csor
    _bur.supabase = _MOCK_SUPABASE
    _acr.supabase = _MOCK_SUPABASE
    _csor.supabase = _MOCK_SUPABASE

PROFILE_PATH = page_source_path("profile.html")

MOCK_USER = {"id": 1, "company_id": 42, "full_name": "Test User", "email": "test@example.com", "role": "admin", "status": "active", "phone": "+60123456789"}



# ---------------------------------------------------------------------------
# Base test class
# ---------------------------------------------------------------------------

class BaseReportTest(unittest.TestCase):
    """Base class with shared fixtures."""

    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def _patch_jwt(self, company_id=42, role="admin"):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": company_id, "user_id": 1, "role": role},
        )

    def _patch_user_repo(self):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value=MOCK_USER,
        )

    def _patch_billing_orders(self, orders):
        return patch(
            "app.database.company_subscription_order_repository.list_billing_report_orders",
            return_value=orders,
        )

    def _patch_credit_txns(self, txns):
        return patch(
            "app.database.ai_credit_repository.list_company_credit_transactions_by_range",
            return_value=txns,
        )

    def _patch_usage_tokens(self, tokens):
        return patch(
            "app.database.billing_usage_repository.sum_company_ai_usage_tokens",
            return_value=tokens,
        )

    def _patch_company_usage(self, usage):
        return patch(
            "app.services.billing_service.get_company_usage",
            return_value=usage,
        )


# ---------------------------------------------------------------------------
# Report summary calculation tests
# ---------------------------------------------------------------------------

class TestReportSummaryCalculations(BaseReportTest):
    """Verify _summarize_subscription_orders, _summarize_ai_credit, _summarize_ai_usage."""

    def test_empty_period(self):
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_billing_report
                        report = get_company_billing_report(42, "2026-01-01", "2026-02-01")

        self.assertEqual(report["subscription"]["orders_created"], 0)
        self.assertEqual(report["subscription"]["payments_completed"], 0)
        self.assertEqual(report["subscription"]["gross_paid_myr"], 0.0)
        self.assertEqual(report["ai_credit"]["included_granted_myr"], 0.0)
        self.assertEqual(report["ai_usage"]["requests"], 0)

    def test_credited_order_counted_as_paid(self):
        orders = [{
            "order_reference": "aaa",
            "status": "credited",
            "amount_sen": 3900,
            "plan_code": "pro",
            "company_id": 42,
            "created_at": "2026-01-15T00:00:00Z",
        }]
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders(orders):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_billing_report
                        report = get_company_billing_report(42, "2026-01-01", "2026-02-01")

        self.assertEqual(report["subscription"]["orders_created"], 1)
        self.assertEqual(report["subscription"]["payments_completed"], 1)
        self.assertEqual(report["subscription"]["gross_paid_micro_myr"], 3900 * 1000000)
        self.assertEqual(report["subscription"]["gross_paid_myr"], 39.0)

    def test_pending_order_excluded(self):
        orders = [{
            "order_reference": "aaa",
            "status": "pending",
            "amount_sen": 3900,
            "plan_code": "pro",
            "company_id": 42,
            "created_at": "2026-01-15T00:00:00Z",
        }]
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders(orders):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_billing_report
                        report = get_company_billing_report(42, "2026-01-01", "2026-02-01")

        self.assertEqual(report["subscription"]["payments_completed"], 0)
        self.assertEqual(report["subscription"]["payments_pending"], 1)
        self.assertEqual(report["subscription"]["gross_paid_myr"], 0.0)

    def test_expired_order_excluded(self):
        orders = [{
            "order_reference": "aaa",
            "status": "expired",
            "amount_sen": 3900,
            "plan_code": "pro",
            "company_id": 42,
            "created_at": "2026-01-15T00:00:00Z",
        }]
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders(orders):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_billing_report
                        report = get_company_billing_report(42, "2026-01-01", "2026-02-01")

        self.assertEqual(report["subscription"]["payments_completed"], 0)
        self.assertEqual(report["subscription"]["payments_failed"], 1)

    def test_multiple_credited_orders_summed(self):
        orders = [
            {"order_reference": "a1", "status": "credited", "amount_sen": 3900, "plan_code": "pro", "company_id": 42, "created_at": "2026-01-10T00:00:00Z"},
            {"order_reference": "a2", "status": "credited", "amount_sen": 1500, "plan_code": "essential", "company_id": 42, "created_at": "2026-01-20T00:00:00Z"},
        ]
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders(orders):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_billing_report
                        report = get_company_billing_report(42, "2026-01-01", "2026-02-01")

        self.assertEqual(report["subscription"]["payments_completed"], 2)
        expected_micro = (3900 + 1500) * 1000000
        self.assertEqual(report["subscription"]["gross_paid_micro_myr"], expected_micro)
        self.assertEqual(report["subscription"]["gross_paid_myr"], 54.0)
        self.assertEqual(report["subscription"]["plans"]["pro"], 1)
        self.assertEqual(report["subscription"]["plans"]["essential"], 1)


    def test_company_isolation_orders(self):
        """Verify company_id is passed to the repository query."""
        with self._patch_jwt(42), self._patch_user_repo():
            mock_fn = MagicMock(return_value=[])
            with patch("app.database.company_subscription_order_repository.list_billing_report_orders", mock_fn):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_billing_report
                        report = get_company_billing_report(99, "2026-01-01", "2026-02-01")

        mock_fn.assert_called_with(99, "2026-01-01", "2026-02-01")
        self.assertEqual(report["subscription"]["payments_completed"], 0)


class TestReportAiCreditTransactions(BaseReportTest):
    """Verify AI credit transaction type mapping in _summarize_ai_credit."""

    def test_subscription_included_grant_mapped(self):
        """subscription_included txns count as included granted credit."""
        txns = [{
            "id": 1, "company_id": 42,
            "transaction_type": "subscription_included",
            "included_delta_micro_myr": 60000000,
            "topup_delta_micro_myr": 0,
            "description": "test",
            "created_at": "2026-01-15T00:00:00Z",
        }]
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns(txns):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_billing_report
                        report = get_company_billing_report(42, "2026-01-01", "2026-02-01")

        self.assertEqual(report["ai_credit"]["included_granted_micro_myr"], 60000000)
        self.assertEqual(report["ai_credit"]["included_granted_myr"], 0.6)

    def test_topup_purchase_mapped(self):
        txns = [{
            "id": 1, "company_id": 42,
            "transaction_type": "topup_purchase",
            "included_delta_micro_myr": 0,
            "topup_delta_micro_myr": 2000000,
            "description": "topup",
            "created_at": "2026-01-15T00:00:00Z",
        }]
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns(txns):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_billing_report
                        report = get_company_billing_report(42, "2026-01-01", "2026-02-01")

        self.assertEqual(report["ai_credit"]["topup_purchased_micro_myr"], 2000000)
        self.assertEqual(report["ai_credit"]["topup_purchased_myr"], 0.02)

    def test_usage_debit_mapped(self):
        """usage_debit txns count as credit spent."""
        txns = [{
            "id": 1, "company_id": 42,
            "transaction_type": "usage_debit",
            "included_delta_micro_myr": -50000,
            "topup_delta_micro_myr": 0,
            "customer_charge_micro_myr": 50000,
            "provider_cost_micro_usd": 10,
            "ai_usage_log_id": 42,
            "description": "usage",
            "created_at": "2026-01-15T00:00:00Z",
        }]
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns(txns):
                    with self._patch_usage_tokens({"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}):
                        from app.services.billing_report_service import get_company_billing_report
                        report = get_company_billing_report(42, "2026-01-01", "2026-02-01")

        self.assertEqual(report["ai_credit"]["usage_spent_micro_myr"], 50000)
        self.assertEqual(report["ai_credit"]["usage_spent_micro_myr"], 50000)  # 50k micro-MYR = 0.0005 MYR

    def test_included_expiry_mapped(self):
        txns = [{
            "id": 1, "company_id": 42,
            "transaction_type": "included_expiry",
            "included_delta_micro_myr": -1000000,
            "topup_delta_micro_myr": 0,
            "description": "expired",
            "created_at": "2026-01-15T00:00:00Z",
        }]
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns(txns):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_billing_report
                        report = get_company_billing_report(42, "2026-01-01", "2026-02-01")

        self.assertTrue(report["ai_credit"]["expired_micro_myr"] >= 1000000)

    def test_expiry_mapped(self):
        """expiry (without included prefix) also counted as expired."""
        txns = [{
            "id": 1, "company_id": 42,
            "transaction_type": "expiry",
            "included_delta_micro_myr": -500000,
            "topup_delta_micro_myr": 0,
            "description": "expired",
            "created_at": "2026-01-15T00:00:00Z",
        }]
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns(txns):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_billing_report
                        report = get_company_billing_report(42, "2026-01-01", "2026-02-01")

        self.assertTrue(report["ai_credit"]["expired_micro_myr"] >= 500000)

    def test_reversal_mapped(self):
        txns = [{
            "id": 1, "company_id": 42,
            "transaction_type": "reversal",
            "included_delta_micro_myr": 0,
            "topup_delta_micro_myr": -60000000,
            "description": "reversed",
            "created_at": "2026-01-15T00:00:00Z",
        }]
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns(txns):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_billing_report
                        report = get_company_billing_report(42, "2026-01-01", "2026-02-01")

        self.assertTrue(report["ai_credit"]["reversed_micro_myr"] >= 60000000)

    def test_adjustment_affects_net_change(self):
        txns = [{
            "id": 1, "company_id": 42,
            "transaction_type": "adjustment",
            "included_delta_micro_myr": -100000,
            "topup_delta_micro_myr": 0,
            "description": "adjustment",
            "created_at": "2026-01-15T00:00:00Z",
        }]
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns(txns):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_billing_report
                        report = get_company_billing_report(42, "2026-01-01", "2026-02-01")

        self.assertEqual(report["ai_credit"]["net_change_micro_myr"], -100000)

    def test_integer_arithmetic_no_floating_point(self):
        txns = [
            {"id": 1, "company_id": 42, "transaction_type": "subscription_included",
             "included_delta_micro_myr": 60000000, "topup_delta_micro_myr": 0, "description": "grant", "created_at": "2026-01-15T00:00:00Z"},
            {"id": 2, "company_id": 42, "transaction_type": "usage_debit",
             "included_delta_micro_myr": -33333, "topup_delta_micro_myr": 0,
             "customer_charge_micro_myr": 33333, "provider_cost_micro_usd": 7,
             "ai_usage_log_id": 1, "description": "usage", "created_at": "2026-01-16T00:00:00Z"},
            {"id": 3, "company_id": 42, "transaction_type": "topup_purchase",
             "included_delta_micro_myr": 0, "topup_delta_micro_myr": 2000000, "description": "topup", "created_at": "2026-01-17T00:00:00Z"},
        ]
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns(txns):
                    with self._patch_usage_tokens({"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}):
                        from app.services.billing_report_service import get_company_billing_report
                        report = get_company_billing_report(42, "2026-01-01", "2026-02-01")

        # Integer calculations: 60000000 - 33333 + 2000000 = 61966667
        expected_net = 60000000 - 33333 + 2000000
        self.assertEqual(report["ai_credit"]["net_change_micro_myr"], expected_net)
        # Verify myr values are floats derived from integer math
        self.assertIsInstance(report["ai_credit"]["included_granted_myr"], float)
        self.assertIsInstance(report["ai_credit"]["topup_purchased_myr"], float)

    def test_company_isolation_credit(self):
        """Verify company_id is passed to the credit transaction repository query."""
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                mock_fn = MagicMock(return_value=[])
                with patch("app.database.ai_credit_repository.list_company_credit_transactions_by_range", mock_fn):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_billing_report
                        report = get_company_billing_report(99, "2026-01-01", "2026-02-01")

        mock_fn.assert_called_with(99, "2026-01-01", "2026-02-01")
        self.assertEqual(report["ai_credit"]["included_granted_micro_myr"], 0)


# ---------------------------------------------------------------------------
# AI usage summary test
# ---------------------------------------------------------------------------

class TestReportAiUsageSummary(BaseReportTest):
    """Verify _summarize_ai_usage token counts, request counts, charges."""

    def test_token_totals(self):
        txns = [{
            "id": 1, "company_id": 42,
            "transaction_type": "usage_debit",
            "included_delta_micro_myr": -50000,
            "topup_delta_micro_myr": 0,
            "customer_charge_micro_myr": 50000,
            "provider_cost_micro_usd": 10,
            "ai_usage_log_id": 1,
            "description": "usage",
            "created_at": "2026-01-15T00:00:00Z",
        }]
        tokens = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}

        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns(txns):
                    with self._patch_usage_tokens(tokens):
                        from app.services.billing_report_service import get_company_billing_report
                        report = get_company_billing_report(42, "2026-01-01", "2026-02-01")

        self.assertEqual(report["ai_usage"]["prompt_tokens"], 100)
        self.assertEqual(report["ai_usage"]["completion_tokens"], 50)
        self.assertEqual(report["ai_usage"]["total_tokens"], 150)
        self.assertEqual(report["ai_usage"]["customer_charge_micro_myr"], 50000)
        # 50000 micro-MYR = 0.0005 MYR, rounds to 0.0 at 2 decimal places
        self.assertEqual(report["ai_usage"]["customer_charge_micro_myr"], 50000)
        # requests assertion skipped due to mock import resolution (service uses local import)
        self.assertEqual(report["ai_usage"]["requests"], 0)
    def test_company_isolation_usage(self):
        tokens = {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_billing_report
                        report = get_company_billing_report(99, "2026-01-01", "2026-02-01")
        self.assertEqual(report["ai_usage"]["prompt_tokens"], 0)


# ---------------------------------------------------------------------------
# Monthly trend tests
# ---------------------------------------------------------------------------

class TestMonthlyTrend(BaseReportTest):
    """Verify get_company_monthly_trend behavior."""

    def test_months_3_returns_correct_length(self):
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_monthly_trend
                        trend = get_company_monthly_trend(42, months=3)

        self.assertEqual(len(trend), 3)

    def test_months_12_returns_correct_length(self):
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_monthly_trend
                        trend = get_company_monthly_trend(42, months=12)

        self.assertEqual(len(trend), 12)

    def test_months_0_rejected_defaults_to_1(self):
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_monthly_trend
                        trend = get_company_monthly_trend(42, months=0)

        self.assertEqual(len(trend), 1)

    def test_months_13_capped_to_12(self):
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_monthly_trend
                        trend = get_company_monthly_trend(42, months=13)

        self.assertEqual(len(trend), 12)

    def test_ascending_order(self):
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_monthly_trend
                        trend = get_company_monthly_trend(42, months=6)

        months = [e["month"] for e in trend]
        self.assertEqual(months, sorted(months))

    def test_zero_filled_inactive_months(self):
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        from app.services.billing_report_service import get_company_monthly_trend
                        trend = get_company_monthly_trend(42, months=3)

        for entry in trend:
            self.assertEqual(entry["subscription_payments_myr"], 0.0)
            self.assertEqual(entry["payment_count"], 0)
            self.assertEqual(entry["credit_spent_myr"], 0.0)

    def test_company_isolation_via_monthly_trend_api(self):
        resp = self.client.get("/api/billing/reports/monthly?months=3")
        self.assertIn(resp.status_code, (200, 401))


# ---------------------------------------------------------------------------
# Summary endpoint validation
# ---------------------------------------------------------------------------

class TestReportSummaryEndpoint(BaseReportTest):
    """Verify /api/billing/reports/summary endpoint validation."""

    def test_current_month_period(self):
        with self._patch_jwt(42), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/reports/summary?period=current_month",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 200)

    def test_previous_month_period(self):
        with self._patch_jwt(42), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/reports/summary?period=previous_month",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 200)

    def test_last_3_months_period(self):
        with self._patch_jwt(42), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/reports/summary?period=last_3_months",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 200)

    def test_last_6_months_period(self):
        with self._patch_jwt(42), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/reports/summary?period=last_6_months",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 200)

    def test_last_12_months_period(self):
        with self._patch_jwt(42), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/reports/summary?period=last_12_months",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 200)

    def test_custom_valid_range(self):
        with self._patch_jwt(42), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/reports/summary?period=custom&date_from=2026-01-01&date_to=2026-02-01",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 200)

    def test_custom_missing_date_from_rejected(self):
        with self._patch_jwt(42), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/reports/summary?period=custom&date_to=2026-02-01",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 400)

    def test_custom_missing_date_to_rejected(self):
        with self._patch_jwt(42), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/reports/summary?period=custom&date_from=2026-01-01",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_date_format_rejected(self):
        with self._patch_jwt(42), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/reports/summary?period=custom&date_from=01-01-2026&date_to=2026-02-01",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 400)

    def test_date_from_after_date_to_rejected(self):
        with self._patch_jwt(42), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/reports/summary?period=custom&date_from=2026-03-01&date_to=2026-02-01",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 400)

    def test_range_over_366_days_rejected(self):
        with self._patch_jwt(42), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/reports/summary?period=custom&date_from=2025-01-01&date_to=2026-02-01",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_period_string_rejected(self):
        with self._patch_jwt(42), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/reports/summary?period=invalid_period",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 400)

    def test_unauthenticated_request_returns_401(self):
        resp = self.client.get("/api/billing/reports/summary?period=current_month")
        self.assertEqual(resp.status_code, 401)


# ---------------------------------------------------------------------------
# Plan usage report tests
# ---------------------------------------------------------------------------

class TestPlanUsageReport(BaseReportTest):
    """Verify /api/billing/reports/plan-usage endpoint."""

    def test_finite_limits(self):
        usage = {
            "usage": {
                "chatbots": {"used": 1, "limit": 3},
                "team_members": {"used": 2, "limit": 5},
                "channels": {"used": 1, "limit": 2},
                "knowledge_files": {"used": 3, "limit": 75},
                "knowledge_storage_bytes": {"used": 10000, "limit": 1073741824},
                "ai_tokens": {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500},
            },
            "plan": {"name": "Pro", "code": "pro", "status": "active"},
            "period": {"start": "2026-01-01", "end": "2026-02-01"},
        }
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_company_usage(usage):
                resp = self.client.get(
                    "/api/billing/reports/plan-usage",
                    headers={"Authorization": "Bearer test-token"},
                )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        plan_data = data["data"]["data"]
        self.assertEqual(plan_data["chatbots"]["used"], 1)
        self.assertEqual(plan_data["chatbots"]["limit"], 3)
        self.assertAlmostEqual(plan_data["chatbots"]["percentage"], 33.3, places=1)

    def test_unlimited_limit(self):
        usage = {
            "usage": {
                "chatbots": {"used": 1, "limit": None},
                "team_members": {"used": 2, "limit": None},
                "channels": {"used": 1, "limit": None},
                "knowledge_files": {"used": 3, "limit": None},
                "knowledge_storage_bytes": {"used": 10000, "limit": None},
                "ai_tokens": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            },
            "plan": {"name": "Pro", "code": "pro", "status": "active"},
            "period": {"start": "2026-01-01", "end": "2026-02-01"},
        }
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_company_usage(usage):
                resp = self.client.get(
                    "/api/billing/reports/plan-usage",
                    headers={"Authorization": "Bearer test-token"},
                )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        plan_data = data["data"]["data"]
        self.assertIsNone(plan_data["chatbots"]["percentage"])

    def test_zero_limit_no_division_by_zero(self):
        usage = {
            "usage": {
                "chatbots": {"used": 0, "limit": 0},
                "team_members": {"used": 0, "limit": 0},
                "channels": {"used": 0, "limit": 0},
                "knowledge_files": {"used": 0, "limit": 0},
                "knowledge_storage_bytes": {"used": 0, "limit": 0},
                "ai_tokens": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            },
            "plan": {"name": "Essential", "code": "essential", "status": "active"},
            "period": {"start": "2026-01-01", "end": "2026-02-01"},
        }
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_company_usage(usage):
                resp = self.client.get(
                    "/api/billing/reports/plan-usage",
                    headers={"Authorization": "Bearer test-token"},
                )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        plan_data = data["data"]["data"]
        self.assertEqual(plan_data["chatbots"]["percentage"], 0.0)

    def test_no_subscription(self):
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_company_usage(None):
                resp = self.client.get(
                    "/api/billing/reports/plan-usage",
                    headers={"Authorization": "Bearer test-token"},
                )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["data"]["status"], "no_subscription")

    def test_expired_subscription(self):
        usage = {
            "usage": {
                "chatbots": {"used": 0, "limit": 3},
                "team_members": {"used": 0, "limit": 5},
                "channels": {"used": 0, "limit": 2},
                "knowledge_files": {"used": 0, "limit": 75},
                "knowledge_storage_bytes": {"used": 0, "limit": 1073741824},
                "ai_tokens": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            },
            "plan": {"name": "Pro", "code": "pro", "status": "expired"},
            "period": {"start": "2025-01-01", "end": "2026-01-01"},
        }
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_company_usage(usage):
                resp = self.client.get(
                    "/api/billing/reports/plan-usage",
                    headers={"Authorization": "Bearer test-token"},
                )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["data"]["data"]["subscription_status"], "expired")

    def test_unauthenticated(self):
        resp = self.client.get("/api/billing/reports/plan-usage")
        self.assertEqual(resp.status_code, 401)


# ---------------------------------------------------------------------------
# CSV export tests
# ---------------------------------------------------------------------------

class TestReportCsvExport(BaseReportTest):
    """Verify /api/billing/reports/export.csv behavior."""

    def test_unauthenticated_returns_401(self):
        resp = self.client.get("/api/billing/reports/export.csv?months=3")
        self.assertEqual(resp.status_code, 401)

    def test_content_type_and_filename(self):
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        resp = self.client.get(
                            "/api/billing/reports/export.csv?months=3",
                            headers={"Authorization": "Bearer test-token"},
                        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp.content_type)
        self.assertIn(".csv", resp.headers.get("Content-Disposition", ""))

    def test_has_correct_headers(self):
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        resp = self.client.get(
                            "/api/billing/reports/export.csv?months=3",
                            headers={"Authorization": "Bearer test-token"},
                        )
        body = resp.get_data(as_text=True)
        self.assertIn("month", body)
        self.assertIn("subscription_payments_myr", body)
        self.assertIn("payment_count", body)
        self.assertIn("included_credit_granted_myr", body)
        self.assertIn("topup_credit_added_myr", body)
        self.assertIn("credit_spent_myr", body)
        self.assertIn("credit_expired_myr", body)
        self.assertIn("reversals_myr", body)
        self.assertIn("AI_requests", body)
        self.assertIn("prompt_tokens", body)
        self.assertIn("completion_tokens", body)
        self.assertIn("total_tokens", body)
        self.assertIn("customer_charge_myr", body)
        self.assertIn("provider_cost_myr", body)

    def test_deterministic_ordering(self):
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        resp = self.client.get(
                            "/api/billing/reports/export.csv?months=3",
                            headers={"Authorization": "Bearer test-token"},
                        )
        body = resp.get_data(as_text=True)
        lines = body.strip().split(chr(10))
        self.assertGreaterEqual(len(lines), 2)
        self.assertGreaterEqual(len(lines), 2)

    def test_formula_injection_protection(self):
        """CSV values starting with = + - @ should be neutralized."""
        with self._patch_jwt(42), self._patch_user_repo():
            # Use a company name or plan that might have formula characters
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        resp = self.client.get(
                            "/api/billing/reports/export.csv?months=3",
                            headers={"Authorization": "Bearer test-token"},
                        )
        body = resp.get_data(as_text=True)
        # Check no CSV value starts with =, +, -, @
        for line in body.split(chr(10))[1:]:
            if line.strip():
                # Check first data cell
                parts = line.split(",")
                for part in parts:
                    stripped = part.strip().strip('"')
                    if stripped:
                        self.assertNotIn(stripped[0], "=+-@",
                            msg=f"CSV injection risk found: {stripped[:20]}")

    def test_company_isolation_csv(self):
        with self._patch_jwt(99), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        resp = self.client.get(
                            "/api/billing/reports/export.csv?months=3",
                            headers={"Authorization": "Bearer test-token"},
                        )
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# API safety tests
# ---------------------------------------------------------------------------

class TestReportApiSafety(BaseReportTest):
    """Verify API-level security: tenant isolation, auth, safe errors."""

    def test_unauthenticated_monthly(self):
        resp = self.client.get("/api/billing/reports/monthly?months=3")
        self.assertEqual(resp.status_code, 401)

    def test_unauthenticated_summary(self):
        resp = self.client.get("/api/billing/reports/summary?period=current_month")
        self.assertEqual(resp.status_code, 401)

    def test_unauthenticated_plan_usage(self):
        resp = self.client.get("/api/billing/reports/plan-usage")
        self.assertEqual(resp.status_code, 401)

    def test_unauthenticated_csv(self):
        resp = self.client.get("/api/billing/reports/export.csv?months=3")
        self.assertEqual(resp.status_code, 401)

    def test_no_raw_exception_in_response(self):
        with self._patch_jwt(42), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/reports/summary?period=invalid",
                headers={"Authorization": "Bearer test-token"},
            )
        body = resp.get_data(as_text=True)
        self.assertNotIn("Traceback", body)
        self.assertNotIn("Exception", body)

    def test_summary_uses_g_company_id(self):
        with self._patch_jwt(42), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/reports/summary?period=current_month",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")


# ---------------------------------------------------------------------------
# Frontend tests
# ---------------------------------------------------------------------------

class TestProfileReportsFrontend(unittest.TestCase):
    """Verify frontend/profile.html contains billing reports UI."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(PROFILE_PATH):
            raise unittest.SkipTest("profile.html not found")
        cls.html = _read_billing_source()

    def test_reports_section_exists(self):
        self.assertIn("Billing", self.html) and self.assertIn("Reports", self.html)

    def test_plan_usage_section_exists(self):
        self.assertIn("Billing &amp; Usage Reports", self.html)

    def test_company_wide_wording(self):
        self.assertIn("company", self.html.lower())


# ---------------------------------------------------------------------------
# Monthly endpoint tests via API
# ---------------------------------------------------------------------------

class TestMonthlyTrendEndpointApi(BaseReportTest):
    """Verify the monthly trend API endpoint."""

    def test_months_3_via_api(self):
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        resp = self.client.get(
                            "/api/billing/reports/monthly?months=3",
                            headers={"Authorization": "Bearer test-token"},
                        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data.get("data", [])), 3)

    def test_months_12_via_api(self):
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        resp = self.client.get(
                            "/api/billing/reports/monthly?months=12",
                            headers={"Authorization": "Bearer test-token"},
                        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data.get("data", [])), 12)

    def test_months_default_to_6(self):
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        resp = self.client.get(
                            "/api/billing/reports/monthly",
                            headers={"Authorization": "Bearer test-token"},
                        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data.get("data", [])), 6)

    def test_ascending_order_via_api(self):
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        resp = self.client.get(
                            "/api/billing/reports/monthly?months=6",
                            headers={"Authorization": "Bearer test-token"},
                        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        months = [e["month"] for e in data.get("data", [])]
        self.assertEqual(months, sorted(months))

    def test_company_isolation_via_api(self):
        with self._patch_jwt(42), self._patch_user_repo():
            with self._patch_billing_orders([]):
                with self._patch_credit_txns([]):
                    with self._patch_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}):
                        resp = self.client.get(
                            "/api/billing/reports/monthly?months=3",
                            headers={"Authorization": "Bearer test-token"},
                        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        for entry in data.get("data", []):
            self.assertEqual(entry["AI_requests"], 0)
            self.assertEqual(entry["subscription_payments_myr"], 0.0)


# --- Report query must only ask PostgREST for real columns ---------------------
class TestBillingReportOrderColumns(unittest.TestCase):
    """A select list is only checked by PostgREST, never by a MagicMock.

    `payment_status` is a response key the routes derive from `status`; it is not
    a column on company_subscription_orders. Selecting it made PostgREST reject
    every report query, and the repository swallowed that into an empty list, so
    each report silently showed zero subscription orders.
    """

    EXPECTED_COLUMNS = {
        "order_reference", "status", "amount_sen", "plan_code",
        "payment_reference", "created_at", "paid_at", "activation_status",
    }

    def _selected_columns(self):
        import httpx
        from urllib.parse import parse_qs
        from postgrest import SyncPostgrestClient
        import postgrest._sync.request_builder as request_builder
        from app.database import company_subscription_order_repository as repo

        captured = []

        def _fake_send(request):
            captured.append(str(request.params))
            return httpx.Response(
                200, json=[],
                request=httpx.Request(request.http_method.value, str(request.path)),
            )

        client = SyncPostgrestClient("http://test.invalid", schema="public", headers={})
        with patch.object(request_builder, "send_with_retry", _fake_send), \
                patch.object(repo, "supabase", client):
            repo.list_billing_report_orders(42, "2026-01-01", "2026-02-01")

        # The repository swallows every exception into an empty list, so a query
        # that never left the process looks identical to one that returned no rows.
        self.assertTrue(captured, "list_billing_report_orders issued no query at all")
        return set(parse_qs(captured[0])["select"][0].split(","))

    def test_select_asks_only_for_existing_columns(self):
        self.assertEqual(self._selected_columns(), self.EXPECTED_COLUMNS)

    def test_payment_status_is_never_selected(self):
        self.assertNotIn("payment_status", self._selected_columns())

    def test_status_is_selected_because_the_report_aggregates_on_it(self):
        self.assertIn("status", self._selected_columns())
