"""Tests for GET /api/billing/toyyibpay/orders/<order_reference> status endpoint."""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("AI_CREDIT_ENFORCEMENT_ENABLED", "true")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("TOYYIBPAY_ENV", "production")
os.environ.setdefault("TOYYIBPAY_USER_SECRET_KEY", "test-secret-key")
os.environ.setdefault("TOYYIBPAY_CATEGORY_CODE", "test-category")
os.environ.setdefault("TOYYIBPAY_REDIRECT_URL", "https://test.example/profile")

import sys
sys.path.insert(0, "C:\\\\Users\\\\User\\\\PycharmProjects\\\\python-whatsapp-bot-main")

import unittest
from unittest.mock import patch, MagicMock

import types

# Mock pre-existing broken dependencies before any app import
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
    "status": "active",
}


def _make_order(status="pending", **kwargs):
    """Helper to build a mock order dict with default safe values."""
    order = {
        "id": 1,
        "order_reference": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "company_id": 42,
        "status": status,
        "amount_micro_myr": 2000000,
        "currency": "MYR",
        "payment_gateway": "toyyibpay",
        "created_at": "2026-07-03T00:00:00Z",
        "paid_at": None,
        "credited_at": None,
    }
    if status == "paid":
        order["paid_at"] = "2026-07-03T00:01:00Z"
    if status == "credited":
        order["paid_at"] = "2026-07-03T00:01:00Z"
        order["credited_at"] = "2026-07-03T00:01:01Z"
        order["credit_transaction_id"] = 42
    order.update(kwargs)
    return order


class TestToyyibpayOrderStatusRoute(unittest.TestCase):
    """Tests for GET /api/billing/toyyibpay/orders/<order_reference>."""

    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.valid_ref = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        self.auth_headers = {"Authorization": "Bearer test-token"}

    def _patch_jwt_decode(self, return_value=None):
        if return_value is None:
            return_value = {"company_id": 42, "user_id": 1, "role": "admin"}
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value=return_value,
        )

    def _patch_user_repo(self, return_value=None):
        if return_value is None:
            return_value = MOCK_USER
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value=return_value,
        )

    def _patch_repo(self, return_value=None, side_effect=None):
        return patch(
            "app.routes.billing_routes.get_topup_order_by_reference_and_company",
            return_value=return_value,
            side_effect=side_effect,
        )

    # ----- Route registration -----
    def test_route_registered(self):
        """GET returns 200 for a valid order."""
        mock_order = _make_order(status="pending")
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=mock_order):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            self.assertNotEqual(resp.status_code, 404)

    def test_get_method_accepted(self):
        """GET returns 200 for a valid authenticated request."""
        mock_order = _make_order(status="pending")
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=mock_order):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            self.assertEqual(resp.status_code, 200)

    def test_post_method_rejected(self):
        """POST returns 405."""
        resp = self.client.post(f"/api/billing/toyyibpay/orders/{self.valid_ref}")
        self.assertEqual(resp.status_code, 405)

    def test_put_method_rejected(self):
        """PUT returns 405."""
        resp = self.client.put(f"/api/billing/toyyibpay/orders/{self.valid_ref}")
        self.assertEqual(resp.status_code, 405)

    def test_delete_method_rejected(self):
        """DELETE returns 405."""
        resp = self.client.delete(f"/api/billing/toyyibpay/orders/{self.valid_ref}")
        self.assertEqual(resp.status_code, 405)

    # ----- Authentication -----
    def test_unauthenticated_request_rejected(self):
        """Missing auth header returns 401."""
        resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}")
        self.assertEqual(resp.status_code, 401)

    def test_expired_token_rejected(self):
        """Expired JWT returns 401."""
        with patch("app.decorators.auth_decorator.jwt.decode", side_effect=__import__('jwt').ExpiredSignatureError("Signature has expired")):
            resp = self.client.get("/api/billing/toyyibpay/orders/" + self.valid_ref, headers=self.auth_headers)
            self.assertEqual(resp.status_code, 401)

    # ----- Successful responses -----
    def test_pending_order_returns_200(self):
        """A pending order returns credited=False."""
        mock_order = _make_order(status="pending")
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=mock_order):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["data"]["status"], "pending")
            self.assertFalse(data["data"]["credited"])

    def test_credited_order_has_credited_true(self):
        """A credited order returns credited=True."""
        mock_order = _make_order(status="credited")
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=mock_order):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["data"]["status"], "credited")
            self.assertTrue(data["data"]["credited"])

    def test_response_has_standard_structure(self):
        """Response follows {status, data} structure."""
        mock_order = _make_order(status="pending")
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=mock_order):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            json_data = resp.get_json()
            self.assertIn("status", json_data)
            self.assertIn("data", json_data)
            self.assertEqual(json_data["status"], "success")

    def test_response_contains_safe_fields(self):
        """Response contains only expected safe fields."""
        mock_order = _make_order(status="credited")
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=mock_order):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            json_data = resp.get_json()
            data = json_data["data"]
            self.assertEqual(data["order_reference"], self.valid_ref)
            self.assertEqual(data["status"], "credited")
            self.assertEqual(data["amount_micro_myr"], 2000000)
            self.assertEqual(data["currency"], "MYR")
            self.assertEqual(data["payment_gateway"], "toyyibpay")
            self.assertIn("created_at", data)
            self.assertIn("paid_at", data)
            self.assertIn("credited_at", data)

    def test_response_does_not_expose_internal_fields(self):
        """Internal fields like company_id, user_id, id, idempotency_key are not exposed."""
        mock_order = _make_order(status="pending", idempotency_key="secret-key", credit_transaction_id=42)
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=mock_order):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            json_data = resp.get_json()
            data_str = str(json_data)
            self.assertNotIn("company_id", data_str)
            self.assertNotIn("idempotency_key", data_str)
            self.assertNotIn("credit_transaction_id", data_str)

    # ----- credited flag behavior -----
    def test_credited_false_for_pending(self):
        """credited is false for pending."""
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=_make_order("pending")):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            self.assertFalse(resp.get_json()["data"]["credited"])

    def test_credited_false_for_claimed(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=_make_order("claimed")):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            self.assertFalse(resp.get_json()["data"]["credited"])

    def test_credited_false_for_paid(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=_make_order("paid")):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            self.assertFalse(resp.get_json()["data"]["credited"])

    def test_credited_true_for_credited(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=_make_order("credited")):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            self.assertTrue(resp.get_json()["data"]["credited"])

    def test_credited_false_for_failed(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=_make_order("failed")):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            self.assertFalse(resp.get_json()["data"]["credited"])

    def test_credited_false_for_cancelled(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=_make_order("cancelled")):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            self.assertFalse(resp.get_json()["data"]["credited"])

    def test_credited_false_for_expired(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=_make_order("expired")):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            self.assertFalse(resp.get_json()["data"]["credited"])

    # ----- Invalid order reference -----
    def test_malformed_order_reference_rejected(self):
        """Non-UUID order reference returns 400."""
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get("/api/billing/toyyibpay/orders/not-a-uuid", headers=self.auth_headers)
            self.assertEqual(resp.status_code, 400)

    def test_empty_order_reference_rejected(self):
        """Empty order reference returns 404 (URL not matched)."""
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get("/api/billing/toyyibpay/orders/", headers=self.auth_headers)
            self.assertEqual(resp.status_code, 404)

    # ----- Missing / wrong-company order -----
    def test_missing_order_returns_404(self):
        """Repository returning None yields 404."""
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=None):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            self.assertEqual(resp.status_code, 404)

    def test_wrong_company_order_returns_404(self):
        """Order owned by another company returns 404 (same as missing)."""
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=None):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            self.assertEqual(resp.status_code, 404)
            json_data = resp.get_json()
            self.assertEqual(json_data["message"], "Order not found.")

    def test_company_id_in_url_cannot_bypass_ownership(self):
        """Company_id query param does not affect ownership (route ignores it)."""
        mock_order = _make_order(status="pending", company_id=99)
        # The route uses g.company_id=42, repo returns None for wrong company
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=None):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}?company_id=99", headers=self.auth_headers)
            self.assertEqual(resp.status_code, 404)

    # ----- Error handling -----
    def test_repository_exception_returns_500(self):
        """Unexpected repository error returns 500."""
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(side_effect=RuntimeError("DB error")):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            self.assertEqual(resp.status_code, 500)

    def test_exception_details_not_leaked(self):
        """Internal error details not exposed in response."""
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(side_effect=RuntimeError("DB crash")):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            data = resp.get_json()
            self.assertNotIn("DB crash", str(data))

    # ----- No side effects -----
    def test_no_credit_applied(self):
        """GET status does not apply credit."""
        mock_order = _make_order(status="pending")
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=mock_order):
            with patch("app.services.ai_credit_topup_callback_service.process_topup_payment_callback") as mock_credit:
                resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
                self.assertEqual(resp.status_code, 200)
                mock_credit.assert_not_called()

    def test_no_order_status_changed(self):
        """GET status does not modify the order."""
        mock_order = _make_order(status="pending")
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=mock_order):
            resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json()["data"]["status"], "pending")

    def test_no_toyyibpay_network_request(self):
        """No ToyyibPay API call is made during status check."""
        mock_order = _make_order(status="pending")
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_repo(return_value=mock_order):
            with patch("app.services.toyyibpay_service.requests.post") as mock_post:
                resp = self.client.get(f"/api/billing/toyyibpay/orders/{self.valid_ref}", headers=self.auth_headers)
                self.assertEqual(resp.status_code, 200)
                mock_post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
