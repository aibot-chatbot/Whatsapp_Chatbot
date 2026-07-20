"""Focused tests for AI-credit repository RPC return values."""

import unittest
from unittest.mock import patch


class _Response:
    def __init__(self, data):
        self.data = data


class _RpcCall:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return _Response(self.data)


class _RpcSupabase:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return _RpcCall(self.data)


class TestAiCreditRepositoryRpcReturns(unittest.TestCase):
    def test_add_ai_credit_topup_returns_first_rpc_row(self):
        from app.database import ai_credit_repository

        expected = {
            "status": "applied",
            "transaction_id": 101,
            "company_id": 42,
        }
        fake_supabase = _RpcSupabase([expected])

        with patch.object(ai_credit_repository, "supabase", fake_supabase):
            result = ai_credit_repository.add_ai_credit_topup(
                company_id=42,
                amount_micro_myr=2_000_000,
                idempotency_key="topup-key",
                payment_reference="gateway-ref",
                description="Top-up",
            )

        self.assertEqual(result, expected)
        self.assertEqual(fake_supabase.calls[0][0], "add_ai_credit_topup")

    def test_allocate_subscription_included_credit_returns_first_rpc_row(self):
        from app.database import ai_credit_repository

        expected = {
            "status": "applied",
            "transaction_id": 202,
            "company_id": 42,
        }
        fake_supabase = _RpcSupabase([expected])

        with patch.object(ai_credit_repository, "supabase", fake_supabase):
            result = ai_credit_repository.allocate_subscription_included_credit(
                company_id=42,
                amount_micro_myr=60_000_000,
                idempotency_key="included-key",
                payment_reference="subscription-ref",
                plan_code="pro",
                description="Included credit",
            )

        self.assertEqual(result, expected)
        self.assertEqual(fake_supabase.calls[0][0], "allocate_subscription_included_credit")


if __name__ == "__main__":
    unittest.main()
