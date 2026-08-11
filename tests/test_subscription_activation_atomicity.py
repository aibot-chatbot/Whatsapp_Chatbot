"""test_subscription_activation_atomicity.py

Focused unit tests for Phase 4B callback atomicity improvements.

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
_CSO_REPO = "app.database.company_subscription_order_repository"


class TestSubscriptionActivationAtomicity(unittest.TestCase):

    def setUp(self):
        self.valid_callback = {
            "payment_gateway": "toyyibpay",
            "gateway_order_id": "bill-001",
            "paid": True,
            "payment_reference": "txn-001",
            "amount_sen": 3900,
            "paid_at": "2026-07-08T12:00:00Z",
        }

        self.order_with_key = {
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
            "source_plan_id": 15,
            "source_period_start": "2026-06-08T12:00:00Z",
            "source_period_end": "2026-07-08T12:00:00Z",
            "source_status": "active",
            "activation_type": "upgrade",
            "activation_sequence_key": "company:42:upgrade-from:15:period:2026-06-08T12:00:00Z",
        }

        self.mock_plan = {
            "id": 20,
            "code": "essential",
            "billing_interval": "monthly",
            "included_ai_credit_micro_myr": 5000000,
            "name": "Essential",
        }

    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".conditional_activate_subscription")
    @patch(_SVC + "._add_included_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_first_order_activates_then_second_is_rejected(
        self, mock_convert, mock_update_status,
        mock_add_included_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
    ):
        mock_get_order.return_value = self.order_with_key
        mock_get_plan.return_value = self.mock_plan
        mock_cond_activate.return_value = {"id": 10, "status": "active"}
        mock_update_status.return_value = {"id": 1, "status": "credited"}
        mock_add_included_credit.return_value = {"status": "applied", "transaction_id": 99}

        result1 = process_subscription_payment_callback(self.valid_callback)
        self.assertEqual(result1["status"], "activated_and_credited")
        mock_claim_seq.assert_called_once()
        _, cond_kwargs = mock_cond_activate.call_args
        from app.services.billing_period_service import calculate_current_period_end
        period_start = cond_kwargs["period_start_iso"]
        expected_end = calculate_current_period_end(period_start, "monthly").isoformat()
        self.assertEqual(cond_kwargs["period_end_iso"], expected_end)

        mock_claim_seq.reset_mock()
        mock_claim_seq.side_effect = RuntimeError("Already claimed by another order")

        second_order = dict(self.order_with_key)
        second_order["order_reference"] = "abc-456"
        second_order["gateway_order_id"] = "bill-002"
        mock_get_order.return_value = second_order

        second_callback = dict(self.valid_callback)
        second_callback["gateway_order_id"] = "bill-002"
        second_callback["payment_reference"] = "txn-002"

        result2 = process_subscription_payment_callback(second_callback)
        self.assertEqual(result2["status"], "activation_already_claimed")
        self.assertTrue(result2["idempotent"])
        mock_cond_activate.assert_called_once()

    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".conditional_activate_subscription")
    @patch(_SVC + "._add_included_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_repeated_same_order_callback_is_idempotent(
        self, mock_convert, mock_update_status,
        mock_add_included_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
    ):
        mock_get_order.return_value = self.order_with_key
        mock_get_plan.return_value = self.mock_plan
        mock_cond_activate.return_value = {"id": 10, "status": "active"}
        mock_update_status.return_value = {"id": 1, "status": "credited"}
        mock_add_included_credit.return_value = {"status": "applied", "transaction_id": 99}

        result1 = process_subscription_payment_callback(self.valid_callback)
        self.assertEqual(result1["status"], "activated_and_credited")

        credited_order = dict(self.order_with_key)
        credited_order["status"] = "credited"
        credited_order["gateway_order_id"] = "bill-001"
        credited_order["payment_reference"] = "txn-001"
        mock_get_order.return_value = credited_order

        result2 = process_subscription_payment_callback(self.valid_callback)
        self.assertEqual(result2["status"], "already_activated")
        self.assertTrue(result2["idempotent"])

    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".conditional_activate_subscription")
    @patch(_SVC + "._add_included_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_source_subscription_changed_rejected(
        self, mock_convert, mock_update_status,
        mock_add_included_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
    ):
        mock_get_order.return_value = self.order_with_key
        mock_get_plan.return_value = self.mock_plan
        mock_cond_activate.side_effect = ValueError(
            "Subscription source state mismatch: expected plan=15, status=active"
        )

        with self.assertRaises(RuntimeError) as ctx:
            process_subscription_payment_callback(self.valid_callback)
        self.assertIn("source subscription state", str(ctx.exception).lower())

    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".conditional_activate_subscription")
    @patch(_SVC + "._add_included_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_only_one_credit_allocation(
        self, mock_convert, mock_update_status,
        mock_add_included_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
    ):
        mock_get_order.return_value = self.order_with_key
        mock_get_plan.return_value = self.mock_plan
        mock_cond_activate.return_value = {"id": 10, "status": "active"}
        mock_update_status.return_value = {"id": 1, "status": "credited"}
        mock_add_included_credit.return_value = {"status": "applied", "transaction_id": 99}

        process_subscription_payment_callback(self.valid_callback)
        self.assertEqual(mock_add_included_credit.call_count, 1)
        _, credit_kwargs = mock_add_included_credit.call_args
        self.assertIn("company:42:upgrade-from", credit_kwargs.get("idempotency_key", ""))
        self.assertEqual(credit_kwargs["amount_micro_myr"], 5000000)

    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".update_company_subscription")
    @patch(_SVC + "._add_included_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_legacy_order_without_activation_key_succeeds(
        self, mock_convert, mock_update_status,
        mock_add_included_credit, mock_update_sub,
        mock_get_plan, mock_get_order,
    ):
        legacy_order = {
            "id": 99, "order_reference": "legacy-001",
            "company_id": 42, "subscription_id": 10,
            "new_plan_id": 20, "amount_sen": 3900,
            "status": "pending", "payment_gateway": "toyyibpay",
            "gateway_order_id": "bill-legacy", "payment_reference": None,
        }
        mock_get_order.return_value = legacy_order
        mock_get_plan.return_value = self.mock_plan
        mock_update_sub.return_value = {"id": 10, "status": "active"}
        mock_update_status.return_value = {"id": 1, "status": "paid"}
        mock_add_included_credit.return_value = {"status": "applied", "transaction_id": 99}

        callback = dict(self.valid_callback)
        callback["gateway_order_id"] = "bill-legacy"
        callback["payment_reference"] = "txn-legacy"

        result = process_subscription_payment_callback(callback)
        self.assertEqual(result["status"], "legacy_order_activated")
        self.assertEqual(result["order_reference"], "legacy-001")
        _, kwargs = mock_update_sub.call_args
        from app.services.billing_period_service import calculate_current_period_end
        period_start = kwargs["updates"]["current_period_start"]
        expected_end = calculate_current_period_end(period_start, "monthly").isoformat()
        self.assertEqual(kwargs["updates"]["current_period_end"], expected_end)

    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".conditional_activate_subscription")
    @patch(_SVC + "._add_included_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_renewal_with_different_key_succeeds_after_expiry(
        self, mock_convert, mock_update_status,
        mock_add_included_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
    ):
        renewal_order = dict(self.order_with_key)
        renewal_order["order_reference"] = "renewal-001"
        renewal_order["gateway_order_id"] = "bill-renewal"
        renewal_order["activation_type"] = "renewal"
        renewal_order["activation_sequence_key"] = "company:42:renewal-after:2026-07-08T12:00:00Z"

        mock_get_order.return_value = renewal_order
        mock_get_plan.return_value = self.mock_plan
        mock_cond_activate.return_value = {"id": 10, "status": "active"}
        mock_update_status.return_value = {"id": 1, "status": "credited"}
        mock_add_included_credit.return_value = {"status": "applied", "transaction_id": 99}

        callback = dict(self.valid_callback)
        callback["gateway_order_id"] = "bill-renewal"
        callback["payment_reference"] = "txn-renewal"

        result = process_subscription_payment_callback(callback)
        self.assertEqual(result["status"], "activated_and_credited")
        self.assertEqual(result["order_reference"], "renewal-001")

    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".conditional_activate_subscription")
    @patch(_SVC + "._add_included_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_topup_balance_preserved_during_credit_grant(
        self, mock_convert, mock_update_status,
        mock_add_included_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
    ):
        mock_get_order.return_value = self.order_with_key
        mock_get_plan.return_value = self.mock_plan
        mock_cond_activate.return_value = {"id": 10, "status": "active"}
        mock_update_status.return_value = {"id": 1, "status": "credited"}
        mock_add_included_credit.return_value = {"status": "applied", "transaction_id": 99}

        result = process_subscription_payment_callback(self.valid_callback)
        self.assertEqual(result["status"], "activated_and_credited")
        mock_add_included_credit.assert_called_once()

# ------------------------------------------------------------------#
    # Schema-version tests (Phase 4B close)
    # ------------------------------------------------------------------#

    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".update_company_subscription")
    @patch(_SVC + "._add_included_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_version_null_historical_uses_legacy_path(
        self, mock_convert, mock_update_status,
        mock_add_included_credit, mock_update_sub,
        mock_get_plan, mock_get_order,
    ):
        """Historical order (schema_version=NULL) uses legacy fallback."""
        historical_order = {
            "id": 50, "order_reference": "hist-001",
            "company_id": 42, "subscription_id": 10,
            "new_plan_id": 20, "amount_sen": 3900,
            "status": "pending", "payment_gateway": "toyyibpay",
            "gateway_order_id": "bill-hist", "payment_reference": None,
            "order_schema_version": None,
        }
        mock_get_order.return_value = historical_order
        mock_get_plan.return_value = self.mock_plan
        mock_update_sub.return_value = {"id": 10, "status": "active"}
        mock_update_status.return_value = {"id": 1, "status": "paid"}
        mock_add_included_credit.return_value = {"status": "applied", "transaction_id": 99}

        callback = dict(self.valid_callback)
        callback["gateway_order_id"] = "bill-hist"
        callback["payment_reference"] = "txn-hist"

        result = process_subscription_payment_callback(callback)
        self.assertEqual(result["status"], "legacy_order_activated")
        self.assertTrue(result.get("legacy_activation", False))

    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + "._add_included_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_version_2_missing_source_fields_fails_closed(
        self, mock_convert, mock_update_status,
        mock_add_included_credit,
        mock_get_plan, mock_get_order, mock_claim_seq,
    ):
        """Version 2 order missing source fields returns malformed_atomic_order."""
        malformed_order = {
            "id": 51, "order_reference": "malformed-001",
            "company_id": 42, "subscription_id": 10,
            "new_plan_id": 20, "amount_sen": 3900,
            "status": "pending", "payment_gateway": "toyyibpay",
            "gateway_order_id": "bill-mal", "payment_reference": None,
            "order_schema_version": 2,
            "source_plan_id": None,
            "source_period_start": None,
            "source_period_end": None,
            "source_status": None,
            "activation_type": "renewal",
            "activation_sequence_key": "company:42:renewal-after:2026-07-08",
        }
        mock_get_order.return_value = malformed_order
        mock_get_plan.return_value = self.mock_plan

        result = process_subscription_payment_callback(self.valid_callback.copy())
        # Update gateway_order_id in callback
        malformed_callback = dict(self.valid_callback)
        malformed_callback["gateway_order_id"] = "bill-mal"
        malformed_callback["payment_reference"] = "txn-mal"

        result = process_subscription_payment_callback(malformed_callback)
        self.assertEqual(result["status"], "malformed_atomic_order")
        self.assertTrue(result["idempotent"])

    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + "._add_included_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_unsupported_schema_version_fails_closed(
        self, mock_convert, mock_update_status,
        mock_add_included_credit,
        mock_get_plan, mock_get_order, mock_claim_seq,
    ):
        """Unknown schema version returns unsupported_order_schema_version."""
        bad_version_order = {
            "id": 52, "order_reference": "badver-001",
            "company_id": 42, "subscription_id": 10,
            "new_plan_id": 20, "amount_sen": 3900,
            "status": "pending", "payment_gateway": "toyyibpay",
            "gateway_order_id": "bill-badver", "payment_reference": None,
            "order_schema_version": 999,
            "source_plan_id": 15,
            "source_status": "active",
            "activation_type": "upgrade",
            "activation_sequence_key": "company:42:upgrade-from:15",
        }
        mock_get_order.return_value = bad_version_order
        mock_get_plan.return_value = self.mock_plan

        bad_callback = dict(self.valid_callback)
        bad_callback["gateway_order_id"] = "bill-badver"
        bad_callback["payment_reference"] = "txn-badver"

        result = process_subscription_payment_callback(bad_callback)
        self.assertEqual(result["status"], "unsupported_order_schema_version")
        self.assertTrue(result["idempotent"])

    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + "._add_included_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_credited_historical_order_remains_idempotent(
        self, mock_convert, mock_update_status,
        mock_add_included_credit,
        mock_get_plan, mock_get_order,
    ):
        """Historical credited order still returns already_activated."""
        credited_historical = {
            "id": 53, "order_reference": "credit-hist",
            "company_id": 42, "subscription_id": 10,
            "new_plan_id": 20, "amount_sen": 3900,
            "status": "credited", "payment_gateway": "toyyibpay",
            "gateway_order_id": "bill-credhist", "payment_reference": "txn-credhist",
            "order_schema_version": None,
        }
        mock_get_order.return_value = credited_historical
        mock_get_plan.return_value = self.mock_plan

        cred_callback = dict(self.valid_callback)
        cred_callback["gateway_order_id"] = "bill-credhist"
        cred_callback["payment_reference"] = "txn-credhist"

        result = process_subscription_payment_callback(cred_callback)
        self.assertEqual(result["status"], "already_activated")
        self.assertTrue(result["idempotent"])
