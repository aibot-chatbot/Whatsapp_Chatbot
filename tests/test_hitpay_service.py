"""Focused unit tests for the server-side HitPay adapter."""

import hashlib
import hmac
import unittest
from unittest.mock import MagicMock, patch

import requests


class TestHitPayService(unittest.TestCase):
    def setUp(self):
        from app.services.hitpay_service import HitPayConfig

        self.config = HitPayConfig(
            enabled=True,
            environment="sandbox",
            api_key="test-api-key",
            webhook_salt="test-webhook-salt",
            redirect_url="https://example.test/billing.html",
            webhook_url="https://example.test/api/billing/hitpay/webhook",
        )

    def test_create_payment_request_uses_hosted_checkout_without_forcing_methods(self):
        from app.services.hitpay_service import create_payment_request

        response = MagicMock(status_code=200)
        response.json.return_value = {
            "id": "9ef68e2e-3569-4f69-9f68-04c7e4bb007c",
            "reference_number": "00000000-0000-4000-8000-000000000001",
            "status": "pending",
            "url": "https://securecheckout.sandbox.hit-pay.com/payment-request/@merchant/id/checkout",
        }
        with patch("app.services.hitpay_service.requests.post", return_value=response) as post:
            result = create_payment_request(
                config=self.config,
                order_reference="00000000-0000-4000-8000-000000000001",
                amount_sen=3900,
                customer_name="Test User",
                customer_email="test@example.com",
                customer_phone=None,
                description="Subscription - Essential",
                expires_after="1 day",
            )

        self.assertEqual(result["gateway_order_id"], "9ef68e2e-3569-4f69-9f68-04c7e4bb007c")
        self.assertEqual(result["checkout_url"], response.json.return_value["url"])
        _, kwargs = post.call_args
        self.assertEqual(kwargs["headers"]["X-BUSINESS-API-KEY"], "test-api-key")
        self.assertEqual(kwargs["json"]["amount"], "39.00")
        self.assertEqual(kwargs["json"]["currency"], "MYR")
        self.assertEqual(kwargs["json"]["reference_number"], "00000000-0000-4000-8000-000000000001")
        self.assertFalse(kwargs["json"]["allow_repeated_payments"])
        self.assertNotIn("payment_methods", kwargs["json"])

    def test_create_timeout_is_ambiguous_and_safe_to_reconcile(self):
        from app.services.hitpay_service import HitPayAmbiguousError, create_payment_request

        with patch(
            "app.services.hitpay_service.requests.post",
            side_effect=requests.Timeout("timed out"),
        ):
            with self.assertRaises(HitPayAmbiguousError):
                create_payment_request(
                    config=self.config,
                    order_reference="00000000-0000-4000-8000-000000000001",
                    amount_sen=3900,
                    customer_name="Test User",
                    customer_email="test@example.com",
                    customer_phone=None,
                    description="Subscription - Essential",
                )

    def test_create_422_is_a_definite_rejection(self):
        from app.services.hitpay_service import HitPayRequestRejectedError, create_payment_request

        response = MagicMock(status_code=422)
        with patch("app.services.hitpay_service.requests.post", return_value=response):
            with self.assertRaises(HitPayRequestRejectedError):
                create_payment_request(
                    config=self.config,
                    order_reference="00000000-0000-4000-8000-000000000001",
                    amount_sen=3900,
                    customer_name="Test User",
                    customer_email="test@example.com",
                    customer_phone=None,
                    description="Subscription - Essential",
                )

    def test_signature_verification_uses_exact_raw_body(self):
        from app.services.hitpay_service import verify_webhook_signature

        raw = b'{"id":"payment-request-1", "status":"completed"}'
        signature = hmac.new(
            b"test-webhook-salt", raw, hashlib.sha256
        ).hexdigest()

        self.assertTrue(verify_webhook_signature(raw, signature, "test-webhook-salt"))
        self.assertFalse(
            verify_webhook_signature(raw.replace(b" ", b""), signature, "test-webhook-salt")
        )

    def test_find_payment_request_searches_exact_internal_reference(self):
        from app.services.hitpay_service import find_payment_request_by_reference

        response = MagicMock(status_code=200)
        response.json.return_value = {
            "data": [
                {"id": "partial", "reference_number": "order-1-extra"},
                {"id": "exact", "reference_number": "order-1"},
            ]
        }
        with patch("app.services.hitpay_service.requests.get", return_value=response) as get:
            result = find_payment_request_by_reference(self.config, "order-1")

        self.assertEqual(result["id"], "exact")
        self.assertEqual(get.call_args.kwargs["params"]["search"], "order-1")

    def test_normalize_completed_request_uses_succeeded_payment_reference(self):
        from app.services.hitpay_service import normalize_payment_request

        normalized = normalize_payment_request({
            "id": "request-1",
            "reference_number": "00000000-0000-4000-8000-000000000001",
            "status": "completed",
            "amount": "39.00",
            "currency": "myr",
            "updated_at": "2026-09-04T10:00:00+08:00",
            "payments": [
                {"id": "payment-1", "status": "succeeded", "updated_at": "2026-09-04T10:00:01+08:00"}
            ],
        })

        self.assertEqual(normalized["payment_gateway"], "hitpay")
        self.assertEqual(normalized["amount_sen"], 3900)
        self.assertEqual(normalized["payment_reference"], "payment-1")
        self.assertTrue(normalized["paid"])


if __name__ == "__main__":
    unittest.main()
