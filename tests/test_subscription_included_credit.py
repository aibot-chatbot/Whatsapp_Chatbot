"""test_subscription_included_credit.py

Tests for the allocate_subscription_included_credit service function
and duplicate credit prevention.
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
    from app.services.ai_credit_service import (
        allocate_subscription_included_credit,
    )


class TestAllocateSubscriptionIncludedCredit(unittest.TestCase):
    """Tests for allocate_subscription_included_credit service function."""

    def setUp(self):
        self.valid_kwargs = {
            "company_id": 42,
            "amount_micro_myr": 60000000,
            "idempotency_key": "sub_credit_company_42_seq_abc123",
            "payment_reference": "txn-pro-001",
            "period_start": "2026-07-09T09:20:00",
            "period_end": "2026-08-09T09:20:00",
            "plan_code": "pro",
            "description": "Subscription pro included AI credit (sequence abc123)",
        }
        self.mock_rpc_result = {
            "status": "applied",
            "transaction_id": 100,
            "company_id": 42,
            "amount_micro_myr": 60000000,
            "included_balance_micro_myr": 60000000,
            "topup_balance_micro_myr": 2000000,
            "total_balance_micro_myr": 62000000,
            "payment_reference": "txn-pro-001",
            "idempotency_key": "sub_credit_company_42_seq_abc123",
        }

    @patch("app.services.ai_credit_service._allocate_included_credit")
    def test_successful_allocation_returns_correct_buckets(self, mock_rpc):
        """Verify included credit goes to included bucket, topup preserved."""
        mock_rpc.return_value = self.mock_rpc_result
        result = allocate_subscription_included_credit(**self.valid_kwargs)

        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["company_id"], 42)
        self.assertEqual(result["amount_micro_myr"], 60000000)
        # Included bucket should be 60,000,000
        self.assertEqual(result["included_balance_micro_myr"], 60000000)
        # Top-up bucket should be 2,000,000 (preserved)
        self.assertEqual(result["topup_balance_micro_myr"], 2000000)
        # Total = 62,000,000
        self.assertEqual(result["total_balance_micro_myr"], 62000000)

    @patch("app.services.ai_credit_service._allocate_included_credit")
    def test_idempotency_returns_already_applied(self, mock_rpc):
        """Verify duplicate call with same key returns already_applied."""
        mock_rpc.return_value = {
            "status": "already_applied",
            "transaction_id": 100,
            "company_id": 42,
            "amount_micro_myr": 60000000,
            "included_balance_micro_myr": 60000000,
            "topup_balance_micro_myr": 2000000,
            "total_balance_micro_myr": 62000000,
            "payment_reference": "txn-pro-001",
            "idempotency_key": "sub_credit_company_42_seq_abc123",
        }
        result = allocate_subscription_included_credit(**self.valid_kwargs)
        self.assertEqual(result["status"], "already_applied")

    @patch("app.services.ai_credit_service._allocate_included_credit")
    def test_preserves_topup_balance(self, mock_rpc):
        """Verify topup balance is preserved in result calculation."""
        mock_rpc.return_value = {
            "status": "applied",
            "transaction_id": 101,
            "company_id": 42,
            "amount_micro_myr": 5000000,
            "included_balance_micro_myr": 5000000,
            "topup_balance_micro_myr": 50000000,
            "total_balance_micro_myr": 55000000,
            "payment_reference": "txn-ess-001",
            "idempotency_key": "sub_credit_company_42_seq_xyz",
        }
        result = allocate_subscription_included_credit(
            company_id=42,
            amount_micro_myr=5000000,
            idempotency_key="sub_credit_company_42_seq_xyz",
            payment_reference="txn-ess-001",
        )
        self.assertEqual(result["included_balance_micro_myr"], 5000000)
        self.assertEqual(result["topup_balance_micro_myr"], 50000000)
        self.assertEqual(result["total_balance_micro_myr"], 55000000)

    @patch("app.services.ai_credit_service._allocate_included_credit")
    def test_rpc_called_with_correct_params(self, mock_rpc):
        """Verify the underlying RPC receives canonical parameters."""
        mock_rpc.return_value = self.mock_rpc_result
        allocate_subscription_included_credit(**self.valid_kwargs)

        mock_rpc.assert_called_once()
        _, kwargs = mock_rpc.call_args
        self.assertEqual(kwargs["company_id"], 42)
        self.assertEqual(kwargs["amount_micro_myr"], 60000000)
        self.assertEqual(kwargs["idempotency_key"], "sub_credit_company_42_seq_abc123")
        self.assertEqual(kwargs["payment_reference"], "txn-pro-001")
        self.assertEqual(kwargs["plan_code"], "pro")

    def test_invalid_company_id_rejected(self):
        """Verify non-positive company_id is rejected."""
        with self.assertRaises(ValueError):
            allocate_subscription_included_credit(
                company_id=0,
                amount_micro_myr=100,
                idempotency_key="test",
                payment_reference="test",
            )

    def test_invalid_amount_rejected(self):
        """Verify zero or negative amount is rejected."""
        with self.assertRaises(ValueError):
            allocate_subscription_included_credit(
                company_id=1,
                amount_micro_myr=0,
                idempotency_key="test",
                payment_reference="test",
            )

    def test_empty_idempotency_key_rejected(self):
        """Verify empty idempotency key is rejected."""
        with self.assertRaises(ValueError):
            allocate_subscription_included_credit(
                company_id=1,
                amount_micro_myr=100,
                idempotency_key="",
                payment_reference="test",
            )

    def test_empty_payment_reference_rejected(self):
        """Verify empty payment reference is rejected."""
        with self.assertRaises(ValueError):
            allocate_subscription_included_credit(
                company_id=1,
                amount_micro_myr=100,
                idempotency_key="test",
                payment_reference="",
            )


class TestDuplicateCreditPrevention(unittest.TestCase):
    """Integration-style tests for duplicate credit prevention via idempotency keys."""

    def setUp(self):
        self.rpc_call_count = 0
        self.rpc_results = []

    def _mock_rpc_first_applied(self, *args, **kwargs):
        """Simulate first call returns applied, second returns already_applied."""
        self.rpc_call_count += 1
        if self.rpc_call_count == 1:
            return {
                "status": "applied",
                "transaction_id": 100,
                "company_id": 42,
                "amount_micro_myr": 60000000,
                "included_balance_micro_myr": 60000000,
                "topup_balance_micro_myr": 2000000,
                "total_balance_micro_myr": 62000000,
                "payment_reference": "txn-pro-001",
                "idempotency_key": "sub_credit_company_42_seq_abc123",
            }
        return {
            "status": "already_applied",
            "transaction_id": 100,
            "company_id": 42,
            "amount_micro_myr": 60000000,
            "included_balance_micro_myr": 60000000,
            "topup_balance_micro_myr": 2000000,
            "total_balance_micro_myr": 62000000,
            "payment_reference": "txn-pro-001",
            "idempotency_key": "sub_credit_company_42_seq_abc123",
        }

    @patch("app.services.ai_credit_service._allocate_included_credit")
    def test_duplicate_same_key_returns_already_applied(self, mock_rpc):
        """Verify same idempotency key on repeated calls returns already_applied."""
        mock_rpc.side_effect = self._mock_rpc_first_applied

        # First call
        r1 = allocate_subscription_included_credit(
            company_id=42, amount_micro_myr=60000000,
            idempotency_key="sub_credit_company_42_seq_abc123",
            payment_reference="txn-pro-001",
        )
        self.assertEqual(r1["status"], "applied")
        self.assertEqual(r1["included_balance_micro_myr"], 60000000)

        # Second call with same key (simulating duplicate callback)
        r2 = allocate_subscription_included_credit(
            company_id=42, amount_micro_myr=60000000,
            idempotency_key="sub_credit_company_42_seq_abc123",
            payment_reference="txn-pro-001",
        )
        self.assertEqual(r2["status"], "already_applied")
        # Balances should still reflect only one grant
        self.assertEqual(r2["included_balance_micro_myr"], 60000000)
        self.assertEqual(r2["topup_balance_micro_myr"], 2000000)

    @patch("app.services.ai_credit_service._allocate_included_credit")
    def test_different_keys_both_applied(self, mock_rpc):
        """Verify different activation keys both get applied (different periods)."""
        calls = []
        def side_effect(*args, **kwargs):
            calls.append(kwargs)
            if "seq_abc" in kwargs.get("idempotency_key", ""):
                return {
                    "status": "applied", "transaction_id": 101,
                    "company_id": 42, "amount_micro_myr": 60000000,
                    "included_balance_micro_myr": 60000000,
                    "topup_balance_micro_myr": 2000000,
                    "total_balance_micro_myr": 62000000,
                    "payment_reference": "txn-pro-001",
                    "idempotency_key": "sub_credit_company_42_seq_abc123",
                }
            return {
                "status": "applied", "transaction_id": 102,
                "company_id": 42, "amount_micro_myr": 60000000,
                "included_balance_micro_myr": 120000000,
                "topup_balance_micro_myr": 2000000,
                "total_balance_micro_myr": 122000000,
                "payment_reference": "txn-pro-002",
                "idempotency_key": "sub_credit_company_42_seq_def456",
            }
        mock_rpc.side_effect = side_effect

        # First period
        r1 = allocate_subscription_included_credit(
            company_id=42, amount_micro_myr=60000000,
            idempotency_key="sub_credit_company_42_seq_abc123",
            payment_reference="txn-pro-001",
        )
        self.assertEqual(r1["status"], "applied")

        # Different period (legitimate renewal)
        r2 = allocate_subscription_included_credit(
            company_id=42, amount_micro_myr=60000000,
            idempotency_key="sub_credit_company_42_seq_def456",
            payment_reference="txn-pro-002",
        )
        self.assertEqual(r2["status"], "applied")
        # Both should have been applied
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
