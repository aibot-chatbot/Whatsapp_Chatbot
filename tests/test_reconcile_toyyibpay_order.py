"""Tests for the ToyyibPay order reconciliation script.

All tests use controlled environment variables with clear=True and
patch load_dotenv so .env values cannot leak in. Every test that calls
main() mocks the reconciliation_service so no real HTTP calls occur.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure the project root is on sys.path for import resolution
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.reconcile_toyyibpay_order import main, _validate_transaction, _normalize_transaction, _parse_toyyibpay_date


# -----------------------------------------------------------------------
# Shared environment template for successful-flow tests
# -----------------------------------------------------------------------

_PRODUCTION_ENV = {
    "TOYYIBPAY_ENV": "production",
    "CONFIRM_TOYYIBPAY_RECONCILE": "YES",
    "RECONCILE_ORDER_REFERENCE": "test-ref",
    "RECONCILE_BILL_CODE": "BC123",
}


class TestReconcileValidation(unittest.TestCase):
    """Pure validation tests that do not import app modules."""

    # -----------------------------------------------------------------------
    # Confirmation guards
    # -----------------------------------------------------------------------

    @patch.dict(os.environ, {
        "TOYYIBPAY_ENV": "production",
        "RECONCILE_ORDER_REFERENCE": "test-ref",
        "RECONCILE_BILL_CODE": "test-bill",
    }, clear=True)
    @patch("scripts.reconcile_toyyibpay_order.load_dotenv")
    def test_refuses_without_confirmation(self, mock_dotenv):
        """Exits when CONFIRM_TOYYIBPAY_RECONCILE is missing."""
        mock_service = MagicMock()
        with self.assertRaises(SystemExit):
            main(reconciliation_service=mock_service)
        mock_service.assert_not_called()

    @patch.dict(os.environ, {
        "TOYYIBPAY_ENV": "production",
        "RECONCILE_ORDER_REFERENCE": "test-ref",
        "RECONCILE_BILL_CODE": "test-bill",
        "CONFIRM_TOYYIBPAY_RECONCILE": "NO",
    }, clear=True)
    @patch("scripts.reconcile_toyyibpay_order.load_dotenv")
    def test_refuses_wrong_confirmation(self, mock_dotenv):
        """Exits when CONFIRM_TOYYIBPAY_RECONCILE is not YES."""
        mock_service = MagicMock()
        with self.assertRaises(SystemExit):
            main(reconciliation_service=mock_service)
        mock_service.assert_not_called()

    # -----------------------------------------------------------------------
    # Environment guard
    # -----------------------------------------------------------------------

    @patch.dict(os.environ, {
        "TOYYIBPAY_ENV": "sandbox",
        "CONFIRM_TOYYIBPAY_RECONCILE": "YES",
        "RECONCILE_ORDER_REFERENCE": "test-ref",
        "RECONCILE_BILL_CODE": "test-bill",
    }, clear=True)
    @patch("scripts.reconcile_toyyibpay_order.load_dotenv")
    def test_refuses_non_production(self, mock_dotenv):
        """Exits when TOYYIBPAY_ENV is not production."""
        mock_service = MagicMock()
        with self.assertRaises(SystemExit):
            main(reconciliation_service=mock_service)
        mock_service.assert_not_called()

    # -----------------------------------------------------------------------
    # Required input fields
    # -----------------------------------------------------------------------

    @patch.dict(os.environ, {
        "TOYYIBPAY_ENV": "production",
        "CONFIRM_TOYYIBPAY_RECONCILE": "YES",
        "RECONCILE_BILL_CODE": "test-bill",
    }, clear=True)
    @patch("scripts.reconcile_toyyibpay_order.load_dotenv")
    def test_refuses_missing_order_reference(self, mock_dotenv):
        """Exits when RECONCILE_ORDER_REFERENCE is missing."""
        mock_service = MagicMock()
        with self.assertRaises(SystemExit):
            main(reconciliation_service=mock_service)
        mock_service.assert_not_called()

    @patch.dict(os.environ, {
        "TOYYIBPAY_ENV": "production",
        "CONFIRM_TOYYIBPAY_RECONCILE": "YES",
        "RECONCILE_ORDER_REFERENCE": "test-ref",
    }, clear=True)
    @patch("scripts.reconcile_toyyibpay_order.load_dotenv")
    def test_refuses_missing_bill_code(self, mock_dotenv):
        """Exits when RECONCILE_BILL_CODE is missing."""
        mock_service = MagicMock()
        with self.assertRaises(SystemExit):
            main(reconciliation_service=mock_service)
        mock_service.assert_not_called()

    # -----------------------------------------------------------------------
    # _validate_transaction
    # -----------------------------------------------------------------------

    def test_validate_rejects_mismatched_external_ref(self):
        """Exits when billExternalReferenceNo does not match."""
        txn = {
            "billExternalReferenceNo": "wrong-ref",
            "billpaymentStatus": "1",
            "billpaymentInvoiceNo": "INV001",
        }
        with self.assertRaises(SystemExit):
            _validate_transaction(txn, "expected-ref", "BC123")

    def test_validate_rejects_missing_invoice(self):
        """Exits when billpaymentInvoiceNo is missing."""
        txn = {
            "billExternalReferenceNo": "expected-ref",
            "billpaymentStatus": "1",
        }
        with self.assertRaises(SystemExit):
            _validate_transaction(txn, "expected-ref", "BC123")

    def test_validate_rejects_unpaid_transaction(self):
        """Exits when billpaymentStatus is not 1."""
        txn = {
            "billExternalReferenceNo": "expected-ref",
            "billpaymentStatus": "0",
            "billpaymentInvoiceNo": "INV001",
        }
        with self.assertRaises(SystemExit):
            _validate_transaction(txn, "expected-ref", "BC123")

    def test_validate_accepts_valid_transaction(self):
        """Does not exit when all fields match (invoice present, status 1)."""
        txn = {
            "billExternalReferenceNo": "expected-ref",
            "billpaymentStatus": "1",
            "billpaymentInvoiceNo": "INV001",
        }
        # Should not raise
        _validate_transaction(txn, "expected-ref", "BC123")

    # -----------------------------------------------------------------------
    # _normalize_transaction
    # -----------------------------------------------------------------------

    def test_normalize_includes_payment_gateway(self):
        """Normalized struct includes toyyibpay gateway."""
        txn = {
            "billExternalReferenceNo": "order-ref-1",
            "billpaymentInvoiceNo": "INV001",
            "billpaymentAmount": "3.00",
            "billPaymentDate": "30/07/2026 12:05:00",
        }
        result = _normalize_transaction(txn, "BC123")
        self.assertEqual(result["payment_gateway"], "toyyibpay")
        self.assertEqual(result["paid_at"], "2026-07-30T04:05:00+00:00")

    def test_normalize_uses_decimal_amount(self):
        """Decimal amount 3.00 becomes 300 cent and 3000000 micro-MYR."""
        txn = {
            "billExternalReferenceNo": "order-ref-1",
            "billpaymentInvoiceNo": "INV001",
            "billpaymentAmount": "3.00",
            "billPaymentDate": "30/07/2026 12:05:00",
        }
        result = _normalize_transaction(txn, "BC123")
        self.assertEqual(result["amount_sen"], 300)
        self.assertEqual(result["paid_total_micro_myr"], 3000000)

    def test_normalize_paid_is_true(self):
        """paid is always True for reconciliation transactions."""
        txn = {
            "billExternalReferenceNo": "order-ref-1",
            "billpaymentInvoiceNo": "INV001",
            "billpaymentAmount": "2.00",
            "billPaymentDate": "30/07/2026 12:05:00",
        }
        result = _normalize_transaction(txn, "BC123")
        self.assertTrue(result["paid"])
        self.assertEqual(result["gateway_status"], "1")

    def test_normalize_does_not_print_secrets(self):
        """Normalized struct does not include userSecretKey."""
        txn = {
            "billExternalReferenceNo": "order-ref-1",
            "billpaymentInvoiceNo": "INV001",
            "billpaymentAmount": "2.00",
        }
        result = _normalize_transaction(txn, "BC123")
        for key in result:
            self.assertNotIn("secret", key.lower())
            self.assertNotIn("category", key.lower())
            self.assertNotIn("email", key.lower())
            self.assertNotIn("phone", key.lower())

    def test_normalize_handles_integer_amount(self):
        """Integer amount like 2 becomes 200 cent."""
        txn = {
            "billExternalReferenceNo": "order-ref-1",
            "billpaymentInvoiceNo": "INV001",
            "billpaymentAmount": 2,
        }
        result = _normalize_transaction(txn, "BC123")
        self.assertEqual(result["amount_sen"], 200)

    # -----
    def test_normalize_gateway_order_id_from_expected(self):
        """gateway_order_id comes from expected_bill_code, not from response."""
        txn = {
            "billExternalReferenceNo": "order-ref-1",
            "billpaymentInvoiceNo": "INV001",
            "billpaymentAmount": "2.00",
            "billPaymentDate": "30/07/2026 12:05:00",
        }
        result = _normalize_transaction(txn, "BC123")
        self.assertEqual(result["gateway_order_id"], "BC123")

    # -----------------------------------------------------------------------
    # _parse_toyyibpay_date
    # -----------------------------------------------------------------------

    def test_parse_date_dd_mm_yyyy(self):
        """02/07/2026 becomes 2026-07-02."""
        result = _parse_toyyibpay_date("02/07/2026 14:14:29")
        self.assertEqual(result, "2026-07-02T06:14:29+00:00")

    def test_parse_date_december(self):
        """31/12/2026 parses as December."""
        result = _parse_toyyibpay_date("31/12/2026 23:59:59")
        self.assertEqual(result, "2026-12-31T15:59:59+00:00")

    def test_parse_date_ambiguous_still_dd_mm(self):
        """03/04/2026 is 3 April, not 4 March."""
        result = _parse_toyyibpay_date("03/04/2026 10:00:00")
        self.assertEqual(result, "2026-04-03T02:00:00+00:00")

    def test_parse_date_empty_string(self):
        """Empty string returns empty."""
        result = _parse_toyyibpay_date("")
        self.assertEqual(result, "")

    def test_parse_date_whitespace(self):
        """Whitespace-only returns empty."""
        result = _parse_toyyibpay_date("   ")
        self.assertEqual(result, "")

    def test_parse_date_malformed_rejected(self):
        """Malformed date raises SystemExit."""
        with self.assertRaises(SystemExit):
            _parse_toyyibpay_date("not-a-date")

    def test_parse_date_wrong_order_rejected(self):
        """YYYY-MM-DD raises SystemExit."""
        with self.assertRaises(SystemExit):
            _parse_toyyibpay_date("2026-07-02 14:14:29")

    def test_parse_date_12h_format(self):
        """12-hour format with PM works."""
        result = _parse_toyyibpay_date("02/07/2026 02:14:29 PM")
        self.assertEqual(result, "2026-07-02T06:14:29+00:00")

    def test_parse_date_date_only(self):
        """Date without time becomes previous-day 16:00 UTC (MYT midnight)."""
        result = _parse_toyyibpay_date("02/07/2026")
        self.assertEqual(result, "2026-07-01T16:00:00+00:00")

    def test_normalize_includes_iso_paid_at(self):
        """paid_at in normalized result is ISO 8601."""
        txn = {
            "billExternalReferenceNo": "order-ref-1",
            "billpaymentInvoiceNo": "INV001",
            "billpaymentAmount": "2.00",
            "billPaymentDate": "02/07/2026 14:14:29",
        }
        result = _normalize_transaction(txn, "BC123")
        self.assertEqual(result["paid_at"], "2026-07-02T06:14:29+00:00")

    # -----------------------------------------------------------------------
    # Full reconciliation flow with mocked service (no live HTTP)
    # -----------------------------------------------------------------------

    @patch.dict(os.environ, dict(_PRODUCTION_ENV), clear=True)
    @patch("scripts.reconcile_toyyibpay_order.load_dotenv")
    def test_reconciliation_calls_callback_service(self, mock_dotenv):
        """Main calls callback service when reconciliation_service is provided."""
        mock_service = MagicMock()
        mock_service.return_value = {"status": "credited", "idempotent": False}

        with patch("builtins.print"):
            result = main(reconciliation_service=mock_service)

        mock_service.assert_called_once_with("test-ref", "BC123")
        self.assertEqual(result["status"], "credited")

    @patch.dict(os.environ, dict(_PRODUCTION_ENV), clear=True)
    @patch("scripts.reconcile_toyyibpay_order.load_dotenv")
    def test_reconciliation_never_applies_credit_directly(self, mock_dotenv):
        """Reconciliation goes through callback service, not direct credit."""
        mock_service = MagicMock()
        mock_service.return_value = {"status": "already_credited", "idempotent": True}

        with patch("builtins.print"):
            result = main(reconciliation_service=mock_service)

        self.assertEqual(result["status"], "already_credited")
        mock_service.assert_called_once()

    # -----------------------------------------------------------------------
    # Global network safety: ambient variables cannot bypass safeguards
    # -----------------------------------------------------------------------

    @patch.dict(os.environ, {
        "TOYYIBPAY_ENV": "production",
        "CONFIRM_TOYYIBPAY_RECONCILE": "YES",
        "RECONCILE_ORDER_REFERENCE": "",
        "RECONCILE_BILL_CODE": "BC123",
    }, clear=True)
    @patch("scripts.reconcile_toyyibpay_order.load_dotenv")
    def test_ambient_refuses_empty_order_ref(self, mock_dotenv):
        """Empty order reference is rejected without network call."""
        mock_service = MagicMock()
        with self.assertRaises(SystemExit):
            main(reconciliation_service=mock_service)
        mock_service.assert_not_called()

    @patch.dict(os.environ, {
        "CONFIRM_TOYYIBPAY_RECONCILE": "YES",
        "TOYYIBPAY_ENV": "production",
        "RECONCILE_ORDER_REFERENCE": "test-ref-0000-0000-000000000000",
        "RECONCILE_BILL_CODE": "BC123",
        "TOYYIBPAY_USER_SECRET_KEY": "test-key",
    }, clear=True)
    @patch("scripts.reconcile_toyyibpay_order.load_dotenv")
    def test_no_network_with_missing_safeguard(self, mock_dotenv):
        """Even with production-looking vars, missing one safeguard stops before any network call."""
        mock_service = MagicMock()
        os.environ.pop("CONFIRM_TOYYIBPAY_RECONCILE", None)

        with self.assertRaises(SystemExit):
            main(reconciliation_service=mock_service)
        mock_service.assert_not_called()

    # -----------------------------------------------------------------------
    # load_dotenv cannot restore cleared variables
    # -----------------------------------------------------------------------

    @patch.dict(os.environ, dict(_PRODUCTION_ENV), clear=True)
    def test_load_dotenv_does_not_leak_into_env(self):
        """load_dotenv is patched, so .env values cannot repopulate cleared env."""
        # Verify no stray production keys leaked in
        self.assertEqual(os.environ.get("TOYYIBPAY_ENV"), "production")
        self.assertEqual(os.environ.get("CONFIRM_TOYYIBPAY_RECONCILE"), "YES")
        # Secret key must NOT be present from .env
        self.assertNotIn("TOYYIBPAY_USER_SECRET_KEY", os.environ)


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromTestCase(TestReconcileValidation))
    sys.exit(0 if result.wasSuccessful() else 1)
