"""Signed HitPay event webhook tests; no network or live payment calls."""

import json
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from app import create_app


_ROUTE = "app.routes.hitpay_routes"


class TestHitPayWebhook(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.raw = json.dumps({
            "id": "hp-request-1",
            "status": "completed",
            "reference_number": "order-1",
        }, separators=(",", ":")).encode()
        self.headers = {
            "Content-Type": "application/json",
            "Hitpay-Signature": "signature",
            "Hitpay-Event-Type": "completed",
            "Hitpay-Event-Object": "payment_request",
        }
        self.config = SimpleNamespace(
            webhook_salt="salt",
            validate_for_webhook=lambda: None,
        )

    def test_route_is_registered(self):
        rules = {rule.rule for rule in self.client.application.url_map.iter_rules()}
        self.assertIn("/api/billing/hitpay/webhook", rules)

    def test_invalid_signature_is_rejected_before_status_lookup(self):
        with (
            patch(_ROUTE + ".HitPayConfig.from_env", return_value=self.config),
            patch(_ROUTE + ".verify_webhook_signature", return_value=False),
            patch(_ROUTE + ".get_payment_request") as lookup,
        ):
            response = self.client.post(
                "/api/billing/hitpay/webhook", data=self.raw, headers=self.headers
            )

        self.assertEqual(response.status_code, 401)
        lookup.assert_not_called()

    def test_completed_event_verifies_exact_bytes_then_refetches_status(self):
        authoritative = {"id": "hp-request-1", "status": "completed"}
        with (
            patch(_ROUTE + ".HitPayConfig.from_env", return_value=self.config),
            patch(_ROUTE + ".verify_webhook_signature", return_value=True) as verify,
            patch(_ROUTE + ".get_payment_request", return_value=authoritative) as lookup,
            patch(_ROUTE + ".process_hitpay_payment_request", return_value={
                "status": "activated", "order_reference": "order-1"
            }) as process,
        ):
            response = self.client.post(
                "/api/billing/hitpay/webhook", data=self.raw, headers=self.headers
            )

        self.assertEqual(response.status_code, 200)
        verify.assert_called_once_with(self.raw, "signature", "salt")
        lookup.assert_called_once_with(self.config, "hp-request-1")
        process.assert_called_once_with(authoritative)

    def test_signed_unrelated_event_is_ignored(self):
        headers = dict(self.headers, **{
            "Hitpay-Event-Type": "created",
            "Hitpay-Event-Object": "charge",
        })
        with (
            patch(_ROUTE + ".HitPayConfig.from_env", return_value=self.config),
            patch(_ROUTE + ".verify_webhook_signature", return_value=True),
            patch(_ROUTE + ".get_payment_request") as lookup,
        ):
            response = self.client.post(
                "/api/billing/hitpay/webhook", data=self.raw, headers=headers
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ignored")
        lookup.assert_not_called()

    def test_oversized_bodies_are_bounded_before_signature_or_provider_work(self):
        from app.routes.hitpay_routes import _MAX_WEBHOOK_BYTES

        for declared_length in (True, False):
            with self.subTest(declared_length=declared_length):
                body = BytesIO(b"x" * (_MAX_WEBHOOK_BYTES + 2))
                with (
                    patch(_ROUTE + ".HitPayConfig.from_env") as config,
                    patch(_ROUTE + ".verify_webhook_signature") as verify,
                    patch(_ROUTE + ".get_payment_request") as lookup,
                ):
                    response = self.client.post(
                        "/api/billing/hitpay/webhook",
                        headers=self.headers,
                        environ_overrides={
                            "wsgi.input": body,
                            "CONTENT_LENGTH": str(_MAX_WEBHOOK_BYTES + 2) if declared_length else "",
                            "wsgi.input_terminated": True,
                        },
                    )

                self.assertEqual(response.status_code, 413)
                self.assertEqual(body.tell(), 0 if declared_length else _MAX_WEBHOOK_BYTES + 1)
                config.assert_not_called()
                verify.assert_not_called()
                lookup.assert_not_called()

    def test_body_at_limit_preserves_exact_signature_bytes(self):
        from app.routes.hitpay_routes import _MAX_WEBHOOK_BYTES

        raw = self.raw.ljust(_MAX_WEBHOOK_BYTES, b" ")
        with (
            patch(_ROUTE + ".HitPayConfig.from_env", return_value=self.config),
            patch(_ROUTE + ".verify_webhook_signature", return_value=True) as verify,
            patch(_ROUTE + ".get_payment_request", return_value={"id": "hp-request-1"}),
            patch(_ROUTE + ".process_hitpay_payment_request", return_value={"status": "activated"}),
        ):
            response = self.client.post(
                "/api/billing/hitpay/webhook", data=raw, headers=self.headers
            )

        self.assertEqual(response.status_code, 200)
        verify.assert_called_once_with(raw, "signature", "salt")

    def test_temporary_status_lookup_failure_returns_retryable_error(self):
        from app.services.hitpay_service import HitPayAPIError

        with (
            patch(_ROUTE + ".HitPayConfig.from_env", return_value=self.config),
            patch(_ROUTE + ".verify_webhook_signature", return_value=True),
            patch(_ROUTE + ".get_payment_request", side_effect=HitPayAPIError("offline")),
        ):
            response = self.client.post(
                "/api/billing/hitpay/webhook", data=self.raw, headers=self.headers
            )

        self.assertEqual(response.status_code, 500)

    def test_configuration_failure_returns_retryable_error(self):
        from app.services.hitpay_service import HitPayConfigError

        with (
            patch(_ROUTE + ".HitPayConfig.from_env", side_effect=HitPayConfigError("missing salt")),
            patch(_ROUTE + ".get_payment_request") as lookup,
        ):
            response = self.client.post(
                "/api/billing/hitpay/webhook", data=self.raw, headers=self.headers
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["message"], "Temporary processing failure.")
        lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
