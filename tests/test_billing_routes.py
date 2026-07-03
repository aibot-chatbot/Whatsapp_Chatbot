"""Tests for the ToyyibPay AI-credit checkout HTTP route."""

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
sys.path.insert(0, "C:\\Users\\User\\PycharmProjects\\python-whatsapp-bot-main")

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
    "full_name": "Test User",
    "email": "test@example.com",
    "status": "active",
    "phone": "+60123456789",
}


class TestToyyibPayCheckoutRoute(unittest.TestCase):
    """Tests for POST /api/billing/toyyibpay/checkout."""

    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.valid_amount = 2_000_000  # RM2.00
        self.valid_body = {"amount_micro_myr": self.valid_amount}

        self.service_result = {
            "status": "pending",
            "order_reference": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            "gateway_order_id": "test-bill-code",
            "checkout_url": "https://toyyibpay.com/test-bill-code",
            "amount_micro_myr": self.valid_amount,
            "currency": "MYR",
            "payment_gateway": "toyyibpay",
            "expires_at": None,
        }

    def _patch_jwt_decode(self):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 42, "user_id": 1, "role": "admin"},
        )

    def _patch_user_repo(self):
        """Patch get_user_by_id in user_repository (used by token_required via lazy import)."""
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value=MOCK_USER,
        )

    def _patch_billing_get_user(self):
        """Patch get_user_by_id in billing_routes (module-level import used by route handler)."""
        return patch(
            "app.routes.billing_routes.get_user_by_id",
            return_value=MOCK_USER,
        )

    def _patch_checkout_service(self, return_value=None, side_effect=None):
        if return_value is None:
            return_value = self.service_result
        return patch(
            "app.routes.billing_routes.create_toyyibpay_topup_checkout",
            return_value=return_value,
            side_effect=side_effect,
        )

    def _patch_get_subscription(self, return_value=None, side_effect=None):
        if return_value is None:
            return_value = {"id": 99, "plan_name": "pro"}
        return patch(
            "app.routes.billing_routes.get_current_subscription",
            return_value=return_value,
            side_effect=side_effect,
        )

    # ----- Route registration -----
    def test_route_registered(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_get_subscription(), self._patch_checkout_service():
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertNotEqual(resp.status_code, 404)

    def test_get_returns_405(self):
        resp = self.client.get("/api/billing/toyyibpay/checkout")
        self.assertEqual(resp.status_code, 405)

    # ----- Authentication -----
    def test_unauthenticated_request_rejected(self):
        resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body)
        self.assertEqual(resp.status_code, 401)

    # ----- Successful checkout -----
    def test_valid_checkout_returns_201(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_get_subscription(), self._patch_checkout_service():
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 201)

    def test_valid_response_contains_safe_fields(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_get_subscription(), self._patch_checkout_service():
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            data = resp.get_json()
            self.assertIn("data", data)
            result = data["data"]
            expected_keys = {"status", "order_reference", "gateway_order_id", "checkout_url", "amount_micro_myr", "currency", "payment_gateway", "expires_at"}
            self.assertEqual(set(result.keys()), expected_keys)
            self.assertEqual(result["payment_gateway"], "toyyibpay")
            self.assertNotIn("UserSecretKey", str(data))
            self.assertNotIn("secret", str(data).lower())

    def test_service_receives_correct_params(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_get_subscription(), self._patch_checkout_service() as mock_service:
            self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            mock_service.assert_called_once()
            _, kwargs = mock_service.call_args
            self.assertEqual(kwargs["company_id"], 42)
            self.assertEqual(kwargs["subscription_id"], 99)
            self.assertEqual(kwargs["created_by_user_id"], 1)
            self.assertEqual(kwargs["amount_micro_myr"], 2000000)
            self.assertEqual(kwargs["customer_email"], "test@example.com")
            self.assertEqual(kwargs["customer_name"], "Test User")
            self.assertIsInstance(kwargs["idempotency_key"], str)

    # ----- company_id from body -----
    def test_company_id_in_body_ignored(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_get_subscription(), self._patch_checkout_service() as mock_service:
            body = {**self.valid_body, "company_id": 999}
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 201)
            _, kwargs = mock_service.call_args
            self.assertEqual(kwargs["company_id"], 42)

    # ----- Malformed/missing JSON -----
    def test_missing_json_body_returns_400(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post("/api/billing/toyyibpay/checkout", data="not-json", content_type="application/json", headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_empty_json_body_returns_400(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post("/api/billing/toyyibpay/checkout", json={}, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_missing_amount_key_returns_400(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post("/api/billing/toyyibpay/checkout", json={"other": "value"}, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    # ----- Amount validation -----
    def test_boolean_amount_rejected(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post("/api/billing/toyyibpay/checkout", json={"amount_micro_myr": True}, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_string_amount_rejected(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post("/api/billing/toyyibpay/checkout", json={"amount_micro_myr": "2000000"}, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_zero_amount_rejected(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post("/api/billing/toyyibpay/checkout", json={"amount_micro_myr": 0}, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_negative_amount_rejected(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post("/api/billing/toyyibpay/checkout", json={"amount_micro_myr": -100}, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_non_divisible_amount_rejected(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post("/api/billing/toyyibpay/checkout", json={"amount_micro_myr": 12345}, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_below_minimum_amount_rejected(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post("/api/billing/toyyibpay/checkout", json={"amount_micro_myr": 1000000}, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_minimum_valid_amount_accepted(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_get_subscription(), self._patch_checkout_service():
            resp = self.client.post("/api/billing/toyyibpay/checkout", json={"amount_micro_myr": 1010000}, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 201)

    # ----- Error handling -----
    def test_service_value_error_returns_400(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_get_subscription(), self._patch_checkout_service(side_effect=ValueError("Invalid amount")):
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_unexpected_exception_returns_500(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_get_subscription(), self._patch_checkout_service(side_effect=RuntimeError("DB crash")):
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 500)

    def test_unexpected_exception_does_not_leak_details(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_get_subscription(), self._patch_checkout_service(side_effect=RuntimeError("DB crash")):
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            data = resp.get_json()
            self.assertNotIn("DB crash", str(data))

    # ----- No credit applied by checkout -----
    def test_checkout_does_not_apply_credit(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_get_subscription(), self._patch_checkout_service():
            with patch("app.services.ai_credit_topup_callback_service.process_topup_payment_callback") as mock_credit:
                self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
                mock_credit.assert_not_called()

    # ----- No network calls -----
    def test_no_live_http_requests(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_get_subscription(), self._patch_checkout_service():
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 201)


    # ----- Phone validation -----
    def _patch_billing_get_user_with_phone(self, phone_value):
        user = dict(MOCK_USER)
        user["phone"] = phone_value
        return patch(
            "app.routes.billing_routes.get_user_by_id",
            return_value=user,
        )

    def test_valid_phone_passed_to_service(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_get_subscription():
            with patch("app.routes.billing_routes.create_toyyibpay_topup_checkout") as mock_svc:
                mock_svc.return_value = self.service_result
                self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
                _, kwargs = mock_svc.call_args
                self.assertEqual(kwargs["customer_phone"], "+60123456789")

    def test_missing_phone_returns_400(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user_with_phone(None):
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)
            data = resp.get_json()
            self.assertIn("phone number", str(data).lower())

    def test_null_phone_returns_400(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user_with_phone(None):
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_empty_phone_returns_400(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user_with_phone(""):
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_whitespace_phone_returns_400(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user_with_phone("   "):
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_invalid_phone_returns_400(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user_with_phone("abc"):
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_short_phone_returns_400(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user_with_phone("12345"):
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_request_phone_ignored(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_get_subscription():
            with patch("app.routes.billing_routes.create_toyyibpay_topup_checkout") as mock_svc:
                mock_svc.return_value = self.service_result
                body = dict(self.valid_body)
                body["customer_phone"] = "ignored"
                self.client.post("/api/billing/toyyibpay/checkout", json=body, headers={"Authorization": "Bearer test-token"})
                _, kwargs = mock_svc.call_args
                self.assertEqual(kwargs["customer_phone"], "+60123456789")

    def test_no_order_created_for_missing_phone(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user_with_phone(None):
            with patch("app.services.ai_credit_topup_checkout_service.create_toyyibpay_topup_checkout") as mock_svc:
                self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
                mock_svc.assert_not_called()

    def test_toyyibpay_not_called_for_invalid_phone(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user_with_phone("abc"):
            with patch("app.services.toyyibpay_service.create_bill") as mock_toyyibpay:
                self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
                mock_toyyibpay.assert_not_called()

if __name__ == "__main__":
    unittest.main()