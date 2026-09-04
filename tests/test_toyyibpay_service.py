"""Tests for the ToyyibPay API service."""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("TOYYIBPAY_ENV", "production")
os.environ.setdefault("TOYYIBPAY_USER_SECRET_KEY", "test-secret-key")
os.environ.setdefault("TOYYIBPAY_CATEGORY_CODE", "test-category")
os.environ.setdefault("TOYYIBPAY_CALLBACK_URL", "https://test.ngrok.app/api/billing/toyyibpay/callback")

import sys
import pathlib
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import unittest
from unittest.mock import patch, MagicMock
import requests

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
    from app.services.toyyibpay_service import (
        ToyyibPayConfig,
        ToyyibPayConfigError,
        ToyyibPayBillRejectedError,
        ToyyibPayBillCreationAmbiguousError,
        micro_myr_to_cent,
        create_bill,
        verify_callback_hash,
        parse_verified_callback,
    )


class TestToyyibPayConfig(unittest.TestCase):
    def setUp(self):
        self.env_backup = os.environ.copy()
        os.environ['TOYYIBPAY_ENV'] = 'production'

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env_backup)

    def test_production_env_accepted(self):
        os.environ["TOYYIBPAY_ENV"] = "production"
        cfg = ToyyibPayConfig()
        self.assertTrue(cfg.env == "production")

    def test_production_base_url(self):
        os.environ["TOYYIBPAY_ENV"] = "production"
        cfg = ToyyibPayConfig()
        self.assertEqual(cfg.base_url, "https://toyyibpay.com")

    def test_missing_env_rejected(self):
        del os.environ["TOYYIBPAY_ENV"]
        with self.assertRaises(ToyyibPayConfigError):
            ToyyibPayConfig()

    def test_sandbox_rejected(self):
        os.environ["TOYYIBPAY_ENV"] = "sandbox"
        with self.assertRaises(ToyyibPayConfigError):
            ToyyibPayConfig()

    def test_invalid_env_rejected(self):
        os.environ["TOYYIBPAY_ENV"] = "invalid"
        with self.assertRaises(ToyyibPayConfigError):
            ToyyibPayConfig()

    def test_required_config_for_bill_creation(self):
        os.environ["TOYYIBPAY_USER_SECRET_KEY"] = ""
        os.environ["TOYYIBPAY_CATEGORY_CODE"] = ""
        os.environ["TOYYIBPAY_CALLBACK_URL"] = ""
        cfg = ToyyibPayConfig()
        with self.assertRaises(ToyyibPayConfigError):
            cfg.validate_for_bill_creation()

    def test_required_config_for_hash_verification(self):
        os.environ["TOYYIBPAY_USER_SECRET_KEY"] = ""
        cfg = ToyyibPayConfig()
        with self.assertRaises(ToyyibPayConfigError):
            cfg.validate_for_hash_verification()

class TestToyyibPayAmountConversion(unittest.TestCase):
    def test_valid_conversion(self):
        self.assertEqual(micro_myr_to_cent(1_000_000), 100)
        self.assertEqual(micro_myr_to_cent(100_000), 10)
        self.assertEqual(micro_myr_to_cent(10_000), 1)

    def test_zero_raises(self):
        with self.assertRaises(ValueError):
            micro_myr_to_cent(0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            micro_myr_to_cent(-100)

    def test_non_divisible_raises(self):
        with self.assertRaises(ValueError):
            micro_myr_to_cent(12345)

    def test_boolean_raises(self):
        with self.assertRaises(ValueError):
            micro_myr_to_cent(True)


class TestToyyibPayCreateBill(unittest.TestCase):
    """Bill creation response validation."""

    def setUp(self):
        self.env_backup = os.environ.copy()
        # Production-only: always set production
        os.environ['TOYYIBPAY_ENV'] = 'production'

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env_backup)

    @patch("app.services.toyyibpay_service.requests.post")
    def test_valid_billcode_string(self, mock_post):
        """Valid BillCode string is accepted."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"BillCode": "ABC123"}]
        mock_post.return_value = mock_response

        result = create_bill(
            order_reference="11111111-1111-4111-8111-111111111111",
            amount_micro_myr=1_000_000,
            customer_email="test@example.com",
            customer_name="Test User",
            description="Top-up",
        )

        self.assertEqual(result["gateway_order_id"], "ABC123")
        self.assertIn("checkout_url", result)
        self.assertEqual(result["checkout_url"], 
                         "https://toyyibpay.com/ABC123")

    @patch("app.services.toyyibpay_service.requests.post")
    def test_bill_expiry_days_is_sent_when_provided(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"BillCode": "ABC123"}]
        mock_post.return_value = mock_response

        create_bill(
            order_reference="11111111-1111-4111-8111-111111111111",
            amount_micro_myr=1_000_000,
            customer_email="test@example.com",
            customer_name="Test User",
            description="Top-up",
            bill_expiry_days=1,
        )

        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["data"]["billExpiryDays"], "1")

    def test_invalid_bill_expiry_days_rejected(self):
        with self.assertRaises(ValueError):
            create_bill(
                order_reference="11111111-1111-4111-8111-111111111111",
                amount_micro_myr=1_000_000,
                customer_email="test@example.com",
                customer_name="Test User",
                description="Top-up",
                bill_expiry_days=0,
            )

    @patch("app.services.toyyibpay_service.requests.post")
    def test_provider_error_response_rejected_with_bounded_message(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "error",
            "msg": "billPhone parameter is empty",
        }
        mock_post.return_value = mock_response

        with self.assertRaises(ToyyibPayBillRejectedError) as ctx:
            create_bill(
                order_reference="11111111-1111-4111-8111-111111111111",
                amount_micro_myr=1_000_000,
                customer_email="test@example.com",
                customer_name="Test User",
                description="Top-up",
            )

        self.assertEqual(str(ctx.exception), "ToyyibPay createBill rejected the request")
        self.assertNotIn("billPhone parameter is empty", str(ctx.exception))

    @patch("app.services.toyyibpay_service.requests.post")
    def test_non_json_response_is_ambiguous(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("not json")
        mock_response.text = "not json"
        mock_response.headers = {"Content-Type": "text/plain"}
        mock_post.return_value = mock_response

        with self.assertRaises(ToyyibPayBillCreationAmbiguousError):
            create_bill(
                order_reference="11111111-1111-4111-8111-111111111111",
                amount_micro_myr=1_000_000,
                customer_email="test@example.com",
                customer_name="Test User",
                description="Top-up",
            )

    @patch("app.services.toyyibpay_service.requests.post")
    def test_unexpected_response_structure_is_ambiguous(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}
        mock_post.return_value = mock_response

        with self.assertRaises(ToyyibPayBillCreationAmbiguousError):
            create_bill(
                order_reference="11111111-1111-4111-8111-111111111111",
                amount_micro_myr=1_000_000,
                customer_email="test@example.com",
                customer_name="Test User",
                description="Top-up",
            )

    @patch("app.services.toyyibpay_service.requests.post")
    def test_timeout_is_ambiguous(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout()

        with self.assertRaises(ToyyibPayBillCreationAmbiguousError):
            create_bill(
                order_reference="11111111-1111-4111-8111-111111111111",
                amount_micro_myr=1_000_000,
                customer_email="test@example.com",
                customer_name="Test User",
                description="Top-up",
            )

    @patch("app.services.toyyibpay_service.requests.post")
    def test_connection_error_is_ambiguous(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError("network uncertain")

        with self.assertRaises(ToyyibPayBillCreationAmbiguousError):
            create_bill(
                order_reference="11111111-1111-4111-8111-111111111111",
                amount_micro_myr=1_000_000,
                customer_email="test@example.com",
                customer_name="Test User",
                description="Top-up",
            )


    @patch("app.services.toyyibpay_service.requests.post")
    def test_billcode_with_spaces_normalized(self, mock_post):
        """BillCode with surrounding whitespace is stripped."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"BillCode": "  ABC123  "}]
        mock_post.return_value = mock_response

        result = create_bill(
            order_reference="11111111-1111-4111-8111-111111111111",
            amount_micro_myr=1_000_000,
            customer_email="test@example.com",
            customer_name="Test User",
            description="Top-up",
        )

        self.assertEqual(result["gateway_order_id"], "ABC123")
        self.assertEqual(result["checkout_url"], 
                         "https://toyyibpay.com/ABC123")
    @patch("app.services.toyyibpay_service.requests.post")
    def test_missing_billcode_key_rejected(self, mock_post):
        """Missing BillCode key is rejected."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"other": "val"}]
        mock_post.return_value = mock_response

        with self.assertRaises(RuntimeError):
            create_bill(
                order_reference="11111111-1111-4111-8111-111111111111",
                amount_micro_myr=1_000_000,
                customer_email="test@example.com",
                customer_name="Test User",
                description="Top-up",
            )

    @patch("app.services.toyyibpay_service.requests.post")
    def test_none_billcode_rejected(self, mock_post):
        """BillCode set to None is rejected."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"BillCode": None}]
        mock_post.return_value = mock_response

        with self.assertRaises(RuntimeError):
            create_bill(
                order_reference="11111111-1111-4111-8111-111111111111",
                amount_micro_myr=1_000_000,
                customer_email="test@example.com",
                customer_name="Test User",
                description="Top-up",
            )

    @patch("app.services.toyyibpay_service.requests.post")
    def test_empty_billcode_rejected(self, mock_post):
        """Empty string BillCode is rejected."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"BillCode": ""}]
        mock_post.return_value = mock_response

        with self.assertRaises(RuntimeError):
            create_bill(
                order_reference="11111111-1111-4111-8111-111111111111",
                amount_micro_myr=1_000_000,
                customer_email="test@example.com",
                customer_name="Test User",
                description="Top-up",
            )

    @patch("app.services.toyyibpay_service.requests.post")
    def test_whitespace_only_billcode_rejected(self, mock_post):
        """Whitespace-only BillCode is rejected after stripping."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"BillCode": "   "}]
        mock_post.return_value = mock_response

        with self.assertRaises(RuntimeError):
            create_bill(
                order_reference="11111111-1111-4111-8111-111111111111",
                amount_micro_myr=1_000_000,
                customer_email="test@example.com",
                customer_name="Test User",
                description="Top-up",
            )

    @patch("app.services.toyyibpay_service.requests.post")
    def test_integer_billcode_rejected(self, mock_post):
        """Integer BillCode is rejected."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"BillCode": 123}]
        mock_post.return_value = mock_response

        with self.assertRaises(RuntimeError):
            create_bill(
                order_reference="11111111-1111-4111-8111-111111111111",
                amount_micro_myr=1_000_000,
                customer_email="test@example.com",
                customer_name="Test User",
                description="Top-up",
            )

    @patch("app.services.toyyibpay_service.requests.post")
    def test_boolean_billcode_rejected(self, mock_post):
        """Boolean BillCode is rejected."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"BillCode": True}]
        mock_post.return_value = mock_response

        with self.assertRaises(RuntimeError):
            create_bill(
                order_reference="11111111-1111-4111-8111-111111111111",
                amount_micro_myr=1_000_000,
                customer_email="test@example.com",
                customer_name="Test User",
                description="Top-up",
            )

    @patch("app.services.toyyibpay_service.requests.post")
    def test_non_dict_first_element_rejected(self, mock_post):
        """First response element that is not a dict is rejected."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = ["ABC123"]
        mock_post.return_value = mock_response

        with self.assertRaises(RuntimeError):
            create_bill(
                order_reference="11111111-1111-4111-8111-111111111111",
                amount_micro_myr=1_000_000,
                customer_email="test@example.com",
                customer_name="Test User",
                description="Top-up",
            )

    @patch("app.services.toyyibpay_service.requests.post")
    def test_empty_response_list_rejected(self, mock_post):
        """Empty response list is rejected."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_post.return_value = mock_response

        with self.assertRaises(RuntimeError):
            create_bill(
                order_reference="11111111-1111-4111-8111-111111111111",
                amount_micro_myr=1_000_000,
                customer_email="test@example.com",
                customer_name="Test User",
                description="Top-up",
            )

    @patch("app.services.toyyibpay_service.requests.post")
    def test_non_list_response_rejected(self, mock_post):
        """Non-list response is rejected."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"BillCode": "ABC123"}
        mock_post.return_value = mock_response

        with self.assertRaises(RuntimeError):
            create_bill(
                order_reference="11111111-1111-4111-8111-111111111111",
                amount_micro_myr=1_000_000,
                customer_email="test@example.com",
                customer_name="Test User",
                description="Top-up",
            )

    @patch("app.services.toyyibpay_service.requests.post")
    def test_malformed_json_rejected(self, mock_post):
        """Non-JSON response is rejected."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("No JSON")
        mock_post.return_value = mock_response

        with self.assertRaises(RuntimeError):
            create_bill(
                order_reference="11111111-1111-4111-8111-111111111111",
                amount_micro_myr=1_000_000,
                customer_email="test@example.com",
                customer_name="Test User",
                description="Top-up",
            )

    @patch("app.services.toyyibpay_service.requests.post")
    def test_http_failure_rejected(self, mock_post):
        """HTTP error is rejected."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 500
        mock_response.text = "Server error"
        mock_post.return_value = mock_response

        with self.assertRaises(RuntimeError):
            create_bill(
                order_reference="11111111-1111-4111-8111-111111111111",
                amount_micro_myr=1_000_000,
                customer_email="test@example.com",
                customer_name="Test User",
                description="Top-up",
            )

class TestToyyibPayCallbackHash(unittest.TestCase):
    def setUp(self):
        self.env_backup = os.environ.copy()
        # Production-only: always set production
        os.environ['TOYYIBPAY_ENV'] = 'production'

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env_backup)

    def _make_config(self):
        os.environ["TOYYIBPAY_USER_SECRET_KEY"] = "test-secret"
        return ToyyibPayConfig()

    def test_valid_hash_passes(self):
        import hashlib
        config = self._make_config()
        payload = {
            "status": "1",
            "order_id": "11111111-1111-4111-8111-111111111111",
            "refno": "REF123",
            "hash": hashlib.md5(
                ("test-secret" + "1" + "11111111-1111-4111-8111-111111111111" + "REF123" + "ok").encode()
            ).hexdigest(),
        }
        self.assertTrue(verify_callback_hash(config, payload))

    def test_invalid_hash_fails(self):
        config = self._make_config()
        payload = {
            "status": "1",
            "order_id": "11111111-1111-4111-8111-111111111111",
            "refno": "REF123",
            "hash": "invalidhash",
        }
        self.assertFalse(verify_callback_hash(config, payload))

    def test_missing_fields_raises(self):
        config = self._make_config()
        with self.assertRaises(ValueError):
            verify_callback_hash(config, {})

    def test_missing_hash_field_raises(self):
        config = self._make_config()
        with self.assertRaises(ValueError):
            verify_callback_hash(config, {"status": "1", "order_id": "abc", "refno": "123"})


class TestToyyibPayCallbackParsing(unittest.TestCase):
    def _callback(self, **overrides):
        payload = {
            "billcode": "BC123",
            "order_id": "11111111-1111-4111-8111-111111111111",
            "refno": "REF123",
            "status": "1",
            "amount": "100",
            "transaction_time": "2026-07-30 12:05:00",
            "reason": "",
        }
        payload.update(overrides)
        return payload

    def test_status_1_is_paid(self):
        result = parse_verified_callback(self._callback(status="1"))
        self.assertTrue(result["paid"])
        self.assertEqual(result["payment_gateway"], "toyyibpay")
        self.assertEqual(result["gateway_order_id"], "BC123")

    def test_status_2_is_not_paid(self):
        result = parse_verified_callback(self._callback(status="2"))
        self.assertFalse(result["paid"])

    def test_status_3_is_not_paid(self):
        result = parse_verified_callback(self._callback(status="3"))
        self.assertFalse(result["paid"])

    def test_missing_billcode_raises(self):
        with self.assertRaises(ValueError):
            parse_verified_callback(self._callback(billcode=""))

    def test_missing_order_id_raises(self):
        with self.assertRaises(ValueError):
            parse_verified_callback(self._callback(order_id=""))

    def test_missing_refno_raises(self):
        with self.assertRaises(ValueError):
            parse_verified_callback(self._callback(refno=""))

    def test_amount_decimal_300(self):
        """Callback amount 3.00 parses to 300 cent."""
        result = parse_verified_callback(self._callback(amount="3.00"))
        self.assertEqual(result["amount_sen"], 300)
        self.assertEqual(result["paid_total_micro_myr"], 3000000)

    def test_amount_decimal_200(self):
        """Callback amount '2.00' parses correctly."""
        result = parse_verified_callback(self._callback(amount="2.00"))
        self.assertEqual(result["amount_sen"], 200)

    def test_amount_integer_parsed(self):
        """Callback amount '250' parsed as MYR 250.00 -> 25000 cent."""
        result = parse_verified_callback(self._callback(amount="250"))
        self.assertEqual(result["amount_sen"], 25000)

    def test_amount_decimal_one_fifty(self):
        """Callback amount '1.50' parses to 150 cent."""
        result = parse_verified_callback(self._callback(amount="1.50"))
        self.assertEqual(result["amount_sen"], 150)

    def test_amount_malformed_rejected(self):
        """Malformed decimal amount is rejected."""
        with self.assertRaises(ValueError):
            parse_verified_callback(self._callback(amount="not-a-number"))

    def test_amount_three_decimal_places_rejected(self):
        """More than two decimal places rejected."""
        with self.assertRaises(ValueError):
            parse_verified_callback(self._callback(amount="3.000"))

    def test_amount_negative_rejected(self):
        with self.assertRaises(ValueError):
            parse_verified_callback(self._callback(amount="-1"))

    def test_amount_zero_rejected(self):
        with self.assertRaises(ValueError):
            parse_verified_callback(self._callback(amount="0"))

    def test_amount_boolean_rejected(self):
        with self.assertRaises(ValueError):
            parse_verified_callback(self._callback(amount=True))

    def test_transaction_time_present(self):
        result = parse_verified_callback(self._callback(transaction_time="2026-07-30 12:05:00"))
        self.assertEqual(result["paid_at"], "2026-07-30 12:05:00")

    def test_failure_reason_propagated(self):
        result = parse_verified_callback(self._callback(reason="Insufficient funds", status="3"))
        self.assertEqual(result["failure_reason"], "Insufficient funds")




class TestToyyibPayNonJsonDiagnostic(unittest.TestCase):
    """Non-JSON response error message includes diagnostic info."""

    def setUp(self):
        self.env_backup = os.environ.copy()
        # Production-only: always set production
        os.environ['TOYYIBPAY_ENV'] = 'production'

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env_backup)

    def _call_create_bill(self, mock_response):
        with patch("app.services.toyyibpay_service.requests.post") as mock_post:
            mock_post.return_value = mock_response
            with self.assertRaises(RuntimeError) as ctx:
                create_bill(
                    order_reference="11111111-1111-4111-8111-111111111111",
                    amount_micro_myr=1_000_000,
                    customer_email="test@example.com",
                    customer_name="Test User",
                    description="Top-up",
                )
            return str(ctx.exception)

    def test_non_json_includes_status(self):
        """Error message includes HTTP status code."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "not json"
        mock_response.json.side_effect = ValueError("No JSON")
        mock_response.headers = {"Content-Type": "text/html"}
        msg = self._call_create_bill(mock_response)
        self.assertIn("HTTP 200", msg)

    def test_non_json_includes_content_type(self):
        """Error message includes Content-Type."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "not json"
        mock_response.json.side_effect = ValueError("No JSON")
        mock_response.headers = {"Content-Type": "text/html"}
        msg = self._call_create_bill(mock_response)
        self.assertIn("text/html", msg)

    def test_non_json_body_truncated(self):
        """Response body is truncated to 300 chars."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "x" * 500
        mock_response.json.side_effect = ValueError("No JSON")
        mock_response.headers = {"Content-Type": "text/html"}
        msg = self._call_create_bill(mock_response)
        self.assertIn("x" * 300, msg)
        self.assertNotIn("x" * 301, msg)

    def test_non_json_secret_not_in_message(self):
        """Secret key is never present in error message."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "not json"
        mock_response.json.side_effect = ValueError("No JSON")
        mock_response.headers = {"Content-Type": "text/html"}
        msg = self._call_create_bill(mock_response)
        self.assertNotIn("test-secret", msg)

    def test_non_json_customer_not_in_message(self):
        """Customer email and name never in error message."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "not json"
        mock_response.json.side_effect = ValueError("No JSON")
        mock_response.headers = {"Content-Type": "text/html"}
        msg = self._call_create_bill(mock_response)
        self.assertNotIn("test@example.com", msg)

if __name__ == "__main__":
    unittest.main()



