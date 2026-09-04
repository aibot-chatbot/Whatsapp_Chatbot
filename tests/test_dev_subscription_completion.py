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
import pathlib
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import json
import unittest
import types
from unittest.mock import ANY, patch, MagicMock, PropertyMock

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

MOCK_USER = {"id": 100, "company_id": 42, "full_name": "Test User", "email": "test@example.com", "phone": None, "role": "admin", "status": "active"}


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    app.config["ENABLE_DEV_BILLING_ROUTES"] = True
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
            "source_plan_id": 1,
            "source_status": "active",
            "source_period_start": "2026-08-01T00:00:00+00:00",
            "source_period_end": "2026-09-01T00:00:00+00:00",
            "activation_type": "upgrade",
            "activation_sequence_key": "company:42:upgrade-from:1:period:2026-08-01T00:00:00+00:00",
            "order_schema_version": 2,
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

    def _advanced_plan(self):
        return {
            "id": 20,
            "code": "advanced",
            "name": "Advanced",
            "is_active": True,
            "billing_interval": "monthly",
            "included_ai_credit_micro_myr": 20000000,
        }

    def _current_subscription(self):
        return {
            "id": 10,
            "company_id": 42,
            "plan_id": 1,
            "status": "active",
            "current_period_start": "2026-08-01T00:00:00+00:00",
            "current_period_end": "2026-09-01T00:00:00+00:00",
            "trial_ends_at": None,
            "plan": {"id": 1, "code": "free", "name": "Free"},
        }

    def _patch_prepare_service_deps(self, *, existing_sequence_order=None):
        return (
            patch("app.services.subscription_checkout_service.uuid.uuid4", return_value=self.valid_ref),
            patch(
                "app.services.subscription_checkout_service.get_current_subscription",
                return_value=self._current_subscription(),
            ),
            patch(
                "app.services.subscription_checkout_service.get_plan_by_code",
                return_value=self._advanced_plan(),
            ),
            patch(
                "app.services.subscription_checkout_service.get_subscription_order_by_activation_sequence_key",
                return_value=existing_sequence_order,
            ),
            patch(
                "app.database.company_subscription_order_repository.list_subscription_orders_for_company",
                return_value=[],
            ),
            patch(
                "app.services.subscription_checkout_service._build_checkout_expires_at",
                return_value="2026-08-13T15:59:59+00:00",
            ),
        )

    # --- Tests ---

    @patch.dict(os.environ, {"FLASK_DEBUG": "1"})
    def test_prepare_advanced_creates_pending_order_without_gateway(self):
        create_return = {
            "id": 77,
            "order_reference": self.valid_ref,
            "status": "pending",
            "gateway_order_id": None,
            "checkout_url": None,
        }
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_prepare_service_deps()[0], \
             self._patch_prepare_service_deps()[1], \
             self._patch_prepare_service_deps()[2], \
             self._patch_prepare_service_deps()[3], \
             self._patch_prepare_service_deps()[4], \
             self._patch_prepare_service_deps()[5], \
             patch("app.services.subscription_checkout_service.create_subscription_order", return_value=create_return) as mock_create, \
             patch("app.services.toyyibpay_service.requests.post") as toyyibpay_post, \
             patch("app.services.subscription_checkout_service.create_bill") as mock_bill:
            resp = self.client.post(
                "/api/billing/dev/subscription-orders/prepare",
                json={
                    "plan_code": "advanced",
                    "amount_sen": 1,
                    "company_id": 999,
                    "gateway_order_id": "attacker",
                    "paid": True,
                },
                headers=self.headers,
            )

        self.assertEqual(resp.status_code, 201)
        body = json.loads(resp.data)
        data = body["data"]
        self.assertEqual(data["order_reference"], self.valid_ref)
        self.assertEqual(data["amount_sen"], 8900)
        self.assertEqual(data["plan_code"], "advanced")
        self.assertEqual(data["status"], "pending")
        self.assertIsNone(data["gateway_order_id"])
        self.assertIsNone(data["checkout_url"])
        self.assertEqual(data["activation_type"], "upgrade")
        self.assertEqual(
            data["activation_sequence_key"],
            "company:42:upgrade-from:1:period:2026-08-01T00:00:00+00:00",
        )
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs["company_id"], 42)
        self.assertEqual(kwargs["new_plan_id"], 20)
        self.assertEqual(kwargs["amount_sen"], 8900)
        self.assertEqual(kwargs["subscription_id"], 10)
        self.assertEqual(kwargs["source_plan_id"], 1)
        self.assertEqual(kwargs["source_status"], "active")
        self.assertEqual(kwargs["source_period_start"], "2026-08-01T00:00:00+00:00")
        self.assertEqual(kwargs["source_period_end"], "2026-09-01T00:00:00+00:00")
        self.assertEqual(kwargs["order_schema_version"], 2)
        self.assertIsNone(kwargs.get("gateway_order_id"))
        mock_bill.assert_not_called()
        toyyibpay_post.assert_not_called()

    @patch.dict(os.environ, {"FLASK_DEBUG": "1"})
    def test_prepare_duplicate_activation_sequence_is_blocked(self):
        existing = dict(self.mock_order)
        existing["activation_sequence_key"] = "company:42:upgrade-from:1:period:2026-08-01T00:00:00+00:00"
        existing["expires_at"] = None
        patches = self._patch_prepare_service_deps(existing_sequence_order=existing)
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
             patch("app.services.subscription_checkout_service.create_subscription_order") as mock_create, \
             patch("app.services.subscription_checkout_service.create_bill") as mock_bill:
            resp = self.client.post(
                "/api/billing/dev/subscription-orders/prepare",
                json={"plan_code": "advanced"},
                headers=self.headers,
            )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("payment link is not available", json.loads(resp.data)["message"].lower())
        mock_create.assert_not_called()
        mock_bill.assert_not_called()

    @patch.dict(os.environ, {"FLASK_DEBUG": "0"})
    def test_prepare_disabled_without_debug_gate(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             patch("app.services.subscription_checkout_service.prepare_subscription_checkout_order") as mock_prepare:
            resp = self.client.post(
                "/api/billing/dev/subscription-orders/prepare",
                json={"plan_code": "advanced"},
                headers=self.headers,
            )

        self.assertEqual(resp.status_code, 404)
        mock_prepare.assert_not_called()

    @patch.dict(os.environ, {"FLASK_DEBUG": "1"})
    def test_prepare_requires_only_plan_code_from_body(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/billing/dev/subscription-orders/prepare",
                json={"company_id": 42, "amount_sen": 8900},
                headers=self.headers,
            )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("plan_code", json.loads(resp.data)["message"])

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
            callback_payload = mock_cb.call_args.args[0]
            self.assertEqual(callback_payload["payment_gateway"], "toyyibpay")
            self.assertEqual(callback_payload["gateway_order_id"], f"DEV_TEST_PAYMENT:{self.valid_ref}")
            self.assertEqual(callback_payload["payment_reference"], "DEV_TEST_PAYMENT")
            self.assertTrue(callback_payload["paid"])
            self.assertEqual(callback_payload["amount_sen"], 3900)
            self.assertIn("paid_at", callback_payload)

    @patch.dict(os.environ, {"FLASK_DEBUG": "0"})
    def test_dev_mode_disabled(self):
        """Dev route requires FLASK_DEBUG even when the blueprint is manually registered."""
        with self._patch_jwt_decode(), self._patch_user_repo(),              self._patch_get_order(), self._patch_update_status(),              self._patch_callback() as mock_cb:
            resp = self.client.post(
                f"/api/billing/dev/subscription-orders/{self.valid_ref}/complete",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 404)
            body = json.loads(resp.data)
            self.assertEqual(body["status"], "error")
            mock_cb.assert_not_called()

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
    def test_existing_gateway_id_is_reused(self):
        order = dict(self.mock_order)
        order["gateway_order_id"] = "existing-dev-gateway"
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_order(return_value=order), self._patch_update_status() as mock_update, \
             self._patch_callback() as mock_cb:
            resp = self.client.post(
                f"/api/billing/dev/subscription-orders/{self.valid_ref}/complete",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 200)

        mock_update.assert_not_called()
        callback_payload = mock_cb.call_args.args[0]
        self.assertEqual(callback_payload["gateway_order_id"], "existing-dev-gateway")

    @patch.dict(os.environ, {"FLASK_DEBUG": "1"})
    def test_request_body_amount_is_ignored(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_order(), self._patch_update_status(), \
             self._patch_callback() as mock_cb:
            resp = self.client.post(
                f"/api/billing/dev/subscription-orders/{self.valid_ref}/complete",
                json={"amount_sen": 1, "paid": False, "company_id": 999},
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 200)

        callback_payload = mock_cb.call_args.args[0]
        self.assertEqual(callback_payload["amount_sen"], 3900)
        self.assertTrue(callback_payload["paid"])

    @patch.dict(os.environ, {"FLASK_DEBUG": "1"})
    def test_malformed_order_rejected_before_callback(self):
        order = dict(self.mock_order)
        order["amount_sen"] = None
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_order(return_value=order), \
             self._patch_update_status() as mock_update, \
             self._patch_callback() as mock_cb:
            resp = self.client.post(
                f"/api/billing/dev/subscription-orders/{self.valid_ref}/complete",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 409)

        mock_update.assert_not_called()
        mock_cb.assert_not_called()

    @patch.dict(os.environ, {"FLASK_DEBUG": "1"})
    def test_real_callback_service_contract_with_synthetic_gateway_id(self):
        synthetic_gateway_id = f"DEV_TEST_PAYMENT:{self.valid_ref}"
        callback_order = dict(self.mock_order)
        callback_order["gateway_order_id"] = synthetic_gateway_id

        advanced_plan = {
            "id": 20,
            "code": "advanced",
            "name": "Advanced",
            "billing_interval": "monthly",
            "included_ai_credit_micro_myr": 20000000,
        }

        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_order(), \
             self._patch_update_status() as route_update, \
             patch(
                 "app.services.subscription_payment_callback_service._get_order_by_gateway",
                 return_value=callback_order,
             ) as get_by_gateway, \
             patch("app.services.subscription_payment_callback_service._update_order_status") as callback_update, \
             patch("app.services.subscription_payment_callback_service._update_activation_state") as activation_state, \
             patch("app.services.subscription_payment_callback_service._claim_activation_sequence") as claim_sequence, \
             patch("app.services.subscription_payment_callback_service.get_plan_by_id", return_value=advanced_plan), \
             patch("app.services.subscription_payment_callback_service.conditional_activate_subscription") as activate, \
             patch("app.services.subscription_payment_callback_service._ensure_company_ai_credit") as ensure_credit, \
             patch("app.services.subscription_payment_callback_service.convert_trial_ai_configuration") as convert_trial, \
             patch("app.services.billing_notification_service.notify_payment_confirmed"), \
             patch("app.services.billing_notification_service.notify_activation_completed"), \
             patch("app.services.toyyibpay_service.requests.post") as toyyibpay_post:
            resp = self.client.post(
                f"/api/billing/dev/subscription-orders/{self.valid_ref}/complete",
                json={"amount_sen": 1, "gateway_order_id": "attacker"},
                headers=self.headers,
            )

        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.data)
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["result"]["status"], "activated_and_credited")
        route_update.assert_called_once_with(
            self.valid_ref,
            "pending",
            gateway_order_id=synthetic_gateway_id,
        )
        get_by_gateway.assert_called_once_with(
            payment_gateway="toyyibpay",
            gateway_order_id=synthetic_gateway_id,
        )
        callback_update.assert_any_call(
            order_reference=self.valid_ref,
            status="paid",
            payment_reference="DEV_TEST_PAYMENT",
            paid_at=ANY,
        )
        callback_update.assert_any_call(
            order_reference=self.valid_ref,
            status="credited",
            credited_at=ANY,
        )
        claim_sequence.assert_called_once()
        activate.assert_called_once()
        ensure_credit.assert_called_once_with(42)
        convert_trial.assert_called_once_with(42, "advanced")
        toyyibpay_post.assert_not_called()

    @patch.dict(os.environ, {"FLASK_DEBUG": "1"})
    def test_dev_prepare_then_complete_uses_real_callback_service_without_toyyibpay(self):
        prepared_order = {
            "id": 88,
            "order_reference": self.valid_ref,
            "status": "pending",
            "gateway_order_id": None,
            "checkout_url": None,
        }
        callback_order = dict(self.mock_order)
        callback_order["amount_sen"] = 8900
        callback_order["new_plan_id"] = 20
        callback_order["gateway_order_id"] = f"DEV_TEST_PAYMENT:{self.valid_ref}"

        patches = self._patch_prepare_service_deps()
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
             patch("app.services.subscription_checkout_service.create_subscription_order", return_value=prepared_order), \
             patch("app.services.subscription_checkout_service.create_bill") as mock_bill, \
             patch("app.services.toyyibpay_service.requests.post") as toyyibpay_post:
            prepare_resp = self.client.post(
                "/api/billing/dev/subscription-orders/prepare",
                json={"plan_code": "advanced"},
                headers=self.headers,
            )

        self.assertEqual(prepare_resp.status_code, 201)
        mock_bill.assert_not_called()
        toyyibpay_post.assert_not_called()

        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_order(return_value=callback_order), \
             self._patch_update_status() as route_update, \
             patch(
                 "app.services.subscription_payment_callback_service._get_order_by_gateway",
                 return_value=callback_order,
             ), \
             patch("app.services.subscription_payment_callback_service._update_order_status") as callback_update, \
             patch("app.services.subscription_payment_callback_service._update_activation_state"), \
             patch("app.services.subscription_payment_callback_service._claim_activation_sequence"), \
             patch("app.services.subscription_payment_callback_service.get_plan_by_id", return_value=self._advanced_plan()), \
             patch("app.services.subscription_payment_callback_service.conditional_activate_subscription") as activate, \
             patch("app.services.subscription_payment_callback_service._ensure_company_ai_credit") as ensure_credit, \
             patch("app.services.subscription_payment_callback_service.convert_trial_ai_configuration"), \
             patch("app.services.billing_notification_service.notify_payment_confirmed"), \
             patch("app.services.billing_notification_service.notify_activation_completed"), \
             patch("app.services.toyyibpay_service.requests.post") as complete_toyyibpay_post:
            complete_resp = self.client.post(
                f"/api/billing/dev/subscription-orders/{self.valid_ref}/complete",
                headers=self.headers,
            )

        self.assertEqual(complete_resp.status_code, 200)
        self.assertEqual(json.loads(complete_resp.data)["result"]["status"], "activated_and_credited")
        route_update.assert_not_called()
        callback_update.assert_any_call(
            order_reference=self.valid_ref,
            status="paid",
            payment_reference="DEV_TEST_PAYMENT",
            paid_at=ANY,
        )
        callback_update.assert_any_call(
            order_reference=self.valid_ref,
            status="credited",
            credited_at=ANY,
        )
        activate.assert_called_once()
        ensure_credit.assert_called_once_with(42)
        complete_toyyibpay_post.assert_not_called()

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
