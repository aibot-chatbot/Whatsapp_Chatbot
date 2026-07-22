"""Tests for AI-credit top-up checkout access enforcement.

Route-level tests confirming that Free/trial users are blocked from
POST /api/billing/toyyibpay/checkout and paid users can proceed.
"""

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
    "role": "admin",
    "status": "active",
    "phone": "+60123456789",
}


class TestToyyibPayCheckoutTopUpEnforcement(unittest.TestCase):
    """Tests that Free/trial companies are blocked from top-up checkout."""

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
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value=MOCK_USER,
        )

    def _patch_billing_get_user(self):
        return patch(
            "app.routes.billing_routes.get_user_by_id",
            return_value=MOCK_USER,
        )

    def _patch_get_subscription(self, return_value=None):
        if return_value is None:
            return_value = {"id": 99, "plan_name": "free"}
        return patch(
            "app.routes.billing_routes.get_current_subscription",
            return_value=return_value,
        )

    def _patch_checkout_service(self, return_value=None, side_effect=None):
        if return_value is None:
            return_value = self.service_result
        return patch(
            "app.routes.billing_routes.create_toyyibpay_topup_checkout",
            return_value=return_value,
            side_effect=side_effect,
        )

    def _patch_ai_access_blocked(self, denial_reason=None):
        """Patch resolve_ai_access to deny top-up (top_up_allowed=False)."""
        from app.services.ai_access_policy import AIAccessPolicy
        if denial_reason is None:
            denial_reason = "AI credit top-up is not available on your current plan."
        return patch(
            "app.routes.billing_routes.resolve_ai_access",
            return_value=AIAccessPolicy(
                allowed=False, top_up_allowed=False,
                denial_reason=denial_reason,
            ),
        )

    def _patch_ai_access_allowed(self):
        """Patch resolve_ai_access to allow top-up."""
        from app.services.ai_access_policy import AIAccessPolicy, ROUTE_OPENROUTER, STATE_ESSENTIAL
        return patch(
            "app.routes.billing_routes.resolve_ai_access",
            return_value=AIAccessPolicy(
                allowed=True, access_state=STATE_ESSENTIAL,
                api_route=ROUTE_OPENROUTER, top_up_allowed=True,
                model_editable=True, denial_reason=None,
            ),
        )

    # ----- Free/trial blocking -----

    def test_free_trial_blocked_returns_403(self):
        """Free trial company cannot create top-up checkout."""
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), \
             self._patch_ai_access_blocked(), self._patch_get_subscription():
            resp = self.client.post(
                "/api/billing/toyyibpay/checkout",
                json=self.valid_body,
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 403)

    def test_free_trial_403_body_includes_denial_reason(self):
        """403 response body includes the backend denial reason."""
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), \
             self._patch_ai_access_blocked(
                 denial_reason="Your trial has expired. Please subscribe to continue."), \
             self._patch_get_subscription():
            resp = self.client.post(
                "/api/billing/toyyibpay/checkout",
                json=self.valid_body,
                headers={"Authorization": "Bearer test-token"},
            )
            data = resp.get_json()
            self.assertEqual(data["status"], "error")
            self.assertIn("trial has expired", data["message"])

    def test_free_trial_403_fallback_message(self):
        """When policy has no denial_reason, route fallback message is used."""
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), \
             self._patch_ai_access_blocked(denial_reason=None), \
             self._patch_get_subscription():
            resp = self.client.post(
                "/api/billing/toyyibpay/checkout",
                json=self.valid_body,
                headers={"Authorization": "Bearer test-token"},
            )
            data = resp.get_json()
            self.assertEqual(data["status"], "error")
            self.assertIn("not available on your current plan", data["message"])

    def test_free_trial_403_does_not_call_checkout_service(self):
        """Access blocked means checkout service is never invoked."""
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), \
             self._patch_ai_access_blocked(), self._patch_get_subscription(), \
             self._patch_checkout_service() as mock_checkout:
            self.client.post(
                "/api/billing/toyyibpay/checkout",
                json=self.valid_body,
                headers={"Authorization": "Bearer test-token"},
            )
            mock_checkout.assert_not_called()

    # ----- Paid active proceeds -----

    def test_paid_active_proceeds_to_checkout_service(self):
        """Paid active company with valid amount reaches checkout service."""
        with self._patch_jwt_decode(), self._patch_user_repo(), self._patch_billing_get_user(), \
             self._patch_ai_access_allowed(), \
             self._patch_get_subscription({"id": 99, "plan_name": "pro"}), \
             self._patch_checkout_service() as mock_checkout:
            resp = self.client.post(
                "/api/billing/toyyibpay/checkout",
                json=self.valid_body,
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 201)
            mock_checkout.assert_called_once()
            _, kwargs = mock_checkout.call_args
            self.assertEqual(kwargs["company_id"], 42)
            self.assertEqual(kwargs["amount_micro_myr"], self.valid_amount)

    # ----- Amount validation still runs -----

    def test_invalid_amount_rejected_before_policy_check(self):
        """Invalid amount is rejected early (before access policy or user lookup)."""
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/billing/toyyibpay/checkout",
                json={"amount_micro_myr": "not-a-number"},
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 400)

    # ----- Unauthenticated -----

    def test_unauthenticated_returns_401_before_policy_check(self):
        """Unauthenticated request is rejected before consulting access policy."""
        resp = self.client.post(
            "/api/billing/toyyibpay/checkout",
            json=self.valid_body,
        )
        self.assertEqual(resp.status_code, 401)
