"""Tests for the ToyyibPay callback HTTP route."""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("AI_CREDIT_ENFORCEMENT_ENABLED", "true")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("TOYYIBPAY_ENV", "sandbox")
os.environ.setdefault("TOYYIBPAY_USER_SECRET_KEY", "test-secret-key")
os.environ.setdefault("TOYYIBPAY_CATEGORY_CODE", "test-category")
os.environ.setdefault("TOYYIBPAY_CALLBACK_URL", "https://test.ngrok.app/api/billing/toyyibpay/callback")

import sys
sys.path.insert(0, r"C:\Users\User\PycharmProjects\python-whatsapp-bot-main")

import unittest
from unittest.mock import patch, MagicMock

import types

# Mock pre-existing broken dependencies before any app import
if 'google' not in sys.modules:
    _g = types.ModuleType('google')
    _g.genai = types.ModuleType('google.genai')
    _g.genai.Client = MagicMock()
    sys.modules['google'] = _g
    sys.modules['google.genai'] = _g.genai
if 'fitz' not in sys.modules:
    sys.modules['fitz'] = types.ModuleType('fitz')
if 'tools' not in sys.modules:
    sys.modules['tools'] = types.ModuleType('tools')
if '_tools' not in sys.modules:
    sys.modules['_tools'] = types.ModuleType('_tools')

with patch("app.database.db.supabase", MagicMock()):
    from app import create_app


class TestToyyibPayRoutes(unittest.TestCase):

    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

        self.valid_payload = {
            "billcode": "BC123",
            "order_id": "11111111-1111-4111-8111-111111111111",
            "refno": "REF123",
            "status": "1",
            "amount": "100",
            "transaction_time": "2026-07-30 12:05:00",
            "reason": "",
            "hash": "test-hash",
        }

    @staticmethod
    def _patch_hash(return_value=True, side_effect=None):
        return patch(
            "app.routes.toyyibpay_routes.verify_callback_hash",
            return_value=return_value,
            side_effect=side_effect,
        )

    @staticmethod
    def _patch_parse(return_value=None, side_effect=None):
        if return_value is None:
            return_value = {
                "payment_gateway": "toyyibpay",
                "gateway_order_id": "BC123",
                "order_reference": "11111111-1111-4111-8111-111111111111",
                "payment_reference": "REF123",
                "paid": True,
                "gateway_status": "1",
                "amount_sen": 100,
                "paid_at": "2026-07-30 12:05:00",
                "failure_reason": None,
            }
        return patch(
            "app.routes.toyyibpay_routes.parse_verified_callback",
            return_value=return_value,
            side_effect=side_effect,
        )

    @staticmethod
    def _patch_process(return_value=None, side_effect=None):
        if return_value is None:
            return_value = {
                "status": "credited",
                "idempotent": False,
                "order_reference": "11111111-1111-4111-8111-111111111111",
                "order_status": "credited",
                "credit_transaction_id": 500,
                "company_id": 1,
                "amount_micro_myr": 1_000_000,
            }
        return patch(
            "app.routes.toyyibpay_routes.process_topup_payment_callback",
            return_value=return_value,
            side_effect=side_effect,
        )

    def test_valid_callback_returns_200(self):
        with self._patch_hash(), self._patch_parse(), self._patch_process():
            resp = self.client.post(
                "/api/billing/toyyibpay/callback",
                data=self.valid_payload,
            )
            self.assertEqual(resp.status_code, 200)

    def test_idempotent_replay_returns_200(self):
        with self._patch_hash(), self._patch_parse(), self._patch_process(
            return_value={
                "status": "already_credited",
                "idempotent": True,
            }
        ):
            resp = self.client.post(
                "/api/billing/toyyibpay/callback",
                data=self.valid_payload,
            )
            self.assertEqual(resp.status_code, 200)

    def test_invalid_hash_returns_400(self):
        with self._patch_hash(return_value=False) as mock_verify, \
             self._patch_parse() as mock_parse, \
             self._patch_process() as mock_process:
            resp = self.client.post(
                "/api/billing/toyyibpay/callback",
                data=self.valid_payload,
            )
            self.assertEqual(resp.status_code, 400)
            mock_parse.assert_not_called()
            mock_process.assert_not_called()

    def test_parse_error_returns_400(self):
        with self._patch_hash(), \
             self._patch_parse(side_effect=ValueError("bad")) as mock_parse, \
             self._patch_process() as mock_process:
            resp = self.client.post(
                "/api/billing/toyyibpay/callback",
                data=self.valid_payload,
            )
            self.assertEqual(resp.status_code, 400)
            mock_process.assert_not_called()

    def test_process_value_error_returns_400(self):
        with self._patch_hash(), self._patch_parse(), \
             self._patch_process(side_effect=ValueError("Unpaid")):
            resp = self.client.post(
                "/api/billing/toyyibpay/callback",
                data=self.valid_payload,
            )
            self.assertEqual(resp.status_code, 400)

    def test_process_runtime_error_returns_500(self):
        with self._patch_hash(), self._patch_parse(), \
             self._patch_process(side_effect=RuntimeError("DB failure")):
            resp = self.client.post(
                "/api/billing/toyyibpay/callback",
                data=self.valid_payload,
            )
            self.assertEqual(resp.status_code, 500)

    def test_success_response_minimal(self):
        with self._patch_hash(), self._patch_parse(), self._patch_process():
            resp = self.client.post(
                "/api/billing/toyyibpay/callback",
                data=self.valid_payload,
            )
            data = resp.get_json()
            self.assertEqual(set(data.keys()), {"status"})

    def test_route_registered(self):
        with self._patch_hash(), self._patch_parse(), self._patch_process():
            resp = self.client.post(
                "/api/billing/toyyibpay/callback",
                data=self.valid_payload,
            )
            self.assertNotEqual(resp.status_code, 404)
            self.assertNotEqual(resp.status_code, 405)

    def test_empty_form_returns_400(self):
        resp = self.client.post("/api/billing/toyyibpay/callback", data={})
        self.assertEqual(resp.status_code, 400)

    def test_hash_value_error_returns_400(self):
        with self._patch_hash(side_effect=ValueError("Missing")) as mock_verify, \
             self._patch_parse() as mock_parse, \
             self._patch_process() as mock_process:
            resp = self.client.post(
                "/api/billing/toyyibpay/callback",
                data=self.valid_payload,
            )
            self.assertEqual(resp.status_code, 400)
            mock_parse.assert_not_called()

    def test_config_error_returns_500(self):
        from app.services.toyyibpay_service import ToyyibPayConfigError
        with self._patch_hash(
            side_effect=ToyyibPayConfigError("Missing")), \
             self._patch_parse() as mock_parse, \
             self._patch_process() as mock_process:
            resp = self.client.post(
                "/api/billing/toyyibpay/callback",
                data=self.valid_payload,
            )
            self.assertEqual(resp.status_code, 500)
            mock_parse.assert_not_called()

    def test_unexpected_exception_returns_500(self):
        with self._patch_hash(side_effect=Exception("Crash")), \
             self._patch_parse() as mock_parse, \
             self._patch_process() as mock_process:
            resp = self.client.post(
                "/api/billing/toyyibpay/callback",
                data=self.valid_payload,
            )
            self.assertEqual(resp.status_code, 500)
            mock_parse.assert_not_called()

    def test_get_returns_405(self):
        resp = self.client.get("/api/billing/toyyibpay/callback")
        self.assertEqual(resp.status_code, 405)

    def test_get_trailing_slash_returns_404(self):
        resp = self.client.get("/api/billing/toyyibpay/callback/")
        self.assertEqual(resp.status_code, 404)

    def test_get_unknown_api_path_returns_404(self):
        resp = self.client.get("/api/completely-unknown-route")
        self.assertEqual(resp.status_code, 404)

    def test_post_callback_reaches_handler(self):
        with self._patch_hash(), self._patch_parse(), self._patch_process():
            resp = self.client.post(
                "/api/billing/toyyibpay/callback",
                data=self.valid_payload,
            )
            self.assertEqual(resp.status_code, 200)

