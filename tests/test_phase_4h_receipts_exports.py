"""Tests for Phase 4H — printable receipts, CSV exports, and usage summary."""
import os
import json
from unittest.mock import patch, MagicMock

from tests.test_phase_4f_tenant_isolation import (

    TestBillingTenantIsolation as BaseTest,
)


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
# ------------------------------------------------------------------------------


class BasePhase4HTest(BaseTest):
    """Base with role-aware _patch_jwt."""

    def _patch_jwt(self, company_id=42, role="admin"):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": company_id, "user_id": 1, "role": role},
        )


class TestPrintableReceipt(BasePhase4HTest):
    """Test the printable HTML receipt endpoint."""

    MOCK_ORDER = {
        "order_reference": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "company_id": 42,
        "new_plan_id": 3,
        "amount_sen": 3900,
        "status": "paid",
        "activation_status": "completed",
        "payment_reference": "txn-abc",
        "gateway_order_id": "bill-xyz",
        "paid_at": "2026-07-08T12:00:00Z",
        "created_at": "2026-07-08T11:00:00Z",
        "credited_at": "2026-07-08T12:01:00Z",
        "source_period_start": "2026-07-08T00:00:00Z",
        "source_period_end": "2026-08-07T23:59:59Z",
    }

    MOCK_PLAN = {"id": 3, "code": "pro", "name": "Pro"}

    def test_printable_receipt_requires_auth(self):
        """Unauthenticated requests are rejected."""
        resp = self.client.get("/api/billing/subscription/orders/abc-123/receipt/print")
        self.assertEqual(resp.status_code, 401)

    def test_printable_receipt_returns_html(self):
        """Receipt returns HTML content."""
        with self._patch_jwt(company_id=42), self._patch_user_repo():
            with patch(
                "app.services.billing_receipt_service.get_subscription_order_by_reference_and_company",
                return_value=self.MOCK_ORDER,
            ), patch(
                "app.services.billing_receipt_service.get_plan_by_id",
                return_value=self.MOCK_PLAN,
            ):
                resp = self.client.get(
                    "/api/billing/subscription/orders/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/receipt/print",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 200)
                self.assertIn("text/html", resp.content_type)

    def test_printable_receipt_has_required_content(self):
        """Receipt contains required fields."""
        with self._patch_jwt(company_id=42), self._patch_user_repo():
            with patch(
                "app.services.billing_receipt_service.get_subscription_order_by_reference_and_company",
                return_value=self.MOCK_ORDER,
            ), patch(
                "app.services.billing_receipt_service.get_plan_by_id",
                return_value=self.MOCK_PLAN,
            ):
                resp = self.client.get(
                    "/api/billing/subscription/orders/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/receipt/print",
                    headers={"Authorization": "Bearer test-token"},
                )
                body = resp.get_data(as_text=True)
                self.assertIn("Payment Receipt", body)
                self.assertIn("This is a payment receipt, not a tax invoice.", body)
                self.assertIn("Pro", body)
                self.assertIn("MYR 39.00", body)
                self.assertIn("Print / Save PDF", body)
                self.assertIn("@media print", body)

    def test_printable_receipt_other_company_denied(self):
        """Other company cannot access receipt."""
        with self._patch_jwt(company_id=99), self._patch_user_repo():
            with patch(
                "app.services.billing_receipt_service.get_subscription_order_by_reference_and_company",
                return_value=None,
            ):
                resp = self.client.get(
                    "/api/billing/subscription/orders/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/receipt/print",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 404)

    def test_printable_receipt_not_tax_invoice(self):
        """Receipt contains the not-a-tax-invoice notice."""
        with self._patch_jwt(company_id=42), self._patch_user_repo():
            with patch(
                "app.services.billing_receipt_service.get_subscription_order_by_reference_and_company",
                return_value=self.MOCK_ORDER,
            ), patch(
                "app.services.billing_receipt_service.get_plan_by_id",
                return_value=self.MOCK_PLAN,
            ):
                resp = self.client.get(
                    "/api/billing/subscription/orders/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/receipt/print",
                    headers={"Authorization": "Bearer test-token"},
                )
                body = resp.get_data(as_text=True)
                self.assertIn("Payment Receipt", body)
                self.assertNotIn("Tax Invoice", body)
                self.assertNotIn("SST Invoice", body)


class TestBillingCsvExport(BasePhase4HTest):
    """Test the billing history CSV export."""

    MOCK_ORDERS = [
        {
            "plan": {"id": 3, "code": "pro", "name": "Pro"},
            "created_at": "2026-07-08T11:00:00Z",
            "paid_at": "2026-07-08T12:00:00Z",
            "amount_sen": 3900,
            "status": "paid",
            "activation_status": "completed",
            "order_reference": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "payment_reference": "txn-abc",
            "gateway_order_id": "bill-xyz",
        },
        {
            "plan": None,
            "created_at": "2026-06-01T00:00:00Z",
            "paid_at": None,
            "amount_sen": 1900,
            "status": "paid",
            "activation_status": "completed",
            "order_reference": "ffffffff-gggg-hhhh-iiii-jjjjjjjjjjjj",
            "payment_reference": "txn-def",
            "gateway_order_id": "bill-uvw",
        },
    ]

    def test_csv_requires_auth(self):
        """Unauthenticated requests are rejected."""
        resp = self.client.get("/api/billing/subscription/orders/export.csv")
        self.assertEqual(resp.status_code, 401)

    def test_csv_returns_csv_content(self):
        """CSV export returns CSV."""
        with self._patch_jwt(company_id=42), self._patch_user_repo():
            with patch(
                "app.database.company_subscription_order_repository.list_subscription_orders_for_company",
                return_value=self.MOCK_ORDERS,
            ):
                resp = self.client.get(
                    "/api/billing/subscription/orders/export.csv",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 200)
                self.assertIn("text/csv", resp.content_type)
                body = resp.get_data(as_text=True)
                self.assertIn("order_reference", body)

    def test_csv_has_correct_headers(self):
        """CSV has expected headers."""
        with self._patch_jwt(company_id=42), self._patch_user_repo():
            with patch(
                "app.database.company_subscription_order_repository.list_subscription_orders_for_company",
                return_value=[],
            ):
                resp = self.client.get(
                    "/api/billing/subscription/orders/export.csv",
                    headers={"Authorization": "Bearer test-token"},
                )
                body = resp.get_data(as_text=True)
                self.assertIn("order_date", body)
                self.assertIn("amount_myr", body)

    def test_csv_injection_mitigated(self):
        """CSV injection characters are neutralized."""
        dangerous_orders = [
            {
                "plan": {"name": "=SUM(A1:A10)"},
                "created_at": "+2026-07-08",
                "paid_at": "-2026-07-08",
                "amount_sen": 3900,
                "status": "=cmd",
                "activation_status": "@test",
                "order_reference": "-order",
                "payment_reference": "=danger",
                "gateway_order_id": "+cmd",
            },
        ]
        with self._patch_jwt(company_id=42), self._patch_user_repo():
            with patch(
                "app.database.company_subscription_order_repository.list_subscription_orders_for_company",
                return_value=dangerous_orders,
            ):
                resp = self.client.get(
                    "/api/billing/subscription/orders/export.csv",
                    headers={"Authorization": "Bearer test-token"},
                )
                body = resp.get_data(as_text=True)
                self.assertIn(chr(39) + chr(61) + 'SUM', body)
                self.assertIn(chr(39) + chr(61) + 'cmd', body)
                self.assertIn(chr(39) + chr(61) + 'danger', body)


class TestAiCreditCsvExport(BasePhase4HTest):
    """Test the AI-credit activity CSV export."""

    MOCK_TXNS = [
        {
            "created_at": "2026-07-09T09:20:00Z",
            "transaction_type": "subscription_included",
            "included_delta_micro_myr": 60000000,
            "topup_delta_micro_myr": 0,
            "included_balance_after_micro_myr": 60000000,
            "topup_balance_after_micro_myr": 2000000,
            "description": "Included credit granted",
            "payment_reference": "txn-1",
            "ai_usage_type": "knowledge_extraction",
            "model": "openai/gpt-4.1",
            "provider": "openrouter",
            "prompt_tokens": 120,
            "completion_tokens": 30,
            "total_tokens": 150,
            "customer_charge_micro_myr": 25000,
        },
    ]

    def test_credit_csv_requires_auth(self):
        """Unauthenticated requests are rejected."""
        resp = self.client.get("/api/billing/ai-credit/transactions/export.csv")
        self.assertEqual(resp.status_code, 401)

    def test_credit_csv_returns_csv(self):
        """Credit CSV returns CSV content."""
        with self._patch_jwt(company_id=42), self._patch_user_repo():
            with patch(
                "app.routes.billing_routes.list_credit_transactions",
                return_value=self.MOCK_TXNS,
            ):
                resp = self.client.get(
                    "/api/billing/ai-credit/transactions/export.csv",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 200)
                self.assertIn("text/csv", resp.content_type)

    def test_credit_csv_has_bucket_deltas(self):
        """CSV contains included and top-up delta columns."""
        with self._patch_jwt(company_id=42), self._patch_user_repo():
            with patch(
                "app.routes.billing_routes.list_credit_transactions",
                return_value=self.MOCK_TXNS,
            ):
                resp = self.client.get(
                    "/api/billing/ai-credit/transactions/export.csv",
                    headers={"Authorization": "Bearer test-token"},
                )
                body = resp.get_data(as_text=True)
                self.assertIn("included_delta_myr", body)
                self.assertIn("topup_delta_myr", body)
                self.assertIn("total_delta_myr", body)
                self.assertIn("60.00", body)
                self.assertIn("2.00", body)

    def test_credit_csv_includes_usage_metadata_when_available(self):
        """CSV includes persisted model/provider/token metadata."""
        with self._patch_jwt(company_id=42), self._patch_user_repo():
            with patch(
                "app.routes.billing_routes.list_credit_transactions",
                return_value=self.MOCK_TXNS,
            ):
                resp = self.client.get(
                    "/api/billing/ai-credit/transactions/export.csv",
                    headers={"Authorization": "Bearer test-token"},
                )
                body = resp.get_data(as_text=True)
                self.assertIn("model", body)
                self.assertIn("provider", body)
                self.assertIn("input_tokens", body)
                self.assertIn("openai/gpt-4.1", body)
                self.assertIn("openrouter", body)
                self.assertIn("120", body)

    def test_credit_csv_no_idempotency_keys(self):
        """Customer CSV does not expose idempotency keys."""
        with self._patch_jwt(company_id=42), self._patch_user_repo():
            with patch(
                "app.routes.billing_routes.list_credit_transactions",
                return_value=self.MOCK_TXNS,
            ):
                resp = self.client.get(
                    "/api/billing/ai-credit/transactions/export.csv",
                    headers={"Authorization": "Bearer test-token"},
                )
                body = resp.get_data(as_text=True)
                self.assertNotIn("idempotency", body.lower())


class TestAiCreditUsageSummary(BasePhase4HTest):
    """Test the AI-credit usage summary API."""

    MOCK_BALANCE = {
        "period_start": "2026-07-01T00:00:00Z",
        "period_end": "2026-07-31T23:59:59Z",
        "included_balance_micro_myr": 60000000,
        "topup_balance_micro_myr": 2000000,
    }

    MOCK_TXNS = [
        {"transaction_type": "subscription_included", "included_delta_micro_myr": 60000000, "topup_delta_micro_myr": 0},
        {"transaction_type": "topup", "included_delta_micro_myr": 0, "topup_delta_micro_myr": 2000000},
        {"transaction_type": "usage", "included_delta_micro_myr": -50000, "topup_delta_micro_myr": 0},
        {"transaction_type": "expiry", "included_delta_micro_myr": -450000, "topup_delta_micro_myr": 0},
    ]

    def test_summary_requires_auth(self):
        """Unauthenticated requests are rejected."""
        resp = self.client.get("/api/billing/ai-credit/usage-summary")
        self.assertEqual(resp.status_code, 401)

    def test_summary_returns_structure(self):
        """Usage summary returns expected structure."""
        with self._patch_jwt(company_id=42), self._patch_user_repo():
            with patch(
                "app.database.ai_credit_repository.get_company_credit_balance",
                return_value=self.MOCK_BALANCE,
            ), patch(
                "app.routes.billing_routes.list_credit_transactions",
                return_value=self.MOCK_TXNS,
            ):
                resp = self.client.get(
                    "/api/billing/ai-credit/usage-summary",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 200)
                data = resp.get_json()
                self.assertEqual(data["status"], "success")

    def test_summary_calculations(self):
        """Usage summary has correct calculations."""
        with self._patch_jwt(company_id=42), self._patch_user_repo():
            with patch(
                "app.database.ai_credit_repository.get_company_credit_balance",
                return_value=self.MOCK_BALANCE,
            ), patch(
                "app.routes.billing_routes.list_credit_transactions",
                return_value=self.MOCK_TXNS,
            ):
                resp = self.client.get(
                    "/api/billing/ai-credit/usage-summary",
                    headers={"Authorization": "Bearer test-token"},
                )
                data = resp.get_json()["data"]
                self.assertEqual(data["balances"]["included_myr"], "60.00")
                self.assertEqual(data["balances"]["topup_myr"], "2.00")
                self.assertEqual(data["balances"]["total_myr"], "62.00")
                self.assertEqual(data["activity"]["included_granted_myr"], "60.00")
                self.assertEqual(data["activity"]["topup_added_myr"], "2.00")
                self.assertEqual(data["activity"]["usage_spent_myr"], "0.05")
                self.assertEqual(data["activity"]["included_expired_myr"], "0.45")

    def test_summary_counts_usage_debit_transactions(self):
        """Usage summary counts the transaction type written by the charge RPC."""
        txns = [
            {"transaction_type": "usage_debit", "included_delta_micro_myr": -25000, "topup_delta_micro_myr": -5000},
        ]
        with self._patch_jwt(company_id=42), self._patch_user_repo():
            with patch(
                "app.database.ai_credit_repository.get_company_credit_balance",
                return_value=self.MOCK_BALANCE,
            ), patch(
                "app.routes.billing_routes.list_credit_transactions",
                return_value=txns,
            ):
                resp = self.client.get(
                    "/api/billing/ai-credit/usage-summary",
                    headers={"Authorization": "Bearer test-token"},
                )
                data = resp.get_json()["data"]
                self.assertEqual(data["activity"]["usage_spent_myr"], "0.03")

    def test_summary_empty_balance(self):
        """Empty balance returns zero summary."""
        with self._patch_jwt(company_id=42), self._patch_user_repo():
            with patch(
                "app.database.ai_credit_repository.get_company_credit_balance",
                return_value=None,
            ):
                resp = self.client.get(
                    "/api/billing/ai-credit/usage-summary",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 200)
                data = resp.get_json()["data"]
                self.assertEqual(data["balances"]["total_myr"], 0)
                self.assertEqual(data["transaction_count"], 0)


class TestProfileFrontendPhase4H(BasePhase4HTest):
    """Static analysis of profile.html for Phase 4H features."""

    @classmethod
    def setUpClass(cls):
        cls.html = _read_billing_source()

    def test_print_receipt_endpoint_wired(self):
        """Profile HTML contains the print receipt endpoint."""
        self.assertIn('receipt', self.html)

    def test_billing_csv_export_function_exists(self):
        """Profile HTML contains billing CSV export function."""
        self.assertIn("exportOrders", self.html)

    def test_credit_csv_export_function_exists(self):
        """Profile HTML contains AI-credit CSV export function."""
        self.assertIn("exportTransactions", self.html)

    def test_usage_summary_cards_exist(self):
        """Profile HTML contains usage summary card containers."""
        self.assertIn("acu-granted", self.html)
        self.assertIn("acu-spent", self.html)
        self.assertIn("acu-expired", self.html)

    def test_summary_fetch_function_exists(self):
        """Profile HTML contains usage summary fetch function."""
        self.assertIn("fetchAiCreditUsageSummary", self.html)

    def test_company_wide_wording_remains(self):
        """Company-wide billing explanation still present."""
        self.assertIn("apply to all chatbots in this company", self.html)

    def test_no_raw_json_display(self):
        """No raw backend JSON endpoints called directly from buttons."""
        self.assertNotIn('/api/billing/subscription/orders/rawraw', self.html)




