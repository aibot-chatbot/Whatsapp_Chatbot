"""test_subscription_payment_callback.py

Unit tests for subscription_payment_callback_service.py.
All repository and service calls are mocked; no Supabase, payment gateway,
or network access.
"""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import sys
sys.path.insert(0, r"C:\Users\User\PycharmProjects\python-whatsapp-bot-main")

import unittest
from unittest.mock import patch, MagicMock
import types

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

# Patch supabase at module level before any repo imports resolve
_sb = MagicMock()
_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
_sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
_sb.rpc.return_value.execute.return_value = MagicMock(data=[])
with patch("app.database.db.supabase", _sb):
    from app.services.subscription_payment_callback_service import (
        process_subscription_payment_callback,
    )
    from app.routes.toyyibpay_routes import (
        _is_subscription_callback,
    )


_SVC = "app.services.subscription_payment_callback_service"


class TestSubscriptionPaymentCallback(unittest.TestCase):
    """Tests for process_subscription_payment_callback()."""

    def setUp(self):
        self.valid_callback = {
            "payment_gateway": "toyyibpay",
            "gateway_order_id": "bill-001",
            "paid": True,
            "payment_reference": "txn-001",
            "amount_sen": 3900,
            "paid_at": "2026-07-08T12:00:00Z",
        }

        self.mock_order = {
            "id": 1,
            "order_reference": "abc-123",
            "company_id": 42,
            "subscription_id": 10,
            "new_plan_id": 20,
            "amount_sen": 3900,
            "status": "pending",
            "payment_gateway": "toyyibpay",
            "gateway_order_id": "bill-001",
            "payment_reference": None,
        }

        self.mock_plan = {
            "id": 20,
            "code": "essential",
            "included_ai_credit_micro_myr": 5000000,
            "name": "Essential",
        }

    @patch("app.database.company_subscription_order_repository.claim_subscription_billing_period")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".update_company_subscription")
    @patch(_SVC + "._add_included_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_successful_payment_activation(
        self, mock_convert, mock_update_status,
        mock_add_included_credit, mock_update_sub,
        mock_get_plan, mock_get_order, mock_claim_period,
    ):
        mock_get_order.return_value = self.mock_order
        mock_get_plan.return_value = self.mock_plan
        mock_update_sub.return_value = {"id": 10, "status": "active"}
        mock_update_status.return_value = {"id": 1, "status": "paid"}
        mock_add_included_credit.return_value = {"status": "applied", "transaction_id": 99}

        result = process_subscription_payment_callback(self.valid_callback)

        self.assertEqual(result["status"], "legacy_order_activated")
        self.assertEqual(result["order_reference"], "abc-123")
        self.assertEqual(result["company_id"], 42)
        self.assertEqual(result["plan_code"], "essential")
        self.assertFalse(result["idempotent"])

        mock_update_sub.assert_called_once()
        _, kwargs = mock_update_sub.call_args
        self.assertEqual(kwargs["subscription_id"], 10)
        self.assertEqual(kwargs["updates"]["status"], "active")
        self.assertIsNone(kwargs["updates"]["trial_ends_at"])

        mock_add_included_credit.assert_called_once()
        _, credit_kwargs = mock_add_included_credit.call_args
        self.assertEqual(credit_kwargs["company_id"], 42)
        self.assertEqual(credit_kwargs["amount_micro_myr"], 5000000)

        mock_convert.assert_called_once_with(42, "essential")

    @patch(_SVC + "._get_order_by_gateway")
    def test_duplicate_credited_callback(self, mock_get_order):
        credited_order = dict(self.mock_order)
        credited_order["status"] = "credited"
        credited_order["gateway_order_id"] = "bill-001"
        credited_order["payment_reference"] = "txn-001"
        mock_get_order.return_value = credited_order

        result = process_subscription_payment_callback(self.valid_callback)

        self.assertEqual(result["status"], "already_activated")
        self.assertTrue(result["idempotent"])
        self.assertEqual(result["order_status"], "credited")

    @patch(_SVC + "._get_order_by_gateway")
    def test_amount_mismatch_raises_error(self, mock_get_order):
        callback = dict(self.valid_callback)
        callback["amount_sen"] = 100
        mock_get_order.return_value = self.mock_order

        with self.assertRaises(ValueError) as ctx:
            process_subscription_payment_callback(callback)
        self.assertIn("less than order amount", str(ctx.exception))

    @patch(_SVC + "._get_order_by_gateway")
    def test_failed_status_rejected(self, mock_get_order):
        failed_order = dict(self.mock_order)
        failed_order["status"] = "failed"
        mock_get_order.return_value = failed_order

        with self.assertRaises(ValueError) as ctx:
            process_subscription_payment_callback(self.valid_callback)
        self.assertIn("cannot activate", str(ctx.exception))

    @patch(_SVC + "._get_order_by_gateway")
    def test_expired_status_rejected(self, mock_get_order):
        expired_order = dict(self.mock_order)
        expired_order["status"] = "expired"
        mock_get_order.return_value = expired_order

        with self.assertRaises(ValueError) as ctx:
            process_subscription_payment_callback(self.valid_callback)
        self.assertIn("cannot activate", str(ctx.exception))

    @patch(_SVC + "._get_order_by_gateway")
    def test_unpaid_callback_returns_not_paid(self, mock_get_order):
        callback = dict(self.valid_callback)
        callback["paid"] = False
        mock_get_order.return_value = self.mock_order

        result = process_subscription_payment_callback(callback)
        self.assertEqual(result["status"], "not_paid")

    @patch(_SVC + "._get_order_by_gateway")
    def test_order_not_found_raises_error(self, mock_get_order):
        mock_get_order.return_value = None

        with self.assertRaises(ValueError) as ctx:
            process_subscription_payment_callback(self.valid_callback)
        self.assertIn("subscription order found", str(ctx.exception))

    @patch(_SVC + "._get_order_by_gateway")
    def test_missing_payment_gateway_raises_error(self, mock_get_order):
        callback = dict(self.valid_callback)
        callback["payment_gateway"] = ""

        with self.assertRaises(ValueError) as ctx:
            process_subscription_payment_callback(callback)
        self.assertIn("payment_gateway", str(ctx.exception))

    @patch("app.database.company_subscription_order_repository.claim_subscription_billing_period")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".update_company_subscription")
    @patch(_SVC + "._add_included_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_trial_conversion_called(
        self, mock_convert, mock_update_status,
        mock_add_included_credit, mock_update_sub,
        mock_get_plan, mock_get_order, mock_claim_period,
    ):
        mock_get_order.return_value = self.mock_order
        mock_get_plan.return_value = self.mock_plan
        mock_update_sub.return_value = {"id": 10, "status": "active"}
        mock_update_status.return_value = {"id": 1, "status": "paid"}
        mock_add_included_credit.return_value = {"status": "applied", "transaction_id": 99}

        result = process_subscription_payment_callback(self.valid_callback)

        self.assertEqual(result["status"], "legacy_order_activated")
        mock_convert.assert_called_once_with(42, "essential")


class TestToyyibpayRouteDetection(unittest.TestCase):
    """Tests for _is_subscription_callback() and route dispatch."""

    def setUp(self):
        self.mock_order = {
            "id": 1,
            "order_reference": "abc-123",
            "payment_gateway": "toyyibpay",
            "gateway_order_id": "bill-sub-001",
        }

    @patch("app.routes.toyyibpay_routes.get_subscription_order_by_gateway_id")
    def test_detects_subscription_callback(self, mock_get_order):
        mock_get_order.return_value = self.mock_order
        result = _is_subscription_callback("toyyibpay", "bill-sub-001")
        self.assertTrue(result)

    @patch("app.routes.toyyibpay_routes.get_subscription_order_by_gateway_id")
    def test_detects_non_subscription_callback(self, mock_get_order):
        mock_get_order.return_value = None
        result = _is_subscription_callback("toyyibpay", "bill-topup-001")
        self.assertFalse(result)

    def test_empty_args_return_false(self):
        self.assertFalse(_is_subscription_callback("", ""))
        self.assertFalse(_is_subscription_callback(None, "bill-001"))
        self.assertFalse(_is_subscription_callback("toyyibpay", ""))


if __name__ == "__main__":
    unittest.main()
