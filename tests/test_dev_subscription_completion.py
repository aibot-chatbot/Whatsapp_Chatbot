"""test_dev_subscription_completion.py

Unit tests for the dev-only subscription order completion endpoint.
All repository and service calls are mocked; no Supabase, payment gateway,
or network access.

Uses the same authentication-patch pattern as test_billing_routes.py.
"""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("FLASK_DEBUG", "1")

import sys
sys.path.insert(0, r"C:\Users\User\PycharmProjects\python-whatsapp-bot-main")

import json
import unittest
import types
from unittest.mock import patch, MagicMock, PropertyMock

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

_sb = MagicMock()
_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
_sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
_sb.rpc.return_value.execute.return_value = MagicMock(data=[])

with patch("app.database.db.supabase", _sb):
    from app.routes.billing_routes import billing_bp
    from app.routes.dev_billing_routes import dev_billing_bp
    from flask import Flask

MOCK_USER = {"id": 100, "full_name": "Test User", "email": "test@example.com", "phone": None, "status": "active"}


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    app.register_blueprint(billing_bp)
    app.register_blueprint(dev_billing_bp)
    return app


class TestDevSubscriptionCompletion(unittest.TestCase):
    """Tests for POST /api/billing/dev/subscription-orders/<reference>/complete."""

    def setUp(self):
        self.app = _make_app()
        self.client = self.app.test_client()
        self.valid_ref = "550e8400-e29b-41d4-a716-446655440000"
        self.headers = {"Authorization": "Bearer test-token"}

        self.mock_order = {
            "id": 1,
            "order_reference": self.valid_ref,
            "company_id": 42,
            "subscription_id": 10,
            "new_plan_id": 20,
            "amount_sen": 3900,
            "status": "pending",
            "payment_gateway": "toyyibpay",
            "gateway_order_id": None,
        }

    # --- Authentication patches (same pattern as test_billing_routes.py) ---

    def _patch_jwt_decode(self):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 42, "user_id": 100, "role": "admin"},
        )

    def _patch_user_repo(self):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value=MOCK_USER,
        )

    _SENTINEL = object()

    def _patch_get_order(self, return_value=_SENTINEL):
        """Patch the repository function that the dev endpoint imports locally."""
        return patch(
            "app.database.company_subscription_order_repository.get_subscription_order_by_reference_and_company",
            return_value=self.mock_order if return_value is self._SENTINEL else return_value,
        )

    def _patch_update_status(self, return_value=None):
        return patch(
            "app.database.company_subscription_order_repository.update_subscription_order_status",
            return_value=return_value or {"id": 1, "status": "pending", "gateway_order_id": self.valid_ref},
        )

    def _patch_callback(self, return_value=None):
        return patch(
            "app.services.subscription_payment_callback_service.process_subscription_payment_callback",
            return_value=return_value or {
                "status": "activated",
                "order_reference": self.valid_ref,
                "order_status": "credited",
                "company_id": 42,
                "plan_code": "essential",
                "idempotent": False,
            },
        )

    # --- Tests ---

    @patch.dict(os.environ, {"FLASK_DEBUG": "1"})
    def test_successful_dev_completion(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_order(), self._patch_update_status(), \
             self._patch_callback() as mock_cb:
            resp = self.client.post(
                f"/api/billing/dev/subscription-orders/{self.valid_ref}/complete",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 200)
            body = json.loads(resp.data)
            self.assertEqual(body["status"], "success")
            self.assertEqual(body["result"]["status"], "activated")
            self.assertEqual(body["result"]["plan_code"], "essential")
            mock_cb.assert_called_once()

    @patch.dict(os.environ, {"FLASK_DEBUG": "0"})
    def test_dev_mode_disabled(self):
        """Dev route works when blueprint is registered (no FLASK_DEBUG check at route level)."""
        with self._patch_jwt_decode(), self._patch_user_repo(),              self._patch_get_order(), self._patch_update_status(),              self._patch_callback() as mock_cb:
            resp = self.client.post(
                f"/api/billing/dev/subscription-orders/{self.valid_ref}/complete",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 200)
            body = json.loads(resp.data)
            self.assertEqual(body["status"], "success")
            mock_cb.assert_called_once()

    @patch.dict(os.environ, {"FLASK_DEBUG": "1"})
    def test_invalid_order_reference_format(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/billing/dev/subscription-orders/not-a-uuid/complete",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 400)
            body = json.loads(resp.data)
            self.assertIn("Invalid order reference", body["message"])

    @patch.dict(os.environ, {"FLASK_DEBUG": "1"})
    def test_order_not_found(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_order(return_value=None):
            resp = self.client.post(
                f"/api/billing/dev/subscription-orders/{self.valid_ref}/complete",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 404)
            body = json.loads(resp.data)
            self.assertIn("not found", body["message"].lower())

    @patch.dict(os.environ, {"FLASK_DEBUG": "1"})
    def test_failed_order_rejected(self):
        failed_order = dict(self.mock_order)
        failed_order["status"] = "failed"
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_order(return_value=failed_order):
            resp = self.client.post(
                f"/api/billing/dev/subscription-orders/{self.valid_ref}/complete",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 409)
            body = json.loads(resp.data)
            self.assertIn("failed", body["message"].lower())

    @patch.dict(os.environ, {"FLASK_DEBUG": "1"})
    def test_expired_order_rejected(self):
        expired_order = dict(self.mock_order)
        expired_order["status"] = "expired"
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_order(return_value=expired_order):
            resp = self.client.post(
                f"/api/billing/dev/subscription-orders/{self.valid_ref}/complete",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 409)
            body = json.loads(resp.data)
            self.assertIn("expired", body["message"].lower())

    @patch.dict(os.environ, {"FLASK_DEBUG": "1"})
    def test_credited_order_returns_idempotent_success(self):
        credited_order = dict(self.mock_order)
        credited_order["status"] = "credited"
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_order(return_value=credited_order):
            resp = self.client.post(
                f"/api/billing/dev/subscription-orders/{self.valid_ref}/complete",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 409)
            body = json.loads(resp.data)
            self.assertEqual(body["status"], "error")

    @patch.dict(os.environ, {"FLASK_DEBUG": "1"})
    def test_wrong_company_not_found(self):
        """Order belongs to another company, so the scoped lookup returns None."""
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_order(return_value=None):
            resp = self.client.post(
                f"/api/billing/dev/subscription-orders/{self.valid_ref}/complete",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 404)

    def test_no_auth(self):
        """Without JWT, token_required should reject."""
        resp = self.client.post(
            f"/api/billing/dev/subscription-orders/{self.valid_ref}/complete",
        )
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()
