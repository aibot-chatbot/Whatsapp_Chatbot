"""Tests for the top-up callback processing service."""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("AI_CREDIT_ENFORCEMENT_ENABLED", "True")

import sys
import pathlib
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import unittest
from unittest.mock import patch, MagicMock, ANY
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
    from app.services.ai_credit_topup_callback_service import (
        process_topup_payment_callback,
    )

_BASE_ORDER = {
    "order_reference": "11111111-1111-4111-8111-111111111111",
    "company_id": 1,
    "subscription_id": 10,
    "amount_micro_myr": 1_000_000,
    "currency": "MYR",
    "payment_gateway": "toyyibpay",
    "gateway_order_id": "BC123",
    "idempotency_key": "idem-key-001",
    "status": "pending",
    "gateway_payment_id": None,
    "payment_reference": None,
    "credit_transaction_id": None,
    "created_at": "2026-07-30T12:00:00+00:00",
    "expires_at": "2026-07-30T13:00:00+00:00",
}

_CALLBACK = {
    "payment_gateway": "toyyibpay",
    "gateway_order_id": "BC123",
    "order_reference": "11111111-1111-4111-8111-111111111111",
    "paid": True,
    "payment_reference": "REF123",
    "amount_sen": 100,
    "paid_at": "2026-07-30T12:05:00+00:00",
    "failure_reason": None,
}


class TestTopupCallbackService(unittest.TestCase):
    """Focused unit tests for the top-up callback service."""

    @staticmethod
    def _make_order(**overrides):
        order = dict(_BASE_ORDER)
        order.update(overrides)
        return order

    @staticmethod
    def _make_callback(**overrides):
        cb = dict(_CALLBACK)
        cb.update(overrides)
        return cb

    # ------------------------------------------------------------------
    # 1. pending order succeeds and becomes credited
    # ------------------------------------------------------------------
    @patch("app.services.ai_credit_topup_callback_service._mark_order_credited")
    @patch("app.services.ai_credit_topup_callback_service._add_topup_credit")
    @patch("app.services.ai_credit_topup_callback_service._mark_order_paid")
    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_pending_order_becomes_credited(
        self, mock_get, mock_paid, mock_credit, mock_credited
    ):
        mock_get.return_value = self._make_order(status="pending")
        mock_paid.return_value = self._make_order(status="paid")
        mock_credit.return_value = {"status": "applied", "transaction_id": 500}
        mock_credited.return_value = self._make_order(status="credited")
        result = process_topup_payment_callback(self._make_callback())
        self.assertEqual(result["status"], "credited")
        self.assertFalse(result["idempotent"])
        self.assertEqual(result["credit_transaction_id"], 500)
        self.assertEqual(result["order_status"], "credited")
        mock_paid.assert_called_once_with(
            order_reference="11111111-1111-4111-8111-111111111111",
            gateway_payment_id="BC123",
            payment_reference="REF123",
            paid_at="2026-07-30T12:05:00+00:00",
        )

    # ------------------------------------------------------------------
    # 2. paid order resumes and becomes credited
    # ------------------------------------------------------------------
    @patch("app.services.ai_credit_topup_callback_service._mark_order_credited")
    @patch("app.services.ai_credit_topup_callback_service._add_topup_credit")
    @patch("app.services.ai_credit_topup_callback_service._mark_order_paid")
    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_paid_order_resumes(
        self, mock_get, mock_paid, mock_credit, mock_credited
    ):
        mock_get.return_value = self._make_order(
            status="paid",
            gateway_payment_id="BC123",
            payment_reference="REF123",
        )
        mock_credit.return_value = {"status": "applied", "transaction_id": 500}
        mock_credited.return_value = self._make_order(status="credited")
        result = process_topup_payment_callback(self._make_callback())
        self.assertEqual(result["status"], "credited")
        mock_paid.assert_not_called()

    # ------------------------------------------------------------------
    # 3. paid order with already-applied credit recovers
    # ------------------------------------------------------------------
    @patch("app.services.ai_credit_topup_callback_service._mark_order_credited")
    @patch("app.services.ai_credit_topup_callback_service._add_topup_credit")
    @patch("app.services.ai_credit_topup_callback_service._mark_order_paid")
    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_paid_order_already_applied_recovers(
        self, mock_get, mock_paid, mock_credit, mock_credited
    ):
        mock_get.return_value = self._make_order(
            status="paid",
            gateway_payment_id="BC123",
            payment_reference="REF123",
        )
        mock_credit.return_value = {
            "status": "already_applied",
            "transaction_id": 500,
        }
        mock_credited.return_value = self._make_order(status="credited")
        result = process_topup_payment_callback(self._make_callback())
        self.assertEqual(result["status"], "already_credited")
        self.assertTrue(result["idempotent"])
        mock_credited.assert_called_once_with(
            order_reference="11111111-1111-4111-8111-111111111111",
            credit_transaction_id=500,
            credited_at="2026-07-30T12:05:00+00:00",
        )

    # ------------------------------------------------------------------
    # 4. credited order with matching callback returns idempotent success
    # ------------------------------------------------------------------
    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_credited_matching_callback_idempotent(self, mock_get):
        mock_get.return_value = self._make_order(
            status="credited",
            gateway_payment_id="BC123",
            payment_reference="REF123",
            credit_transaction_id=500,
        )
        result = process_topup_payment_callback(self._make_callback())
        self.assertEqual(result["status"], "already_credited")
        self.assertTrue(result["idempotent"])

    # ------------------------------------------------------------------
    # 5. credited order with mismatched callback raises
    # ------------------------------------------------------------------
    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_credited_mismatched_callback_raises(self, mock_get):
        mock_get.return_value = self._make_order(
            status="credited",
            gateway_payment_id="BC123",
            payment_reference="DIFFERENT_REF",
            credit_transaction_id=500,
        )
        with self.assertRaises(ValueError) as ctx:
            process_topup_payment_callback(self._make_callback())
        self.assertIn("payment_reference", str(ctx.exception))

    # ------------------------------------------------------------------
    # 6. credited order with amount mismatch is logged
    # ------------------------------------------------------------------
    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_credited_amount_mismatch_logged(self, mock_get):
        """Amount mismatch is logged but does not reject the transaction."""
        mock_get.return_value = self._make_order(
            status="credited",
            amount_micro_myr=500_000,
            gateway_payment_id="BC123",
            payment_reference="REF123",
            credit_transaction_id=500,
        )
        result = process_topup_payment_callback(self._make_callback())
        self.assertEqual(result["status"], "already_credited")
        self.assertTrue(result["idempotent"])

    # ------------------------------------------------------------------
    # 7. unknown gateway_order_id is rejected
    # ------------------------------------------------------------------
    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_unknown_bill_code_rejected(self, mock_get):
        mock_get.return_value = None
        with self.assertRaises(ValueError) as ctx:
            process_topup_payment_callback(self._make_callback())
        self.assertIn("No toyyibpay top-up order found", str(ctx.exception))

    # ------------------------------------------------------------------
    # 8. missing gateway_order_id is rejected
    # ------------------------------------------------------------------
    def test_missing_gateway_order_id_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            process_topup_payment_callback(self._make_callback(gateway_order_id=""))
        self.assertIn("gateway_order_id", str(ctx.exception))

    # ------------------------------------------------------------------
    # 9. missing payment_reference is rejected
    # ------------------------------------------------------------------
    def test_missing_payment_reference_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            process_topup_payment_callback(self._make_callback(payment_reference=""))
        self.assertIn("payment_reference", str(ctx.exception))

    # ------------------------------------------------------------------
    # 10. unpaid callback is not credited
    # ------------------------------------------------------------------
    @patch("app.services.ai_credit_topup_callback_service._mark_order_credited")
    @patch("app.services.ai_credit_topup_callback_service._add_topup_credit")
    @patch("app.services.ai_credit_topup_callback_service._mark_order_paid")
    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_unpaid_callback_not_credited(
        self, mock_get, mock_paid, mock_credit, mock_credited
    ):
        """Unpaid callback raises ValueError and does not grant credit."""
        mock_get.return_value = self._make_order(status="pending")
        with self.assertRaises(ValueError) as ctx:
            process_topup_payment_callback(
                self._make_callback(paid=False, failure_reason="Payment cancelled")
            )
        self.assertIn("not successful", str(ctx.exception))
        mock_paid.assert_not_called()
        mock_credit.assert_not_called()
        mock_credited.assert_not_called()

    # ------------------------------------------------------------------
    # 11. amount_sen fallback support
    # ------------------------------------------------------------------
    @patch("app.services.ai_credit_topup_callback_service._mark_order_credited")
    @patch("app.services.ai_credit_topup_callback_service._add_topup_credit")
    @patch("app.services.ai_credit_topup_callback_service._mark_order_paid")
    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_amount_sen_fallback(
        self, mock_get, mock_paid, mock_credit, mock_credited
    ):
        mock_get.return_value = self._make_order(status="pending")
        mock_paid.return_value = self._make_order(status="paid")
        mock_credit.return_value = {"status": "applied", "transaction_id": 500}
        mock_credited.return_value = self._make_order(status="credited")
        process_topup_payment_callback(
            self._make_callback(
                paid_amount_sen=0,
                amount_sen=100,
            )
        )
        mock_credit.assert_called_once()

    # ------------------------------------------------------------------
    # 12. zero, boolean, and non-integer amounts are rejected
    # ------------------------------------------------------------------
    def test_zero_paid_amount_rejected(self):
        with self.assertRaises(ValueError):
            process_topup_payment_callback(
                self._make_callback(
                    paid_amount_sen=0,
                    amount_sen=0,
                )
            )

    def test_boolean_paid_amount_rejected(self):
        with self.assertRaises(ValueError):
            process_topup_payment_callback(self._make_callback(paid_amount_sen=True))

    def test_boolean_amount_sen_rejected(self):
        with self.assertRaises(ValueError):
            process_topup_payment_callback(
                self._make_callback(
                    paid_amount_sen=0,
                    amount_sen=False,
                )
            )

    # ------------------------------------------------------------------
    # 13. failed, expired, cancelled orders are rejected
    # ------------------------------------------------------------------
    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_terminal_states_rejected(self, mock_get):
        for status in ("failed", "expired", "cancelled"):
            with self.subTest(status=status):
                mock_get.return_value = self._make_order(status=status)
                with self.assertRaises(ValueError) as ctx:
                    process_topup_payment_callback(self._make_callback())
                self.assertIn(status, str(ctx.exception))

    # ------------------------------------------------------------------
    # 14. claimed status is rejected
    # ------------------------------------------------------------------
    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_claimed_status_rejected(self, mock_get):
        mock_get.return_value = self._make_order(status="claimed")
        with self.assertRaises(ValueError) as ctx:
            process_topup_payment_callback(self._make_callback())
        self.assertIn("claimed", str(ctx.exception))

    # ------------------------------------------------------------------
    # 15. credit service failure does not mark credited
    # ------------------------------------------------------------------
    @patch("app.services.ai_credit_topup_callback_service._mark_order_credited")
    @patch("app.services.ai_credit_topup_callback_service._add_topup_credit")
    @patch("app.services.ai_credit_topup_callback_service._mark_order_paid")
    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_credit_failure_does_not_mark_credited(
        self, mock_get, mock_paid, mock_credit, mock_credited
    ):
        mock_get.return_value = self._make_order(status="pending")
        mock_paid.return_value = self._make_order(status="paid")
        mock_credit.side_effect = RuntimeError("RPC error")
        with self.assertRaises(RuntimeError):
            process_topup_payment_callback(self._make_callback())
        mock_credited.assert_not_called()

    # ------------------------------------------------------------------
    # 16. mark credited failure reports reconciliation-required state
    # ------------------------------------------------------------------
    @patch("app.services.ai_credit_topup_callback_service._mark_order_credited")
    @patch("app.services.ai_credit_topup_callback_service._add_topup_credit")
    @patch("app.services.ai_credit_topup_callback_service._mark_order_paid")
    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_mark_credited_failure_reconciliation(
        self, mock_get, mock_paid, mock_credit, mock_credited
    ):
        mock_get.return_value = self._make_order(status="pending")
        mock_paid.return_value = self._make_order(status="paid")
        mock_credit.return_value = {"status": "applied", "transaction_id": 500}
        mock_credited.side_effect = RuntimeError("Transition failed")
        with self.assertRaises(RuntimeError) as ctx:
            process_topup_payment_callback(self._make_callback())
        self.assertIn("Reconciliation required", str(ctx.exception))



    # ------------------------------------------------------------------
    # 17. callback order_id identity cross-check
    # ------------------------------------------------------------------
    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_matching_order_reference_accepted(self, mock_get):
        """Valid callback with matching order_id is processed normally."""
        mock_get.return_value = self._make_order(status="pending")
        with patch("app.services.ai_credit_topup_callback_service._mark_order_paid") as mock_paid,              patch("app.services.ai_credit_topup_callback_service._add_topup_credit") as mock_credit,              patch("app.services.ai_credit_topup_callback_service._mark_order_credited") as mock_credited:
            mock_paid.return_value = self._make_order(status="paid")
            mock_credit.return_value = {"status": "applied", "transaction_id": 500}
            mock_credited.return_value = self._make_order(status="credited")
            result = process_topup_payment_callback(
                self._make_callback(
                    order_reference="11111111-1111-4111-8111-111111111111",
                )
            )
            self.assertEqual(result["status"], "credited")
            mock_paid.assert_called_once()

    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_mismatched_order_reference_rejected(self, mock_get):
        """Valid hash but different order_id is rejected before credit."""
        mock_get.return_value = self._make_order(status="pending")
        with patch("app.services.ai_credit_topup_callback_service._mark_order_paid") as mock_paid,              patch("app.services.ai_credit_topup_callback_service._add_topup_credit") as mock_credit,              patch("app.services.ai_credit_topup_callback_service._mark_order_credited") as mock_credited:
            with self.assertRaises(ValueError) as ctx:
                process_topup_payment_callback(
                    self._make_callback(
                        order_reference="22222222-2222-4222-8222-222222222222",
                    )
                )
            self.assertIn("does not match", str(ctx.exception))
            mock_paid.assert_not_called()
            mock_credit.assert_not_called()
            mock_credited.assert_not_called()

    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_mismatched_callback_does_not_apply_credit(self, mock_get):
        """Mismatched order_id does not call credit RPC."""
        mock_get.return_value = self._make_order(status="pending")
        with patch("app.services.ai_credit_topup_callback_service._mark_order_paid") as mock_paid,              patch("app.services.ai_credit_topup_callback_service._add_topup_credit") as mock_credit,              patch("app.services.ai_credit_topup_callback_service._mark_order_credited") as mock_credited:
            with self.assertRaises(ValueError):
                process_topup_payment_callback(
                    self._make_callback(
                        order_reference="22222222-2222-4222-8222-222222222222",
                    )
                )
            mock_credit.assert_not_called()

    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_mismatched_callback_does_not_mark_paid(self, mock_get):
        """Mismatched order_id does not mark order paid."""
        mock_get.return_value = self._make_order(status="pending")
        with patch("app.services.ai_credit_topup_callback_service._mark_order_paid") as mock_paid,              patch("app.services.ai_credit_topup_callback_service._add_topup_credit") as mock_credit,              patch("app.services.ai_credit_topup_callback_service._mark_order_credited") as mock_credited:
            with self.assertRaises(ValueError):
                process_topup_payment_callback(
                    self._make_callback(
                        order_reference="22222222-2222-4222-8222-222222222222",
                    )
                )
            mock_paid.assert_not_called()

    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_missing_callback_order_reference_rejected(self, mock_get):
        """Callback without order_id is rejected by processing."""
        mock_get.return_value = self._make_order(status="pending")
        with self.assertRaises(ValueError) as ctx:
            process_topup_payment_callback(
                self._make_callback(order_reference=None)
            )
        self.assertIn("order_reference", str(ctx.exception))

    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_empty_callback_order_reference_rejected(self, mock_get):
        """Callback with empty order_id is rejected."""
        mock_get.return_value = self._make_order(status="pending")
        with self.assertRaises(ValueError) as ctx:
            process_topup_payment_callback(
                self._make_callback(order_reference="")
            )
        self.assertIn("order_reference", str(ctx.exception))

    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_uppercase_uuid_still_matches(self, mock_get):
        """Uppercase UUID in callback is normalized to canonical form."""
        mock_get.return_value = self._make_order(status="pending")
        with patch("app.services.ai_credit_topup_callback_service._mark_order_paid") as mock_paid,              patch("app.services.ai_credit_topup_callback_service._add_topup_credit") as mock_credit,              patch("app.services.ai_credit_topup_callback_service._mark_order_credited") as mock_credited:
            mock_paid.return_value = self._make_order(status="paid")
            mock_credit.return_value = {"status": "applied", "transaction_id": 500}
            mock_credited.return_value = self._make_order(status="credited")
            result = process_topup_payment_callback(
                self._make_callback(
                    order_reference="11111111-1111-4111-8111-111111111111".upper(),
                )
            )
            self.assertEqual(result["status"], "credited")
            mock_paid.assert_called_once()

    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_compact_uuid_still_matches(self, mock_get):
        """Compact UUID (no hyphens) in callback is normalized to canonical."""
        mock_get.return_value = self._make_order(status="pending")
        with patch("app.services.ai_credit_topup_callback_service._mark_order_paid") as mock_paid,              patch("app.services.ai_credit_topup_callback_service._add_topup_credit") as mock_credit,              patch("app.services.ai_credit_topup_callback_service._mark_order_credited") as mock_credited:
            mock_paid.return_value = self._make_order(status="paid")
            mock_credit.return_value = {"status": "applied", "transaction_id": 500}
            mock_credited.return_value = self._make_order(status="credited")
            compact = "11111111111141118111111111111111"
            result = process_topup_payment_callback(
                self._make_callback(
                    order_reference=compact,
                )
            )
            self.assertEqual(result["status"], "credited")
            mock_paid.assert_called_once()

    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    def test_no_network_request_in_identity_check(self, mock_get):
        """Identity check does not make ToyyibPay or Supabase calls."""
        mock_get.return_value = self._make_order(status="pending")
        with patch("app.services.ai_credit_topup_callback_service._mark_order_paid") as mock_paid,              patch("app.services.ai_credit_topup_callback_service._add_topup_credit") as mock_credit,              patch("app.services.ai_credit_topup_callback_service._mark_order_credited") as mock_credited:
            with patch("app.services.toyyibpay_service.requests.post") as mock_post:
                with self.assertRaises(ValueError):
                    process_topup_payment_callback(
                        self._make_callback(
                            order_reference="22222222-2222-4222-8222-222222222222",
                        )
                    )
                mock_post.assert_not_called()



if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromTestCase(TestTopupCallbackService))
    sys.exit(0 if result.wasSuccessful() else 1)