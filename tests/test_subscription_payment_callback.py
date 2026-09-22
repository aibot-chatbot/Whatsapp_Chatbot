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
import pathlib
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

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


_SVC = "app.services.subscription_payment_callback_service"


class TestSubscriptionPaymentCallback(unittest.TestCase):
    """Tests for process_subscription_payment_callback()."""

    def setUp(self):
        self.valid_callback = {
            "payment_gateway": "toyyibpay",
            "gateway_order_id": "bill-001",
            # The gateway-signed order id. The handler cross-checks it against
            # the order it finds by gateway_order_id, so it must match
            # mock_order["order_reference"] below.
            "order_reference": "abc-123",
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
            "billing_interval": "monthly",
            "included_ai_credit_micro_myr": 5000000,
            "name": "Essential",
        }

    @patch("app.database.company_subscription_order_repository.claim_subscription_billing_period")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".update_company_subscription")
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_successful_payment_activation(
        self, mock_convert, mock_update_status,
        mock_ensure_company_ai_credit, mock_update_sub,
        mock_get_plan, mock_get_order, mock_claim_period,
    ):
        mock_get_order.return_value = self.mock_order
        mock_get_plan.return_value = self.mock_plan
        mock_update_sub.return_value = {"id": 10, "status": "active"}
        mock_update_status.return_value = {"id": 1, "status": "paid"}
        mock_ensure_company_ai_credit.return_value = {
            "status": "ensured",
            "period_changed": True,
            "included_credit_granted_micro_myr": 5000000,
        }

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
        from app.services.billing_period_service import calculate_current_period_end
        period_start = kwargs["updates"]["current_period_start"]
        expected_end = calculate_current_period_end(period_start, "monthly").isoformat()
        self.assertEqual(kwargs["updates"]["current_period_end"], expected_end)

        mock_ensure_company_ai_credit.assert_called_once_with(42)

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
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_trial_conversion_called(
        self, mock_convert, mock_update_status,
        mock_ensure_company_ai_credit, mock_update_sub,
        mock_get_plan, mock_get_order, mock_claim_period,
    ):
        mock_get_order.return_value = self.mock_order
        mock_get_plan.return_value = self.mock_plan
        mock_update_sub.return_value = {"id": 10, "status": "active"}
        mock_update_status.return_value = {"id": 1, "status": "paid"}
        mock_ensure_company_ai_credit.return_value = {
            "status": "ensured",
            "period_changed": True,
            "included_credit_granted_micro_myr": 5000000,
        }

        result = process_subscription_payment_callback(self.valid_callback)

        self.assertEqual(result["status"], "legacy_order_activated")
        mock_convert.assert_called_once_with(42, "essential")
        _, kwargs = mock_update_sub.call_args
        from app.services.billing_period_service import calculate_current_period_end
        period_start = kwargs["updates"]["current_period_start"]
        expected_end = calculate_current_period_end(period_start, "monthly").isoformat()
        self.assertEqual(kwargs["updates"]["current_period_end"], expected_end)

    @patch("app.database.company_subscription_order_repository.claim_subscription_billing_period")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".update_company_subscription")
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_activation_state")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_credit_grant_failure_leaves_paid_credit_pending_not_credited(
        self, mock_convert, mock_update_status, mock_update_activation_state,
        mock_ensure_company_ai_credit, mock_update_sub,
        mock_get_plan, mock_get_order, mock_claim_period,
    ):
        mock_get_order.return_value = self.mock_order
        mock_get_plan.return_value = self.mock_plan
        mock_update_sub.return_value = {"id": 10, "status": "active"}
        mock_update_status.return_value = {"id": 1, "status": "paid"}
        mock_ensure_company_ai_credit.side_effect = RuntimeError(
            "invalid input value for transaction_type subscription_included"
        )

        result = process_subscription_payment_callback(self.valid_callback)

        self.assertEqual(result["status"], "activation_credit_pending")
        self.assertEqual(result["order_status"], "paid")
        mock_update_sub.assert_called_once()
        mock_ensure_company_ai_credit.assert_called_once_with(42)
        mock_convert.assert_not_called()
        mock_update_status.assert_any_call(
            order_reference="abc-123",
            status="paid",
            payment_reference="txn-001",
            paid_at="2026-07-08T12:00:00Z",
        )
        credited_calls = [
            call for call in mock_update_status.call_args_list
            if call.kwargs.get("status") == "credited"
        ]
        self.assertEqual(credited_calls, [])
        self.assertTrue(any(
            call.kwargs.get("activation_status") == "credit_pending"
            and call.kwargs.get("activation_error_code") == "credit_grant_failed"
            and call.kwargs.get("reconciliation_required") is True
            for call in mock_update_activation_state.call_args_list
        ))

    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".conditional_activate_subscription")
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_activation_state")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_free_trial_to_advanced_uses_authoritative_advanced_credit_period(
        self, mock_convert, mock_update_status, mock_update_activation_state,
        mock_ensure_company_ai_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
    ):
        advanced_order = dict(self.mock_order)
        advanced_order.update({
            "new_plan_id": 7,
            "amount_sen": 8900,
            "source_plan_id": 1,
            "source_period_start": "2026-08-12T03:07:02.646645+00:00",
            "source_period_end": "2026-08-19T03:07:02.646645+00:00",
            "source_status": "trial",
            "activation_type": "initial",
            "activation_sequence_key": (
                "company:42:initial-from:10:trial:"
                "2026-08-19T03:07:02.646645+00:00"
            ),
            "order_schema_version": 2,
        })
        advanced_plan = {
            "id": 7,
            "code": "advanced",
            "billing_interval": "monthly",
            "included_ai_credit_micro_myr": 20000000,
            "name": "Advanced",
        }
        callback = dict(self.valid_callback)
        callback["amount_sen"] = 8900

        mock_get_order.return_value = advanced_order
        mock_get_plan.return_value = advanced_plan
        mock_cond_activate.return_value = {"id": 10, "status": "active", "plan_id": 7}
        mock_update_status.return_value = {"id": 1, "status": "credited"}
        mock_ensure_company_ai_credit.return_value = {
            "status": "ensured",
            "period_changed": True,
            "included_credit_granted_micro_myr": 20000000,
            "topup_balance_micro_myr": 0,
        }

        result = process_subscription_payment_callback(callback)

        self.assertEqual(result["status"], "activated_and_credited")
        self.assertEqual(result["plan_code"], "advanced")
        mock_cond_activate.assert_called_once()
        _, activate_kwargs = mock_cond_activate.call_args
        self.assertEqual(activate_kwargs["target_plan_id"], 7)
        self.assertEqual(activate_kwargs["expected_status"], "trial")
        mock_ensure_company_ai_credit.assert_called_once_with(42)
        mock_convert.assert_called_once_with(42, "advanced")
        mock_update_status.assert_any_call(
            order_reference="abc-123",
            status="credited",
            credited_at="2026-07-08T12:00:00Z",
        )
        self.assertTrue(any(
            call.kwargs.get("activation_status") == "completed"
            and call.kwargs.get("reconciliation_required") is False
            for call in mock_update_activation_state.call_args_list
        ))


    @patch(_SVC + "._get_order_by_gateway")
    def test_callback_for_a_different_order_is_rejected(self, mock_get_order):
        """A genuine callback must not be able to activate someone else's order.

        ToyyibPay signs status, order_id and refno - but NOT billcode. The order
        is located by billcode, so without comparing the signed order_id to the
        order that was found, a valid callback paired with another order's
        billcode activates the wrong subscription.
        """
        mock_get_order.return_value = self.mock_order  # order_reference "abc-123"

        hostile = dict(self.valid_callback)
        hostile["order_reference"] = "some-other-order"

        with self.assertRaises(ValueError) as ctx:
            process_subscription_payment_callback(hostile)
        self.assertIn("does not match", str(ctx.exception))

    @patch(_SVC + "._get_order_by_gateway")
    def test_callback_without_order_reference_is_rejected(self, mock_get_order):
        """The signed order id is mandatory; a callback lacking it cannot be trusted."""
        mock_get_order.return_value = self.mock_order

        incomplete = dict(self.valid_callback)
        incomplete.pop("order_reference")

        with self.assertRaises(ValueError) as ctx:
            process_subscription_payment_callback(incomplete)
        self.assertIn("order_reference", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
