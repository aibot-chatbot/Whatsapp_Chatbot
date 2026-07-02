"""Tests for UUID order-reference generation, validation and repository compatibility."""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("AI_CREDIT_ENFORCEMENT_ENABLED", "true")

import sys
sys.path.insert(0, r"C:\Users\User\PycharmProjects\python-whatsapp-bot-main")

import uuid
import unittest
from unittest.mock import patch, MagicMock, PropertyMock, ANY

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
    from app.services.ai_credit_topup_order_service import (
        _generate_order_reference,
        _validate_order_reference,
        create_pending_topup_order,
        mark_order_paid as service_mark_paid,
        mark_order_credited as service_mark_credited,
        mark_order_failed as service_mark_failed,
        mark_order_expired as service_mark_expired,
        mark_order_cancelled as service_mark_cancelled,
        claim_checkout_creation,
        complete_checkout_creation,
        fail_checkout_creation,
    )

TEST_UUID_STR = "11111111-1111-4111-8111-111111111111"
TEST_UUID_COMPACT = "11111111111141118111111111111111"
TEST_UUID_UPPER = "11111111-1111-4111-8111-111111111111".upper()
TEST_UUID_OBJ = uuid.UUID(TEST_UUID_STR)


class TestOrderReferenceGeneration(unittest.TestCase):
    """Tests for _generate_order_reference()."""

    def test_generated_reference_is_valid_uuid_v4(self):
        ref = _generate_order_reference()
        parsed = uuid.UUID(ref)
        self.assertEqual(parsed.version, 4)

    def test_two_generated_references_differ(self):
        ref1 = _generate_order_reference()
        ref2 = _generate_order_reference()
        self.assertNotEqual(ref1, ref2)

    def test_generated_reference_is_canonical_lowercase(self):
        ref = _generate_order_reference()
        self.assertEqual(ref, ref.lower())
        self.assertIn("-", ref)


class TestOrderReferenceValidation(unittest.TestCase):
    """Tests for _validate_order_reference()."""

    def test_valid_canonical_uuid_string_returned_unchanged(self):
        result = _validate_order_reference(TEST_UUID_STR)
        self.assertEqual(result, TEST_UUID_STR)

    def test_uuid_object_converted_to_canonical_string(self):
        result = _validate_order_reference(TEST_UUID_OBJ)
        self.assertEqual(result, TEST_UUID_STR)

    def test_compact_uuid_text_normalized(self):
        result = _validate_order_reference(TEST_UUID_COMPACT)
        self.assertEqual(result, TEST_UUID_STR)

    def test_uppercase_uuid_text_normalized(self):
        result = _validate_order_reference(TEST_UUID_UPPER)
        self.assertEqual(result, TEST_UUID_STR)

    def test_topup_prefix_rejected(self):
        with self.assertRaises(ValueError):
            _validate_order_reference("TOPUP-1-20260730120000000")

    def test_malformed_uuid_rejected(self):
        with self.assertRaises(ValueError):
            _validate_order_reference("not-a-uuid")

    def test_empty_string_rejected(self):
        with self.assertRaises(ValueError):
            _validate_order_reference("")

    def test_integer_rejected(self):
        with self.assertRaises(ValueError):
            _validate_order_reference(12345)

    def test_boolean_rejected(self):
        with self.assertRaises(ValueError):
            _validate_order_reference(True)

    def test_partial_uuid_rejected(self):
        with self.assertRaises(ValueError):
            _validate_order_reference("11111111-1111-4111")


class TestCreateOrderUUIDIntegration(unittest.TestCase):
    """Tests that create_pending_topup_order sends a valid UUID."""

    @patch("app.services.ai_credit_topup_order_service._repo_get_by_idempotency_key", return_value=None)
    @patch("app.services.ai_credit_topup_order_service._repo_create")
    @patch("app.services.ai_credit_topup_order_service._repo_get_by_reference", return_value=MagicMock())
    def test_created_order_reference_is_valid_uuid(self, mock_get_ref, mock_create, mock_get_idem):
        mock_create.return_value = {
            "id": 1,
            "order_reference": TEST_UUID_STR,
            "company_id": 1,
            "status": "pending",
        }
        result = create_pending_topup_order(
            company_id=1,
            subscription_id=10,
            created_by_user_id=100,
            amount_micro_myr=1_000_000,
            payment_gateway="toyyibpay",
            idempotency_key="idem-001",
        )
        parsed = uuid.UUID(result["order_reference"])
        self.assertEqual(parsed.version, 4)
        self.assertEqual(result["order_reference"], str(parsed))

    @patch("app.services.ai_credit_topup_order_service._repo_get_by_idempotency_key", return_value=None)
    @patch("app.services.ai_credit_topup_order_service._repo_create")
    @patch("app.services.ai_credit_topup_order_service._repo_get_by_reference", return_value=MagicMock())
    def test_repository_insert_gets_canonical_uuid(self, mock_get_ref, mock_create, mock_get_idem):
        mock_create.return_value = {
            "id": 1,
            "order_reference": TEST_UUID_STR,
            "company_id": 1,
            "status": "pending",
        }
        result = create_pending_topup_order(
            company_id=1,
            subscription_id=10,
            created_by_user_id=100,
            amount_micro_myr=1_000_000,
            payment_gateway="toyyibpay",
            idempotency_key="idem-002",
        )
        _, call_kwargs = mock_create.call_args
        call_ref = call_kwargs.get("order_reference", "")
        uuid.UUID(call_ref)


class TestMarkOperationsUUID(unittest.TestCase):
    """Tests that status-marking functions pass canonical UUID to repository."""

    @patch("app.services.ai_credit_topup_order_service._repo_mark_paid")
    def test_mark_paid_receives_canonical_uuid(self, mock_repo):
        mock_repo.return_value = {"id": 1, "order_reference": TEST_UUID_STR, "status": "paid"}
        result = service_mark_paid(
            order_reference=TEST_UUID_STR,
            gateway_payment_id="pay_abc",
            payment_reference="ref_abc",
            paid_at="2026-07-30T12:00:00+00:00",
        )
        kwargs = mock_repo.call_args.kwargs
        uuid.UUID(kwargs["order_reference"])

    @patch("app.services.ai_credit_topup_order_service._repo_mark_credited")
    def test_mark_credited_receives_canonical_uuid(self, mock_repo):
        mock_repo.return_value = {"id": 1, "order_reference": TEST_UUID_STR, "status": "credited"}
        result = service_mark_credited(
            order_reference=TEST_UUID_STR,
            credit_transaction_id=500,
            credited_at="2026-07-30T12:05:00+00:00",
        )
        kwargs = mock_repo.call_args.kwargs
        uuid.UUID(kwargs["order_reference"])

    @patch("app.services.ai_credit_topup_order_service._repo_mark_failed")
    def test_mark_failed_receives_canonical_uuid(self, mock_repo):
        mock_repo.return_value = {"id": 1, "order_reference": TEST_UUID_STR, "status": "failed"}
        result = service_mark_failed(
            order_reference=TEST_UUID_STR,
            failure_reason="test failure",
        )
        kwargs = mock_repo.call_args.kwargs
        uuid.UUID(kwargs["order_reference"])

    @patch("app.services.ai_credit_topup_order_service._repo_mark_expired")
    def test_mark_expired_receives_canonical_uuid(self, mock_repo):
        mock_repo.return_value = {"id": 1, "order_reference": TEST_UUID_STR, "status": "expired"}
        result = service_mark_expired(order_reference=TEST_UUID_STR)
        kwargs = mock_repo.call_args.kwargs
        uuid.UUID(kwargs["order_reference"])

    @patch("app.services.ai_credit_topup_order_service._repo_mark_cancelled")
    def test_mark_cancelled_receives_canonical_uuid(self, mock_repo):
        mock_repo.return_value = {"id": 1, "order_reference": TEST_UUID_STR, "status": "cancelled"}
        result = service_mark_cancelled(order_reference=TEST_UUID_STR)
        kwargs = mock_repo.call_args.kwargs
        uuid.UUID(kwargs["order_reference"])


class TestCallbackIdempotencyKeyUUID(unittest.TestCase):
    """Tests that the callback service uses UUID as idempotency key."""

    @patch("app.services.ai_credit_topup_callback_service._add_topup_credit")
    @patch("app.services.ai_credit_topup_callback_service._get_order_by_gateway")
    @patch("app.services.ai_credit_topup_callback_service._mark_order_paid")
    @patch("app.services.ai_credit_topup_callback_service._mark_order_credited")
    def test_callback_service_uses_uuid_as_idempotency_key(
        self, mock_mark_credited, mock_mark_paid, mock_get_order, mock_credit
    ):
        mock_get_order.return_value = {
            "id": 1,
            "order_reference": TEST_UUID_STR,
            "company_id": 1,
            "amount_micro_myr": 1_000_000,
            "currency": "MYR",
            "payment_gateway": "toyyibpay",
            "gateway_order_id": "BC123",
            "status": "pending",
            "idempotency_key": "idem-key-001",
        }
        mock_mark_paid.return_value = {
            "id": 1,
            "order_reference": TEST_UUID_STR,
            "status": "paid",
            "gateway_payment_id": "BC123",
            "payment_reference": "REF123",
        }
        mock_mark_credited.return_value = {
            "id": 1,
            "order_reference": TEST_UUID_STR,
            "status": "credited",
            "credit_transaction_id": 500,
        }
        mock_credit.return_value = {"status": "applied", "transaction_id": 500}

        from app.services.ai_credit_topup_callback_service import process_topup_payment_callback

        result = process_topup_payment_callback({
            "payment_gateway": "toyyibpay",
            "gateway_order_id": "BC123",
            "paid": True,
            "payment_reference": "REF123",
            "amount_sen": 100,
            "paid_amount_sen": 100,
            "paid_at": "2026-07-30T12:05:00+00:00",
        })
        kwargs = mock_credit.call_args.kwargs
        idem_key = kwargs.get("idempotency_key")
        self.assertIsNotNone(idem_key)
        uuid.UUID(idem_key)


if __name__ == "__main__":
    unittest.main()

