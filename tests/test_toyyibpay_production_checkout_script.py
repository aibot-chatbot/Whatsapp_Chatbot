"""Tests for the ToyyibPay production checkout script."""

import os
import sys
sys.path.insert(0, r"C:\Users\User\PycharmProjects\python-whatsapp-bot-main")
import unittest
from unittest.mock import patch, MagicMock, call


class TestToyyibPayProductionCheckoutScript(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "smoke_test_toyyibpay_production_checkout",
            os.path.join(
                r"C:\Users\User\PycharmProjects\python-whatsapp-bot-main",
                "scripts", "smoke_test_toyyibpay_production_checkout.py"
            ),
        );
        cls.mod = importlib.util.module_from_spec(spec);
        spec.loader.exec_module(cls.mod);

    # --- Confirmation guards ---

    @patch.dict(os.environ, {"TOYYIBPAY_ENV": "production"}, clear=True)
    def test_refuses_without_confirmation(self):
        with self.assertRaises(SystemExit):
            self.mod.main()

    @patch.dict(os.environ, {"TOYYIBPAY_ENV": "production", "CONFIRM_TOYYIBPAY_PRODUCTION_TEST": "NO"}, clear=True)
    def test_refuses_wrong_confirmation(self):
        with self.assertRaises(SystemExit):
            self.mod.main()

    @patch.dict(os.environ, {"TOYYIBPAY_ENV": "production", "CONFIRM_TOYYIBPAY_PRODUCTION_TEST": "nope"}, clear=True)
    def test_refuses_wrong_confirmation_value(self):
        with self.assertRaises(SystemExit):
            self.mod.main()

    @patch.dict(os.environ, {"TOYYIBPAY_ENV": "sandbox", "CONFIRM_TOYYIBPAY_PRODUCTION_TEST": "YES"}, clear=True)
    def test_refuses_when_env_not_production(self):
        with self.assertRaises(SystemExit):
            self.mod.main()

    @patch.dict(os.environ, {"TOYYIBPAY_ENV": "", "CONFIRM_TOYYIBPAY_PRODUCTION_TEST": "YES"}, clear=True)
    def test_refuses_when_env_missing(self):
        with self.assertRaises(SystemExit):
            self.mod.main()

    # --- Amount validation ---

    @patch.dict(os.environ, {
        "TOYYIBPAY_ENV": "production",
        "CONFIRM_TOYYIBPAY_PRODUCTION_TEST": "YES",
        "SMOKE_TEST_COMPANY_ID": "1",
        "SMOKE_TEST_SUBSCRIPTION_ID": "1",
        "SMOKE_TEST_USER_ID": "3",
        "SMOKE_TEST_CUSTOMER_NAME": "Test User",
        "SMOKE_TEST_CUSTOMER_EMAIL": "test@example.com",
        "SMOKE_TEST_AMOUNT_MICRO_MYR": "100000",
    }, clear=True)
    def test_refuses_amount_below_minimum(self):
        with self.assertRaises(SystemExit):
            self.mod.main()

    @patch.dict(os.environ, {
        "TOYYIBPAY_ENV": "production",
        "CONFIRM_TOYYIBPAY_PRODUCTION_TEST": "YES",
        "SMOKE_TEST_COMPANY_ID": "1",
        "SMOKE_TEST_SUBSCRIPTION_ID": "1",
        "SMOKE_TEST_USER_ID": "3",
        "SMOKE_TEST_CUSTOMER_NAME": "Test User",
        "SMOKE_TEST_CUSTOMER_EMAIL": "test@example.com",
        "SMOKE_TEST_AMOUNT_MICRO_MYR": "1999999",
    }, clear=True)
    def test_refuses_amount_non_divisible(self):
        with self.assertRaises(SystemExit):
            self.mod.main()

    @patch.dict(os.environ, {
        "TOYYIBPAY_ENV": "production",
        "CONFIRM_TOYYIBPAY_PRODUCTION_TEST": "YES",
        "SMOKE_TEST_COMPANY_ID": "1",
        "SMOKE_TEST_SUBSCRIPTION_ID": "1",
        "SMOKE_TEST_USER_ID": "3",
        "SMOKE_TEST_CUSTOMER_NAME": "Test User",
        "SMOKE_TEST_CUSTOMER_EMAIL": "test@example.com",
    }, clear=True)
    def test_refuses_amount_missing(self):
        with self.assertRaises(SystemExit):
            self.mod.main()

    @patch.dict(os.environ, {
        "TOYYIBPAY_ENV": "production",
        "CONFIRM_TOYYIBPAY_PRODUCTION_TEST": "YES",
        "SMOKE_TEST_COMPANY_ID": "1",
        "SMOKE_TEST_SUBSCRIPTION_ID": "1",
        "SMOKE_TEST_USER_ID": "3",
        "SMOKE_TEST_CUSTOMER_NAME": "Test User",
        "SMOKE_TEST_CUSTOMER_EMAIL": "test@example.com",
        "SMOKE_TEST_AMOUNT_MICRO_MYR": "0",
    }, clear=True)
    def test_refuses_amount_zero(self):
        with self.assertRaises(SystemExit):
            self.mod.main()

    # --- Successful flow via DI ---

    def _make_mock_result(self, **overrides):
        result = {
            "status": "pending",
            "order_reference": "11111111-1111-4111-8111-111111111111",
            "checkout_url": "https://toyyibpay.com/ABC123",
            "gateway_order_id": "ABC123",
            "amount_micro_myr": 2000000,
            "currency": "MYR",
            "payment_gateway": "toyyibpay",
            "expires_at": None,
        }
        result.update(overrides)
        return result

    @patch.dict(os.environ, {
        "TOYYIBPAY_ENV": "production",
        "CONFIRM_TOYYIBPAY_PRODUCTION_TEST": "YES",
        "SMOKE_TEST_COMPANY_ID": "1",
        "SMOKE_TEST_SUBSCRIPTION_ID": "1",
        "SMOKE_TEST_USER_ID": "3",
        "SMOKE_TEST_CUSTOMER_NAME": "Test User",
        "SMOKE_TEST_CUSTOMER_EMAIL": "test@example.com",
        "SMOKE_TEST_AMOUNT_MICRO_MYR": "2000000",
    }, clear=True)
    def test_accepts_rm2(self):
        mock_service = MagicMock(return_value=self._make_mock_result())
        try:
            self.mod.main(checkout_service=mock_service)
        except SystemExit as e:
            if e.code != 0:
                raise
        mock_service.assert_called_once()

    @patch.dict(os.environ, {
        "TOYYIBPAY_ENV": "production",
        "CONFIRM_TOYYIBPAY_PRODUCTION_TEST": "YES",
        "SMOKE_TEST_COMPANY_ID": "1",
        "SMOKE_TEST_SUBSCRIPTION_ID": "1",
        "SMOKE_TEST_USER_ID": "3",
        "SMOKE_TEST_CUSTOMER_NAME": "Test User",
        "SMOKE_TEST_CUSTOMER_EMAIL": "test@example.com",
        "SMOKE_TEST_CUSTOMER_PHONE": "+60123456789",
        "SMOKE_TEST_AMOUNT_MICRO_MYR": "2000000",
    }, clear=True)
    def test_calls_checkout_service_with_correct_params(self):
        mock_service = MagicMock(return_value=self._make_mock_result())
        try:
            self.mod.main(checkout_service=mock_service)
        except SystemExit as e:
            if e.code != 0:
                raise
        mock_service.assert_called_once()
        _, kwargs = mock_service.call_args
        self.assertEqual(kwargs["company_id"], 1)
        self.assertEqual(kwargs["subscription_id"], 1)
        self.assertEqual(kwargs["created_by_user_id"], 3)
        self.assertEqual(kwargs["customer_name"], "Test User")
        self.assertEqual(kwargs["customer_email"], "test@example.com")
        self.assertEqual(kwargs["customer_phone"], "+60123456789")
        self.assertEqual(kwargs["amount_micro_myr"], 2000000)

    @patch("sys.stdout")
    @patch.dict(os.environ, {
        "TOYYIBPAY_ENV": "production",
        "CONFIRM_TOYYIBPAY_PRODUCTION_TEST": "YES",
        "SMOKE_TEST_COMPANY_ID": "1",
        "SMOKE_TEST_SUBSCRIPTION_ID": "1",
        "SMOKE_TEST_USER_ID": "3",
        "SMOKE_TEST_CUSTOMER_NAME": "Test User",
        "SMOKE_TEST_CUSTOMER_EMAIL": "test@example.com",
        "SMOKE_TEST_AMOUNT_MICRO_MYR": "2000000",
        "TOYYIBPAY_USER_SECRET_KEY": "super-secret-prod-value-456",
        "TOYYIBPAY_CATEGORY_CODE": "cat-secret-prod",
        "TOYYIBPAY_CALLBACK_URL": "https://secret-callback.test",
    }, clear=True)
    def test_prints_safe_fields_only(self, mock_stdout):
        """Prints safe checkout fields, never secrets."""
        mock_service = MagicMock(return_value=self._make_mock_result())
        try:
            self.mod.main(checkout_service=mock_service)
        except SystemExit as e:
            if e.code != 0:
                raise
        written = ""
        for call_args in mock_stdout.write.call_args_list:
            written += str(call_args[0][0])
        # Safe fields appear
        self.assertIn("11111111-1111-4111-8111-111111111111", written)
        self.assertIn("https://toyyibpay.com/ABC123", written)
        self.assertIn("ABC123", written)
        # Secrets never appear
        self.assertNotIn("super-secret-prod-value-456", written)
        self.assertNotIn("cat-secret-prod", written)
        self.assertNotIn("https://secret-callback.test", written)
        # Customer details not printed
        self.assertNotIn("test@example.com", written)
        self.assertNotIn("Test User", written)

    # --- Safety checks (source inspection) ---

    def test_never_calls_credit_apply(self):
        import inspect
        source = inspect.getsource(self.mod)
        self.assertNotIn("add_company_ai_credit_topup", source)
        self.assertNotIn("mark_order_paid", source)
        self.assertNotIn("mark_order_credited", source)

    def test_never_calls_callback_service(self):
        import inspect
        source = inspect.getsource(self.mod)
        self.assertNotIn("process_topup_payment_callback", source)
        self.assertNotIn("verify_callback_hash", source)

if __name__ == "__main__":
    unittest.main()
