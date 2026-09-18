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
            # The gateway-signed order id, cross-checked against the order
            # found by gateway_order_id. Must track order_reference below.
            "order_reference": "abc-123",
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
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_first_order_activates_then_second_is_rejected(
        self, mock_convert, mock_update_status,
        mock_ensure_company_ai_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
    ):
        mock_get_order.return_value = self.order_with_key
        mock_get_plan.return_value = self.mock_plan
        mock_cond_activate.return_value = {"id": 10, "status": "active"}
        mock_update_status.return_value = {"id": 1, "status": "credited"}
        mock_ensure_company_ai_credit.return_value = {"status": "applied", "transaction_id": 99}

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
        second_callback["order_reference"] = "abc-456"
        second_callback["payment_reference"] = "txn-002"

        result2 = process_subscription_payment_callback(second_callback)
        self.assertEqual(result2["status"], "activation_already_claimed")
        self.assertTrue(result2["idempotent"])
        mock_cond_activate.assert_called_once()

    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".conditional_activate_subscription")
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_repeated_same_order_callback_is_idempotent(
        self, mock_convert, mock_update_status,
        mock_ensure_company_ai_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
    ):
        mock_get_order.return_value = self.order_with_key
        mock_get_plan.return_value = self.mock_plan
        mock_cond_activate.return_value = {"id": 10, "status": "active"}
        mock_update_status.return_value = {"id": 1, "status": "credited"}
        mock_ensure_company_ai_credit.return_value = {"status": "applied", "transaction_id": 99}

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
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_source_subscription_changed_rejected(
        self, mock_convert, mock_update_status,
        mock_ensure_company_ai_credit, mock_cond_activate,
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
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_null_period_recovery_requires_current_subscription_null_period(
        self, mock_convert, mock_update_status,
        mock_ensure_company_ai_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
    ):
        recovery_order = dict(self.order_with_key)
        recovery_order.update({
            "order_schema_version": 2,
            "activation_type": "renewal",
            "source_period_end": None,
            "activation_sequence_key": "company:42:renewal-after:null-period-end",
        })
        mock_get_order.return_value = recovery_order
        mock_get_plan.return_value = self.mock_plan
        mock_cond_activate.return_value = {"id": 10, "status": "active"}
        mock_update_status.return_value = {"id": 1, "status": "credited"}
        mock_ensure_company_ai_credit.return_value = {"status": "applied", "transaction_id": 99}

        result = process_subscription_payment_callback(self.valid_callback)

        self.assertEqual(result["status"], "activated_and_credited")
        _, cond_kwargs = mock_cond_activate.call_args
        self.assertIsNone(cond_kwargs["expected_period_end"])
        self.assertTrue(cond_kwargs["expected_period_end_is_null"])

    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".conditional_activate_subscription")
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_null_period_recovery_rejects_stale_callback_after_period_changes(
        self, mock_convert, mock_update_status,
        mock_ensure_company_ai_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
    ):
        recovery_order = dict(self.order_with_key)
        recovery_order.update({
            "order_schema_version": 2,
            "activation_type": "renewal",
            "source_period_end": None,
            "activation_sequence_key": "company:42:renewal-after:null-period-end",
        })
        mock_get_order.return_value = recovery_order
        mock_get_plan.return_value = self.mock_plan
        mock_cond_activate.side_effect = ValueError(
            "Subscription source state mismatch: expected period_end=None; actual period_end=2026-08-01"
        )

        with self.assertRaises(RuntimeError) as ctx:
            process_subscription_payment_callback(self.valid_callback)

        self.assertIn("source subscription state", str(ctx.exception).lower())
        _, cond_kwargs = mock_cond_activate.call_args
        self.assertTrue(cond_kwargs["expected_period_end_is_null"])

    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".conditional_activate_subscription")
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_version_2_null_period_renewal_without_marker_fails_closed(
        self, mock_convert, mock_update_status,
        mock_ensure_company_ai_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
    ):
        malformed_order = dict(self.order_with_key)
        malformed_order.update({
            "order_schema_version": 2,
            "activation_type": "renewal",
            "source_period_end": None,
            "activation_sequence_key": "company:42:renewal-after:None",
        })
        mock_get_order.return_value = malformed_order
        mock_get_plan.return_value = self.mock_plan

        result = process_subscription_payment_callback(self.valid_callback)

        self.assertEqual(result["status"], "malformed_atomic_order")
        mock_cond_activate.assert_not_called()

    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".conditional_activate_subscription")
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_only_one_credit_allocation(
        self, mock_convert, mock_update_status,
        mock_ensure_company_ai_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
    ):
        mock_get_order.return_value = self.order_with_key
        mock_get_plan.return_value = self.mock_plan
        mock_cond_activate.return_value = {"id": 10, "status": "active"}
        mock_update_status.return_value = {"id": 1, "status": "credited"}
        mock_ensure_company_ai_credit.return_value = {"status": "applied", "transaction_id": 99}

        process_subscription_payment_callback(self.valid_callback)
        mock_ensure_company_ai_credit.assert_called_once_with(42)

    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".update_company_subscription")
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_legacy_order_without_activation_key_succeeds(
        self, mock_convert, mock_update_status,
        mock_ensure_company_ai_credit, mock_update_sub,
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
        mock_ensure_company_ai_credit.return_value = {"status": "applied", "transaction_id": 99}

        callback = dict(self.valid_callback)
        callback["gateway_order_id"] = "bill-legacy"
        callback["order_reference"] = "legacy-001"
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
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_renewal_with_different_key_succeeds_after_expiry(
        self, mock_convert, mock_update_status,
        mock_ensure_company_ai_credit, mock_cond_activate,
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
        mock_ensure_company_ai_credit.return_value = {"status": "applied", "transaction_id": 99}

        callback = dict(self.valid_callback)
        callback["gateway_order_id"] = "bill-renewal"
        callback["order_reference"] = "renewal-001"
        callback["payment_reference"] = "txn-renewal"

        result = process_subscription_payment_callback(callback)
        self.assertEqual(result["status"], "activated_and_credited")
        self.assertEqual(result["order_reference"], "renewal-001")

    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".conditional_activate_subscription")
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_topup_balance_preserved_during_credit_grant(
        self, mock_convert, mock_update_status,
        mock_ensure_company_ai_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
    ):
        mock_get_order.return_value = self.order_with_key
        mock_get_plan.return_value = self.mock_plan
        mock_cond_activate.return_value = {"id": 10, "status": "active"}
        mock_update_status.return_value = {"id": 1, "status": "credited"}
        mock_ensure_company_ai_credit.return_value = {"status": "applied", "transaction_id": 99}

        result = process_subscription_payment_callback(self.valid_callback)
        self.assertEqual(result["status"], "activated_and_credited")
        mock_ensure_company_ai_credit.assert_called_once()

# ------------------------------------------------------------------#
    # Schema-version tests (Phase 4B close)
    # ------------------------------------------------------------------#

    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".update_company_subscription")
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_version_null_historical_uses_legacy_path(
        self, mock_convert, mock_update_status,
        mock_ensure_company_ai_credit, mock_update_sub,
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
        mock_ensure_company_ai_credit.return_value = {"status": "applied", "transaction_id": 99}

        callback = dict(self.valid_callback)
        callback["gateway_order_id"] = "bill-hist"
        callback["order_reference"] = "hist-001"
        callback["payment_reference"] = "txn-hist"

        result = process_subscription_payment_callback(callback)
        self.assertEqual(result["status"], "legacy_order_activated")
        self.assertTrue(result.get("legacy_activation", False))

    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_version_2_missing_source_fields_fails_closed(
        self, mock_convert, mock_update_status,
        mock_ensure_company_ai_credit,
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

        # Point the callback at the malformed order. (An earlier call here used
        # self.valid_callback, whose result was immediately overwritten by the
        # one below and never asserted on - dead code, removed.)
        malformed_callback = dict(self.valid_callback)
        malformed_callback["gateway_order_id"] = "bill-mal"
        malformed_callback["order_reference"] = "malformed-001"
        malformed_callback["payment_reference"] = "txn-mal"

        result = process_subscription_payment_callback(malformed_callback)
        self.assertEqual(result["status"], "malformed_atomic_order")
        self.assertTrue(result["idempotent"])

    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_unsupported_schema_version_fails_closed(
        self, mock_convert, mock_update_status,
        mock_ensure_company_ai_credit,
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
        bad_callback["order_reference"] = "badver-001"
        bad_callback["payment_reference"] = "txn-badver"

        result = process_subscription_payment_callback(bad_callback)
        self.assertEqual(result["status"], "unsupported_order_schema_version")
        self.assertTrue(result["idempotent"])

    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_credited_historical_order_remains_idempotent(
        self, mock_convert, mock_update_status,
        mock_ensure_company_ai_credit,
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
        cred_callback["order_reference"] = "credit-hist"
        cred_callback["payment_reference"] = "txn-credhist"

        result = process_subscription_payment_callback(cred_callback)
        self.assertEqual(result["status"], "already_activated")
        self.assertTrue(result["idempotent"])


class TestPaidOrderNeverStallsSilentlyAtClaimed(unittest.TestCase):
    """Regression: a paid order must never sit at activation_status='claimed'
    with no reason recorded.

    Live incident 2026-09-18, order 33 (company 1, CHIP live, RM1.00): the
    renewal snapshot captured source_status='active' at checkout, the lifecycle
    job expired the subscription 6 minutes before the customer paid, and
    conditional_activate_subscription then matched zero rows. The activation
    sequence had already been claimed, so the row was left status='paid',
    activation_status='claimed', activation_error_code=NULL,
    reconciliation_required=false - money taken, nothing delivered, and nothing
    anywhere flagging it.
    """

    def setUp(self):
        self.callback = {
            "payment_gateway": "chip",
            "gateway_order_id": "chip-purchase-1",
            "order_reference": "94a0eb99-6a4b-4dc5-a3ec-145edca80eaa",
            "paid": True,
            "payment_reference": "chip-txn-1",
            "amount_sen": 100,
            "paid_at": "2026-09-18T05:06:39Z",
        }
        self.order = {
            "id": 33,
            "order_reference": "94a0eb99-6a4b-4dc5-a3ec-145edca80eaa",
            "company_id": 1,
            "subscription_id": 1,
            "new_plan_id": 4,
            "amount_sen": 100,
            "status": "paid",
            "payment_gateway": "chip",
            "gateway_environment": "live",
            "gateway_order_id": "chip-purchase-1",
            "payment_reference": "chip-txn-1",
            "order_schema_version": 2,
            "activation_type": "renewal",
            "source_plan_id": 4,
            "source_status": "active",
            "source_period_start": "2026-07-28T16:38:37.437543Z",
            "source_period_end": "2026-08-28T16:38:37.437543Z",
            "activation_sequence_key": (
                "company:1:renewal-after:2026-08-28T16:38:37.437543+00:00"
            ),
        }
        self.plan = {
            "id": 4,
            "code": "essential",
            "billing_interval": "monthly",
            "included_ai_credit_micro_myr": 5000000,
            "name": "Essential",
        }

    @patch(_SVC + "._update_activation_state")
    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".conditional_activate_subscription")
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_source_state_mismatch_flags_the_order_for_reconciliation(
        self, mock_convert, mock_update_status,
        mock_ensure_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
        mock_update_activation_state,
    ):
        mock_get_order.return_value = self.order
        mock_get_plan.return_value = self.plan
        # The subscription expired between checkout and payment, so the
        # conditional update matches zero rows.
        mock_cond_activate.side_effect = ValueError(
            "Subscription source state mismatch: expected plan=4, status=active"
        )

        with self.assertRaises(RuntimeError):
            process_subscription_payment_callback(self.callback)

        flagged = [
            call.kwargs for call in mock_update_activation_state.call_args_list
            if call.kwargs.get("activation_error_code")
        ]
        self.assertTrue(
            flagged,
            "paid order stalled after the activation claim without recording "
            "any activation_error_code - this is the silent stall",
        )
        self.assertEqual(flagged[-1]["activation_error_code"], "source_subscription_changed")
        self.assertTrue(
            flagged[-1]["reconciliation_required"],
            "a stalled paid order must be flagged for reconciliation",
        )

    @patch(_SVC + "._update_activation_state")
    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".conditional_activate_subscription")
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_stall_flag_never_moves_activation_status_off_claimed(
        self, mock_convert, mock_update_status,
        mock_ensure_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
        mock_update_activation_state,
    ):
        """The reconciler reads activation_status to pick which stage to retry,
        and conflict/failed are terminal. Flagging must not spend that retry."""
        mock_get_order.return_value = self.order
        mock_get_plan.return_value = self.plan
        mock_cond_activate.side_effect = ValueError("source state mismatch")

        with self.assertRaises(RuntimeError):
            process_subscription_payment_callback(self.callback)

        written_statuses = [
            call.kwargs.get("activation_status")
            for call in mock_update_activation_state.call_args_list
        ]
        self.assertNotIn("conflict", written_statuses)
        self.assertNotIn("failed", written_statuses)
        self.assertIsNone(written_statuses[-1])

    @patch(_SVC + "._update_activation_state")
    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".conditional_activate_subscription")
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_malformed_v2_order_is_flagged_after_the_claim(
        self, mock_convert, mock_update_status,
        mock_ensure_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
        mock_update_activation_state,
    ):
        """The claim happens before the schema check, so this exit stalls too."""
        malformed = dict(self.order)
        malformed["source_status"] = None
        mock_get_order.return_value = malformed
        mock_get_plan.return_value = self.plan

        result = process_subscription_payment_callback(self.callback)

        self.assertEqual(result["status"], "malformed_atomic_order")
        flagged = [
            call.kwargs for call in mock_update_activation_state.call_args_list
            if call.kwargs.get("activation_error_code")
        ]
        self.assertTrue(flagged, "malformed v2 order stalled at claimed unflagged")
        self.assertEqual(flagged[-1]["activation_error_code"], "malformed_atomic_order")
        self.assertTrue(flagged[-1]["reconciliation_required"])

    @patch(_SVC + "._update_activation_state")
    @patch(_SVC + "._claim_activation_sequence")
    @patch(_SVC + "._get_order_by_gateway")
    @patch(_SVC + ".get_plan_by_id")
    @patch(_SVC + ".conditional_activate_subscription")
    @patch(_SVC + "._ensure_company_ai_credit")
    @patch(_SVC + "._update_order_status")
    @patch(_SVC + ".convert_trial_ai_configuration")
    def test_already_credited_order_is_a_no_op_and_never_regrants_credit(
        self, mock_convert, mock_update_status,
        mock_ensure_credit, mock_cond_activate,
        mock_get_plan, mock_get_order, mock_claim_seq,
        mock_update_activation_state,
    ):
        """Re-driving a credited order must not activate, credit, or flag it."""
        credited = dict(self.order)
        credited["status"] = "credited"
        mock_get_order.return_value = credited
        mock_get_plan.return_value = self.plan

        result = process_subscription_payment_callback(self.callback)

        self.assertEqual(result["status"], "already_activated")
        self.assertTrue(result["idempotent"])
        mock_cond_activate.assert_not_called()
        mock_ensure_credit.assert_not_called()
        mock_claim_seq.assert_not_called()
        self.assertEqual(mock_update_activation_state.call_args_list, [])
