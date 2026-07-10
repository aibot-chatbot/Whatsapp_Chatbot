"""Tests for Phase 4G admin billing support endpoints."""
from unittest.mock import patch

from tests.test_phase_4f_tenant_isolation import (
    TestBillingTenantIsolation as BaseAuthTest,
)


class BaseAdminTest(BaseAuthTest):
    """Base for admin test classes with role-aware _patch_jwt."""

    def _patch_jwt(self, company_id=42, role="admin"):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": company_id, "user_id": 1, "role": role},
        )


class TestAdminAuthorization(BaseAdminTest):
    """Test admin billing endpoint authorization."""

    def test_admin_owner_can_list_orders(self):
        """Company admin/owner can list own orders."""
        with self._patch_jwt(company_id=42, role="admin"), self._patch_user_repo():
            with patch(
                "app.routes.admin_billing_routes.list_subscription_orders_for_company",
                return_value=[],
            ):
                resp = self.client.get(
                    "/api/admin/billing/orders",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 200)

    def test_member_cannot_list_orders(self):
        """Company member cannot access admin billing."""
        with self._patch_jwt(company_id=42, role="member"), self._patch_user_repo():
            resp = self.client.get(
                "/api/admin/billing/orders",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_cannot_list_orders(self):
        """Unauthenticated requests are rejected."""
        resp = self.client.get("/api/admin/billing/orders")
        self.assertEqual(resp.status_code, 401)

    def test_admin_owner_can_get_order_detail(self):
        """Company admin/owner can view own order detail."""
        mock_order = {
            "order_reference": "abc-123",
            "company_id": 42,
            "new_plan_id": 3,
            "amount_sen": 3900,
            "status": "paid",
            "activation_status": "not_started",
            "created_at": "2026-07-01T00:00:00Z",
        }
        with self._patch_jwt(company_id=42, role="admin"), self._patch_user_repo():
            with patch(
                "app.routes.admin_billing_routes.get_subscription_order_by_reference_and_company",
                return_value=mock_order,
            ):
                resp = self.client.get(
                    "/api/admin/billing/orders/abc-123",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 200)
                data = resp.get_json()
                self.assertEqual(data["data"]["order_reference"], "abc-123")
                self.assertEqual(data["data"]["company_id"], 42)

    def test_order_not_found_returns_404(self):
        """Non-existent order returns 404."""
        with self._patch_jwt(company_id=42, role="admin"), self._patch_user_repo():
            with patch(
                "app.routes.admin_billing_routes.get_subscription_order_by_reference_and_company",
                return_value=None,
            ):
                resp = self.client.get(
                    "/api/admin/billing/orders/nonexistent",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 404)

    def test_member_cannot_get_order_detail(self):
        """Member cannot get order detail."""
        with self._patch_jwt(company_id=42, role="member"), self._patch_user_repo():
            resp = self.client.get(
                "/api/admin/billing/orders/abc-123",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 403)

    def test_admin_owner_can_reconcile_order(self):
        """Company admin/owner can reconcile own order."""
        with self._patch_jwt(company_id=42, role="admin"), self._patch_user_repo():
            with patch(
                "app.routes.admin_billing_routes.reconcile_subscription_order",
                return_value={
                    "outcome": "reconciled_and_completed",
                    "order_status": "credited",
                    "message": "Reconciliation completed.",
                },
            ):
                resp = self.client.post(
                    "/api/admin/billing/orders/abc-123/reconcile",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 200)
                data = resp.get_json()
                self.assertEqual(data["data"]["outcome"], "reconciled_and_completed")

    def test_manual_review_returns_409(self):
        """Manual review required returns 409."""
        with self._patch_jwt(company_id=42, role="admin"), self._patch_user_repo():
            with patch(
                "app.routes.admin_billing_routes.reconcile_subscription_order",
                return_value={
                    "outcome": "manual_review_required",
                    "order_status": "paid",
                    "message": "This payment requires support review.",
                },
            ):
                resp = self.client.post(
                    "/api/admin/billing/orders/abc-123/reconcile",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 409)

    def test_member_cannot_reconcile(self):
        """Company member cannot trigger reconciliation."""
        with self._patch_jwt(company_id=42, role="member"), self._patch_user_repo():
            resp = self.client.post(
                "/api/admin/billing/orders/abc-123/reconcile",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 403)


class TestAdminAICredit(BaseAdminTest):
    """Test admin AI-credit inspection endpoints."""

    def test_admin_owner_can_view_credit_summary(self):
        """Company admin/owner can view credit summary."""
        mock_balance = {
            "included_balance_micro_myr": 60000000,
            "topup_balance_micro_myr": 2000000,
            "total_balance_micro_myr": 62000000,
            "period_start": "2026-07-01T00:00:00Z",
            "period_end": "2026-07-31T00:00:00Z",
        }
        with self._patch_jwt(company_id=42, role="admin"), self._patch_user_repo():
            with patch(
                "app.routes.admin_billing_routes.get_company_credit_balance",
                return_value=mock_balance,
            ):
                resp = self.client.get(
                    "/api/admin/billing/ai-credit",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 200)
                data = resp.get_json()
                self.assertEqual(data["data"]["included_balance_micro_myr"], 60000000)
                self.assertEqual(data["data"]["topup_balance_micro_myr"], 2000000)

    def test_credit_member_cannot_view_summary(self):
        """Company member cannot view AI credit summary."""
        with self._patch_jwt(company_id=42, role="member"), self._patch_user_repo():
            resp = self.client.get(
                "/api/admin/billing/ai-credit",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 403)

    def test_admin_owner_can_view_transactions(self):
        """Company admin/owner can view credit transactions."""
        mock_txns = [
            {
                "id": 1,
                "transaction_type": "subscription_included",
                "description": "Subscription included credit",
                "net_delta_micro_myr": 60000000,
                "included_balance_after_micro_myr": 60000000,
                "topup_balance_after_micro_myr": 2000000,
                "idempotency_key": "key-1",
                "payment_reference": "txn-1",
                "created_at": "2026-07-09T09:20:00Z",
            },
        ]
        with self._patch_jwt(company_id=42, role="admin"), self._patch_user_repo():
            with patch(
                "app.routes.admin_billing_routes.list_company_credit_transactions",
                return_value=mock_txns,
            ):
                resp = self.client.get(
                    "/api/admin/billing/ai-credit/transactions",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 200)
                data = resp.get_json()
                self.assertEqual(len(data["data"]["transactions"]), 1)

    def test_credit_not_found_returns_404(self):
        """Missing credit balance returns 404."""
        with self._patch_jwt(company_id=42, role="admin"), self._patch_user_repo():
            with patch(
                "app.routes.admin_billing_routes.get_company_credit_balance",
                return_value=None,
            ):
                resp = self.client.get(
                    "/api/admin/billing/ai-credit",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 404)


class TestSupportRepositoryFunctions(BaseAdminTest):
    """Test the support repository functions."""

    def test_find_order_by_reference(self):
        """Finding an order by reference returns it."""
        from app.database.company_subscription_order_repository import (
            find_subscription_order_for_support,
        )
        mock_rows = type("Mock", (), {"data": [{"order_reference": "abc-123", "company_id": 42}]})()

        with patch(
            "app.database.company_subscription_order_repository.supabase.table",
        ) as mock_table:
            mock_query = mock_table.return_value
            mock_query.select.return_value = mock_query
            mock_query.eq.return_value = mock_query
            mock_query.limit.return_value = mock_query
            mock_query.execute.return_value = mock_rows

            result = find_subscription_order_for_support(order_reference="abc-123")
            self.assertIsNotNone(result)
            self.assertEqual(result["order_reference"], "abc-123")

    def test_find_order_no_params_raises(self):
        """No search parameters raises ValueError."""
        from app.database.company_subscription_order_repository import (
            find_subscription_order_for_support,
        )
        with self.assertRaises(ValueError):
            find_subscription_order_for_support()
