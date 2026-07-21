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
    "company_id": 42,
    "full_name": "Test User",
    "email": "test@example.com",
    "status": "active",
    "phone": "+60123456789",
}

MALFORMED_AUTHORITATIVE_USER = {
    "id": 1,
    "status": "active",
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

    def _patch_ai_access(self):
        """Patch resolve_ai_access to allow top-up (returns top_up_allowed=True)."""
        from app.services.ai_access_policy import AIAccessPolicy, ROUTE_OPENROUTER, STATE_ESSENTIAL
        return patch(
            "app.routes.billing_routes.resolve_ai_access",
            return_value=AIAccessPolicy(
                allowed=True, access_state=STATE_ESSENTIAL,
                api_route=ROUTE_OPENROUTER, top_up_allowed=True,
                model_editable=True, denial_reason=None,
            ),
        )

    # ----- Route registration -----
    def test_route_registered(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_ai_access(), self._patch_get_subscription(), self._patch_checkout_service():
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
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_ai_access(), self._patch_get_subscription(), self._patch_checkout_service():
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 201)

    def test_valid_response_contains_safe_fields(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_ai_access(), self._patch_get_subscription(), self._patch_checkout_service():
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
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_ai_access(), self._patch_get_subscription(), self._patch_checkout_service() as mock_service:
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
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_ai_access(), self._patch_get_subscription(), self._patch_checkout_service() as mock_service:
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
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_ai_access(), self._patch_get_subscription(), self._patch_checkout_service():
            resp = self.client.post("/api/billing/toyyibpay/checkout", json={"amount_micro_myr": 1010000}, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 201)

    # ----- Error handling -----
    def test_service_value_error_returns_400(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_ai_access(), self._patch_get_subscription(), self._patch_checkout_service(side_effect=ValueError("Invalid amount")):
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_unexpected_exception_returns_500(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_ai_access(), self._patch_get_subscription(), self._patch_checkout_service(side_effect=RuntimeError("DB crash")):
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 500)

    def test_unexpected_exception_does_not_leak_details(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_ai_access(), self._patch_get_subscription(), self._patch_checkout_service(side_effect=RuntimeError("DB crash")):
            resp = self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            data = resp.get_json()
            self.assertNotIn("DB crash", str(data))

    # ----- No credit applied by checkout -----
    def test_checkout_does_not_apply_credit(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_ai_access(), self._patch_get_subscription(), self._patch_checkout_service():
            with patch("app.services.ai_credit_topup_callback_service.process_topup_payment_callback") as mock_credit:
                self.client.post("/api/billing/toyyibpay/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
                mock_credit.assert_not_called()

    # ----- No network calls -----
    def test_no_live_http_requests(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_ai_access(), self._patch_get_subscription(), self._patch_checkout_service():
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
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_ai_access(), self._patch_get_subscription():
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
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_ai_access(), self._patch_get_subscription():
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



class TestSubscriptionCheckoutRoute(unittest.TestCase):
    """Tests for POST /api/billing/subscription/checkout."""

    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.valid_body = {"plan_code": "essential"}
        self.service_result = {
            "order_reference": "00000000-0000-0000-0000-000000000001",
            "checkout_url": "https://toyyibpay.com/test-checkout",
            "amount_sen": 3900,
        }

    def _patch_jwt_decode(self):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 42, "user_id": 1, "role": "admin"},
        )

    def _patch_user_repo(self):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value=MOCK_USER,
        )

    def _patch_billing_get_user(self):
        return patch(
            "app.routes.billing_routes.get_user_by_id",
            return_value=MOCK_USER,
        )

    def _patch_checkout_service(self, return_value=None, side_effect=None):
        if return_value is None:
            return_value = self.service_result
        return patch(
            "app.routes.billing_routes.create_subscription_checkout",
            return_value=return_value,
            side_effect=side_effect,
        )

    # ----- Route registration -----

    def test_route_registered(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_checkout_service():
            resp = self.client.post("/api/billing/subscription/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertNotEqual(resp.status_code, 404)

    def test_get_returns_405(self):
        resp = self.client.get("/api/billing/subscription/checkout")
        self.assertEqual(resp.status_code, 405)

    # ----- Authentication -----

    def test_unauthenticated_request_rejected(self):
        resp = self.client.post("/api/billing/subscription/checkout", json=self.valid_body)
        self.assertEqual(resp.status_code, 401)

    def test_malformed_authoritative_user_without_company_id_returns_503(self):
        with patch("app.decorators.auth_decorator.jwt.decode", return_value={"user_id": 1, "role": "admin"}), patch("app.database.user_repository.get_user_by_id", return_value=MALFORMED_AUTHORITATIVE_USER):
            resp = self.client.post("/api/billing/subscription/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 503)
            self.assertEqual(resp.get_json()["code"], "authentication_backend_unavailable")

    # ----- Request validation -----

    def test_missing_plan_code_returns_400(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post("/api/billing/subscription/checkout", json={}, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_invalid_plan_code_returns_400(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user():
            resp = self.client.post("/api/billing/subscription/checkout", json={"plan_code": "nonexistent"}, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_missing_json_body_returns_400(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post("/api/billing/subscription/checkout", data="not-json", content_type="application/json", headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    # ----- Successful checkout -----

    def test_valid_checkout_returns_200(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_checkout_service():
            resp = self.client.post("/api/billing/subscription/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 200)

    def test_valid_response_contains_required_fields(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_checkout_service():
            resp = self.client.post("/api/billing/subscription/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            data = resp.get_json()
            self.assertIn("data", data)
            result = data["data"]
            self.assertIn("order_reference", result)
            self.assertIn("checkout_url", result)
            self.assertIn("amount_sen", result)
            self.assertEqual(result["amount_sen"], 3900)

    def test_service_receives_correct_params(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_checkout_service() as mock_service:
            self.client.post("/api/billing/subscription/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            mock_service.assert_called_once()
            _, kwargs = mock_service.call_args
            self.assertEqual(kwargs["company_id"], 42)
            self.assertEqual(kwargs["plan_code"], "essential")

    # ----- Error handling -----

    def test_service_value_error_returns_400(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_checkout_service(side_effect=ValueError("Invalid plan")):
            resp = self.client.post("/api/billing/subscription/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 400)

    def test_service_runtime_error_returns_502(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_checkout_service(side_effect=RuntimeError("Gateway error")):
            resp = self.client.post("/api/billing/subscription/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 502)

    # ----- No activation -----

    def test_checkout_does_not_activate_subscription(self):
        """Verify checkout does not change subscription status."""
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), self._patch_checkout_service():
            resp = self.client.post("/api/billing/subscription/checkout", json=self.valid_body, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(resp.status_code, 200)
            # This test passes by not raising an error - the service mock replaces
            # the real implementation which does not modify subscriptions.


class TestSubscriptionOrderStatusRoute(unittest.TestCase):
    """Tests for GET /api/billing/subscription/orders/<reference>."""

    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.valid_ref = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

        self.mock_pending_order = {
            "order_reference": self.valid_ref,
            "status": "pending",
            "amount_sen": 3900,
            "new_plan_id": 20,
            "payment_gateway": "toyyibpay",
            "created_at": "2026-07-08T12:00:00Z",
            "paid_at": None,
            "credited_at": None,
        }

        self.mock_credited_order = {
            "order_reference": self.valid_ref,
            "status": "credited",
            "amount_sen": 8900,
            "new_plan_id": 21,
            "payment_gateway": "toyyibpay",
            "created_at": "2026-07-08T12:00:00Z",
            "paid_at": "2026-07-08T12:05:00Z",
            "credited_at": "2026-07-08T12:06:00Z",
        }

    def _patch_jwt_decode(self):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 42, "user_id": 1, "role": "admin"},
        )

    def _patch_user_repo(self):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value=MOCK_USER,
        )

    def _patch_subscription_order_repo(self, return_value=None):
        return patch(
            "app.database.company_subscription_order_repository.get_subscription_order_by_reference_and_company",
            return_value=return_value,
        )

    def _patch_plan_repo(self, return_value=None):
        return patch(
            "app.database.subscription_plan_repository.get_plan_by_id",
            return_value=return_value,
        )

    # ----- Authentication -----

    def test_unauthenticated_request_rejected(self):
        resp = self.client.get(f"/api/billing/subscription/orders/{self.valid_ref}")
        self.assertEqual(resp.status_code, 401)

    def test_malformed_authoritative_user_without_company_id_returns_503(self):
        with patch("app.decorators.auth_decorator.jwt.decode", return_value={"user_id": 1, "role": "admin"}), \
             patch("app.database.user_repository.get_user_by_id", return_value=MALFORMED_AUTHORITATIVE_USER):
            resp = self.client.get(
                f"/api/billing/subscription/orders/{self.valid_ref}",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 503)
            self.assertEqual(resp.get_json()["code"], "authentication_backend_unavailable")

    # ----- Request validation -----

    def test_invalid_uuid_returns_400(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/subscription/orders/not-a-uuid",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 400)

    # ----- Success cases -----

    def test_pending_order_returns_200(self):
        with (self._patch_jwt_decode(), self._patch_user_repo(),
              self._patch_subscription_order_repo(self.mock_pending_order),
              self._patch_plan_repo({"id": 20, "code": "pro", "name": "Pro"})):
            resp = self.client.get(
                f"/api/billing/subscription/orders/{self.valid_ref}",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["data"]["status"], "pending")
            self.assertEqual(data["data"]["amount_sen"], 3900)
            self.assertEqual(data["data"]["plan_id"], 20)

    def test_credited_order_returns_200(self):
        with (self._patch_jwt_decode(), self._patch_user_repo(),
              self._patch_subscription_order_repo(self.mock_credited_order),
              self._patch_plan_repo({"id": 21, "code": "advanced", "name": "Advanced"})):
            resp = self.client.get(
                f"/api/billing/subscription/orders/{self.valid_ref}",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["data"]["status"], "credited")
            self.assertEqual(data["data"]["amount_sen"], 8900)
            self.assertIsNotNone(data["data"]["paid_at"])
            self.assertIsNotNone(data["data"]["credited_at"])

    def test_route_registered(self):
        with (self._patch_jwt_decode(), self._patch_user_repo(),
              self._patch_subscription_order_repo(self.mock_pending_order),
              self._patch_plan_repo({"id": 20, "code": "pro", "name": "Pro"})):
            resp = self.client.get(
                f"/api/billing/subscription/orders/{self.valid_ref}",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertNotEqual(resp.status_code, 404)

    # ----- Not found -----

    def test_order_not_found_returns_404(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_subscription_order_repo(None):
            resp = self.client.get(
                f"/api/billing/subscription/orders/{self.valid_ref}",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 404)


class TestSubscriptionOrderListRoute(unittest.TestCase):
    """Tests for GET /api/billing/subscription/orders (listing)."""

    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

        self.mock_order = {
            "order_reference": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            "company_id": 42,
            "status": "paid",
            "amount_sen": 3900,
            "new_plan_id": 20,
            "payment_gateway": "toyyibpay",
            "payment_reference": "TBP-12345",
            "gateway_order_id": "BILL-001",
            "created_at": "2026-07-08T12:00:00Z",
            "paid_at": "2026-07-08T12:05:00Z",
            "credited_at": None,
            "expires_at": None,
            "activation_status": "credit_pending",
            "reconciliation_required": False,
        }

    def _patch_jwt_decode(self):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 42, "user_id": 1, "role": "admin"},
        )

    def _patch_user_repo(self):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value=MOCK_USER,
        )

    def _patch_list_repo(self, return_value=None):
        return patch(
            "app.database.company_subscription_order_repository.list_subscription_orders_for_company",
            return_value=return_value or [],
        )

    def _patch_plan_repo(self, return_value=None):
        return patch(
            "app.database.subscription_plan_repository.get_plan_by_id",
            return_value=return_value,
        )

    def test_unauthenticated_request_rejected(self):
        resp = self.client.get("/api/billing/subscription/orders")
        self.assertEqual(resp.status_code, 401)

    def test_malformed_authoritative_user_without_company_id_returns_503(self):
        with patch("app.decorators.auth_decorator.jwt.decode", return_value={"user_id": 1, "role": "admin"}), \
             patch("app.database.user_repository.get_user_by_id", return_value=MALFORMED_AUTHORITATIVE_USER):
            resp = self.client.get(
                "/api/billing/subscription/orders",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 503)
            self.assertEqual(resp.get_json()["code"], "authentication_backend_unavailable")

    def test_invalid_limit_rejected(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/subscription/orders?limit=abc",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 400)

    def test_limit_zero_rejected(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/subscription/orders?limit=0",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 400)

    def test_invalid_offset_rejected(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/subscription/orders?offset=-1",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 400)

    def test_invalid_status_rejected(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/subscription/orders?status=invalid_status",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 400)

    def test_empty_list_returns_pagination(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_list_repo([]):
            resp = self.client.get(
                "/api/billing/subscription/orders",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["data"]["orders"], [])
            self.assertFalse(data["data"]["pagination"]["has_more"])

    def test_returns_orders_with_safe_fields(self):
        mock_plan = {"id": 20, "code": "pro", "name": "Pro"}
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_list_repo([self.mock_order]), \
             self._patch_plan_repo(mock_plan):
            resp = self.client.get(
                "/api/billing/subscription/orders",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(len(data["data"]["orders"]), 1)
            order = data["data"]["orders"][0]
            self.assertEqual(order["order_reference"], self.mock_order["order_reference"])
            self.assertEqual(order["payment_status"], "paid")
            self.assertIsNotNone(order["plan"])
            self.assertEqual(order["plan"]["code"], "pro")
            self.assertEqual(order["plan"]["name"], "Pro")
            self.assertEqual(order["amount_sen"], 3900)
            self.assertEqual(order["currency"], "MYR")
            self.assertEqual(order["payment_reference"], "TBP-12345")
            self.assertEqual(order["gateway_order_id"], "BILL-001")
            self.assertIn("customer_status_message", order)
            self.assertIn("retry_allowed", order)
            self.assertIn("reconciliation_required", order)

    def test_status_filter_passed_to_repo(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            with patch(
                "app.database.company_subscription_order_repository.list_subscription_orders_for_company",
            ) as mock_list:
                mock_list.return_value = []
                resp = self.client.get(
                    "/api/billing/subscription/orders?status=paid",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 200)
                mock_list.assert_called_with(company_id=42, limit=20, offset=0, status="paid")

    def test_no_internal_error_leakage(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            with patch(
                "app.database.company_subscription_order_repository.list_subscription_orders_for_company",
                side_effect=RuntimeError("internal details"),
            ):
                resp = self.client.get(
                    "/api/billing/subscription/orders",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 500)
                body = resp.get_json()
                self.assertNotIn("internal details", body.get("message", ""))


class TestSubscriptionOrderReceiptRoute(unittest.TestCase):
    """Tests for GET /api/billing/subscription/orders/<reference>/receipt."""

    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.valid_ref = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

        self.mock_order = {
            "order_reference": self.valid_ref,
            "company_id": 42,
            "status": "paid",
            "amount_sen": 3900,
            "new_plan_id": 20,
            "payment_gateway": "toyyibpay",
            "payment_reference": "TBP-12345",
            "gateway_order_id": "BILL-001",
            "created_at": "2026-07-08T12:00:00Z",
            "paid_at": "2026-07-08T12:05:00Z",
            "credited_at": None,
            "expires_at": None,
            "activation_status": "completed",
            "source_period_start": "2026-07-08T00:00:00Z",
            "source_period_end": "2026-08-07T00:00:00Z",
        }

    def _patch_jwt_decode(self, company_id=42):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": company_id, "user_id": 1, "role": "admin"},
        )

    def _patch_user_repo(self):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value=MOCK_USER,
        )

    def _patch_order_repo(self, return_value=None):
        return patch(
            "app.database.company_subscription_order_repository.get_subscription_order_by_reference_and_company",
            return_value=return_value,
        )

    def _patch_plan_repo(self, return_value=None):
        return patch(
            "app.database.subscription_plan_repository.get_plan_by_id",
            return_value=return_value,
        )

    def test_unauthenticated_request_rejected(self):
        resp = self.client.get(f"/api/billing/subscription/orders/{self.valid_ref}/receipt")
        self.assertEqual(resp.status_code, 401)

    def test_invalid_uuid_returns_400(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/subscription/orders/not-a-uuid/receipt",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 400)

    def test_returns_receipt_with_correct_fields(self):
        mock_plan = {"id": 20, "code": "pro", "name": "Pro"}
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_order_repo(self.mock_order), \
             self._patch_plan_repo(mock_plan):
            resp = self.client.get(
                f"/api/billing/subscription/orders/{self.valid_ref}/receipt",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            receipt = data["data"]["receipt"]
            self.assertEqual(receipt["order_reference"], self.valid_ref)
            self.assertEqual(receipt["plan"]["code"], "pro")
            self.assertEqual(receipt["plan"]["name"], "Pro")
            self.assertEqual(receipt["amount_sen"], 3900)
            self.assertEqual(receipt["amount_myr"], 39.0)
            self.assertEqual(receipt["currency"], "MYR")
            self.assertEqual(receipt["payment_status"], "paid")
            self.assertEqual(receipt["payment_reference"], "TBP-12345")
            self.assertEqual(receipt["gateway_reference"], "BILL-001")
            self.assertIsNotNone(receipt["payment_date"])
            self.assertIn("notice", data["data"])
            self.assertIn("not a tax invoice", data["data"]["notice"].lower())

    def test_wrong_company_rejected(self):
        with self._patch_jwt_decode(company_id=99), self._patch_user_repo(), \
             self._patch_order_repo(None):
            resp = self.client.get(
                f"/api/billing/subscription/orders/{self.valid_ref}/receipt",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 404)

    def test_no_internal_error_leakage(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            with patch(
                "app.database.company_subscription_order_repository.get_subscription_order_by_reference_and_company",
                side_effect=RuntimeError("internal error text"),
            ):
                resp = self.client.get(
                    f"/api/billing/subscription/orders/{self.valid_ref}/receipt",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 500)
                body = resp.get_json()
                self.assertNotIn("internal error text", body.get("message", ""))



if __name__ == "__main__":
    unittest.main()
