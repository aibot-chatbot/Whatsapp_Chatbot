"""CHIP adapter regression checks; all provider HTTP calls use mocks."""

import base64
import os
import unittest
from copy import deepcopy
from dataclasses import replace
from unittest.mock import MagicMock, patch

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from app.services import chip_service as chip


PURCHASE_ID = "00000000-0000-4000-8000-000000000001"
BRAND_ID = "00000000-0000-4000-8000-000000000002"
OTHER_ID = "00000000-0000-4000-8000-000000000003"


class TestChipService(unittest.TestCase):
    def setUp(self):
        chip._cached_public_key.cache_clear()
        self.addCleanup(chip._cached_public_key.cache_clear)
        self.config = chip.ChipConfig(
            enabled=True, api_key="synthetic-test-key", brand_id=BRAND_ID,
            redirect_url="https://example.test/billing.html",
            webhook_url="https://example.test/api/billing/chip/callback",
        )
        self.purchase = {
            "id": PURCHASE_ID, "type": "purchase", "reference": "subscription-1",
            "brand_id": BRAND_ID, "is_test": True, "status": "created",
            "purchase": {"currency": "MYR", "total": 3900},
            "payment": None, "marked_as_paid": False, "force_recurring": False,
            "skip_capture": False, "checkout_url": f"https://gate.chip-in.asia/p/{PURCHASE_ID}/",
        }
        self.create_args = dict(
            order_reference="subscription-1", amount_sen=3900, description="Essential subscription",
            customer_name="Test Customer", customer_email="test@example.test", customer_phone=None,
        )

    def paid_purchase(self):
        purchase = deepcopy(self.purchase)
        purchase.update(status="paid", checkout_url=None, payment={
            "amount": 3900, "currency": "MYR", "is_outgoing": False,
            "payment_type": "purchase", "paid_on": 1700000000,
        })
        return purchase

    def test_config_defaults_to_disabled_test_mode_and_separates_keys(self):
        with patch.dict(os.environ, {}, clear=True):
            config = chip.ChipConfig.from_env()
        self.assertTrue(config.is_test)
        self.assertFalse(config.enabled)
        with patch.dict(os.environ, {
            "CHIP_ENABLED": "true", "CHIP_TEST_API_KEY": "synthetic-test-key",
            "CHIP_LIVE_API_KEY": "synthetic-live-key", "CHIP_BRAND_ID": BRAND_ID,
        }, clear=True):
            config = chip.ChipConfig.from_env()
            self.assertEqual(config.api_key, "synthetic-test-key")
            self.assertNotIn(config.api_key, repr(config))
            os.environ["CHIP_ENV"] = "live"
            live_config = chip.ChipConfig.from_env()
            self.assertEqual(live_config.api_key, "synthetic-live-key")
            with self.assertRaises(chip.ChipConfigError):
                live_config.validate_for_api()
            os.environ["CHIP_LIVE_ENABLED"] = "true"
            chip.ChipConfig.from_env().validate_for_api()

    def test_live_mode_never_falls_back_to_test_or_generic_key(self):
        with patch.dict(os.environ, {
            "CHIP_ENABLED": "true", "CHIP_ENV": "live", "CHIP_LIVE_ENABLED": "true",
            "CHIP_TEST_API_KEY": "synthetic-test-key", "CHIP_COLLECT_SECRET_KEY": "synthetic-generic-key",
            "CHIP_BRAND_ID": BRAND_ID,
        }, clear=True):
            with self.assertRaises(chip.ChipConfigError):
                chip.ChipConfig.from_env().validate_for_api()

    def test_each_mode_prefers_its_own_callback_and_webhook_public_key(self):
        # CHIP test and live are separate signing datasets. A single shared key
        # variable silently verifies live callbacks against the test key.
        shared = {
            "CHIP_ENABLED": "true", "CHIP_LIVE_ENABLED": "true", "CHIP_BRAND_ID": BRAND_ID,
            "CHIP_CALLBACK_PUBLIC_KEY": "shared-callback-key",
            "CHIP_WEBHOOK_PUBLIC_KEY": "shared-webhook-key",
            "CHIP_LIVE_CALLBACK_PUBLIC_KEY": "live-callback-key",
            "CHIP_LIVE_WEBHOOK_PUBLIC_KEY": "live-webhook-key",
        }
        with patch.dict(os.environ, {**shared, "CHIP_ENV": "live"}, clear=True):
            live = chip.ChipConfig.from_env()
        self.assertEqual(live.callback_public_key, "live-callback-key")
        self.assertEqual(live.webhook_public_key, "live-webhook-key")
        with patch.dict(os.environ, {**shared, "CHIP_ENV": "test"}, clear=True):
            test = chip.ChipConfig.from_env()
        self.assertEqual(test.callback_public_key, "shared-callback-key")
        self.assertEqual(test.webhook_public_key, "shared-webhook-key")
        # The unprefixed name stays a fallback so an existing deployment keeps verifying.
        with patch.dict(os.environ, {
            k: v for k, v in {**shared, "CHIP_ENV": "live"}.items() if "LIVE_CALLBACK" not in k
        }, clear=True):
            self.assertEqual(chip.ChipConfig.from_env().callback_public_key, "shared-callback-key")
        self.assertNotIn("live-callback-key", repr(live))

    def test_success_callback_url_must_not_target_the_webhook_endpoint(self):
        # success_callback payloads are signed with the company key, so a /webhook
        # target would be checked against a key CHIP never used for them.
        for url in (
            "https://example.test/api/billing/chip/webhook",
            "https://example.test/api/billing/chip/webhook/",
        ):
            with self.subTest(url=url), self.assertRaises(chip.ChipConfigError):
                replace(self.config, webhook_url=url).validate_for_checkout()
        replace(self.config, webhook_url="https://example.test/api/billing/chip/callback").validate_for_checkout()

    def test_config_rejects_invalid_mode_boolean_and_unsafe_redirects(self):
        for values in ({"CHIP_ENV": "staging"}, {"CHIP_ENABLED": "perhaps"}, {"CHIP_LIVE_ENABLED": "maybe"}):
            with self.subTest(values=values), patch.dict(os.environ, values, clear=True):
                with self.assertRaises(chip.ChipConfigError):
                    chip.ChipConfig.from_env()
        for url in ("http://example.test", "https://user:pass@example.test", "https://example.test/#secret", "https://example.test:444/", "https://example.test/\n"):
            with self.subTest(url=url), self.assertRaises(chip.ChipConfigError):
                replace(self.config, webhook_url=url).validate_for_checkout()

    def test_create_sends_integer_sen_and_server_callbacks_without_redirects(self):
        response = MagicMock(status_code=201)
        response.json.return_value = self.purchase
        with patch.object(chip.requests, "post", return_value=response) as post:
            result = chip.create_purchase(self.config, **self.create_args, due=1900000000)
        self.assertEqual(result["gateway_order_id"], PURCHASE_ID)
        args, kwargs = post.call_args
        self.assertEqual(args, ("https://gate.chip-in.asia/api/v1/purchases/",))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer synthetic-test-key")
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], (5, 20))
        payload = kwargs["json"]
        self.assertEqual(payload["purchase"]["products"][0]["price"], 3900)
        self.assertEqual(payload["purchase"]["currency"], "MYR")
        self.assertTrue(payload["purchase"]["due_strict"])
        self.assertEqual(payload["success_callback"], self.config.webhook_url)
        self.assertEqual(payload["success_redirect"], self.config.redirect_url)
        self.assertFalse(payload["force_recurring"])
        self.assertFalse(payload["skip_capture"])
        self.assertFalse(payload["send_receipt"])
        self.assertNotIn("is_test", payload)  # The selected API key determines mode.

    def test_input_validation_happens_before_http(self):
        for changes in ({"amount_sen": True}, {"amount_sen": 39.0}, {"amount_sen": -1}, {"order_reference": "../admin"}, {"customer_email": "invalid"}, {"customer_name": ""}, {"description": "x" * 257}):
            with self.subTest(changes=changes), patch.object(chip.requests, "post") as post:
                with self.assertRaises(ValueError):
                    chip.create_purchase(self.config, **(self.create_args | changes))
                post.assert_not_called()

    def test_create_timeout_and_ambiguous_statuses_are_never_retried(self):
        for status in (200, 202, 302, 408, 409, 425, 429, 500, 503):
            with self.subTest(status=status), patch.object(chip.requests, "post", return_value=MagicMock(status_code=status)) as post:
                with self.assertRaises(chip.ChipAmbiguousError):
                    chip.create_purchase(self.config, **self.create_args)
                self.assertEqual(post.call_count, 1)
        with patch.object(chip.requests, "post", side_effect=requests.Timeout("private customer information")) as post:
            with self.assertRaises(chip.ChipAmbiguousError) as error:
                chip.create_purchase(self.config, **self.create_args)
            self.assertNotIn("private", str(error.exception))
            self.assertTrue(error.exception.__suppress_context__)
            self.assertEqual(post.call_count, 1)

    def test_definitive_client_rejection_is_distinct(self):
        for status in (400, 401, 403, 404, 422):
            with self.subTest(status=status), patch.object(chip.requests, "post", return_value=MagicMock(status_code=status)):
                with self.assertRaises(chip.ChipRequestRejectedError):
                    chip.create_purchase(self.config, **self.create_args)

    def test_create_rejects_missing_or_mismatched_response_fields(self):
        mutations = (
            {"id": None}, {"id": "../purchases"}, {"brand_id": OTHER_ID}, {"is_test": False},
            {"is_test": "true"}, {"reference": "another-order"}, {"force_recurring": True},
            {"skip_capture": True}, {"status": "sent"}, {"type": "payment"},
            {"purchase": {"currency": "USD", "total": 3900}},
            {"purchase": {"currency": "MYR", "total": 3901}},
            {"purchase": {"currency": "MYR", "total": 3900.0}},
            {"checkout_url": "https://gate.chip-in.asia.evil.test/"},
        )
        for mutation in mutations:
            response = MagicMock(status_code=201)
            response.json.return_value = self.purchase | mutation
            with self.subTest(mutation=mutation), patch.object(chip.requests, "post", return_value=response):
                with self.assertRaises(chip.ChipAmbiguousError):
                    chip.create_purchase(self.config, **self.create_args)
        for body in ([], None, "not an object"):
            response = MagicMock(status_code=201)
            response.json.return_value = body
            with self.subTest(body=body), patch.object(chip.requests, "post", return_value=response):
                with self.assertRaises(chip.ChipAmbiguousError):
                    chip.create_purchase(self.config, **self.create_args)

    def test_checkout_url_rejects_spoofed_origins_credentials_ports_and_controls(self):
        for value in (None, "", "http://gate.chip-in.asia/p/x/", "https://gate.chip-in.asia.evil.test/p/x/", "https://gate.chip-in.asia@evil.test/p/x/", "https://user@gate.chip-in.asia/p/x/", "https://gate.chip-in.asia:444/p/x/", "https://gate.chip-in.asia/p/x/#fragment", "https://gate.chip-in.asia\\@evil.test/", "https://gate.chip-in.asia/p/\nx"):
            with self.subTest(value=value), self.assertRaises(chip.ChipAmbiguousError):
                chip.validate_checkout_url(value)
        self.assertEqual(chip.validate_checkout_url(self.purchase["checkout_url"]), self.purchase["checkout_url"])

    def test_get_validates_ids_before_http_and_binds_mode_brand(self):
        with patch.object(chip.requests, "get") as get:
            with self.assertRaises(ValueError):
                chip.get_purchase(self.config, "../public_key")
            get.assert_not_called()
        for changes in ({"id": OTHER_ID}, {"brand_id": OTHER_ID}, {"is_test": False}):
            response = MagicMock(status_code=200)
            response.json.return_value = self.purchase | changes
            with self.subTest(changes=changes), patch.object(chip.requests, "get", return_value=response):
                with self.assertRaises(chip.ChipAPIError):
                    chip.get_purchase(self.config, PURCHASE_ID)
        response = MagicMock(status_code=200)
        response.json.return_value = self.paid_purchase()
        with patch.object(chip.requests, "get", return_value=response) as get:
            self.assertEqual(chip.get_purchase(self.config, PURCHASE_ID)["status"], "paid")
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_get_rejects_redirects_and_invalid_json(self):
        for status in (302, 401, 429, 500):
            with self.subTest(status=status), patch.object(chip.requests, "get", return_value=MagicMock(status_code=status)):
                with self.assertRaises(chip.ChipAPIError):
                    chip.get_purchase(self.config, PURCHASE_ID)
        response = MagicMock(status_code=200)
        response.json.side_effect = ValueError("private response")
        with patch.object(chip.requests, "get", return_value=response), self.assertRaises(chip.ChipAPIError):
            chip.get_purchase(self.config, PURCHASE_ID)

    def test_only_proven_paid_cleared_or_settled_payments_are_normalized_as_paid(self):
        for status in ("paid", "cleared", "settled"):
            purchase = self.paid_purchase() | {"status": status}
            normalized = chip.normalize_purchase(purchase)
            self.assertTrue(normalized["paid"])
            self.assertEqual(normalized["amount_sen"], 3900)
            self.assertEqual(normalized["payment_reference"], PURCHASE_ID)
            self.assertEqual(normalized["paid_at"], "2023-11-14T22:13:20+00:00")
            self.assertNotIn("client", normalized)
        for status in ("created", "hold", "pending_capture", "preauthorized", "error", "refunded", "chargeback"):
            self.assertFalse(chip.normalize_purchase(self.purchase | {"status": status})["paid"])

    def test_paid_requires_incoming_exact_amount_currency_real_transaction_and_timestamp(self):
        mutations = (
            {"amount": 3901}, {"amount": "3900"}, {"amount": True}, {"currency": "USD"},
            {"is_outgoing": True}, {"is_outgoing": None}, {"payment_type": "refund"},
            {"paid_on": None}, {"paid_on": True}, {"paid_on": 9223372036854775807},
        )
        for mutation in mutations:
            purchase = self.paid_purchase()
            purchase["payment"].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                chip.normalize_purchase(purchase)
        for changes in ({"marked_as_paid": True}, {"marked_as_paid": None}, {"payment": None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                chip.normalize_purchase(self.paid_purchase() | changes)

    def test_signature_checks_exact_body_rsa_key_algorithm_and_base64(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
        raw = b'{"id":"purchase", "is_test":true}'
        signature = base64.b64encode(key.sign(raw, padding.PKCS1v15(), hashes.SHA256())).decode("ascii")
        self.assertTrue(chip.verify_webhook_signature(raw, signature, public_key))
        self.assertFalse(chip.verify_webhook_signature(raw + b" ", signature, public_key))
        for invalid_signature in ("!invalid", "", signature + "\n", None):
            self.assertFalse(chip.verify_webhook_signature(raw, invalid_signature, public_key))
        self.assertFalse(chip.verify_webhook_signature(raw, signature, "malformed PEM"))
        ec_key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
        self.assertFalse(chip.verify_webhook_signature(raw, signature, ec_key))
        pss = base64.b64encode(key.sign(raw, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())).decode("ascii")
        self.assertFalse(chip.verify_webhook_signature(raw, pss, public_key))

    def test_public_key_endpoint_requires_json_encoded_rsa_pem_string(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
        response = MagicMock(status_code=200)
        response.json.return_value = pem
        with patch.object(chip.requests, "get", return_value=response) as get:
            self.assertEqual(chip.get_public_key(self.config), pem)
        self.assertEqual(get.call_args.args[0], "https://gate.chip-in.asia/api/v1/public_key/")
        for invalid in ({"public_key": pem}, None, "invalid"):
            chip._cached_public_key.cache_clear()
            response.json.return_value = invalid
            with self.subTest(invalid=type(invalid)), patch.object(chip.requests, "get", return_value=response):
                with self.assertRaises(chip.ChipAPIError):
                    chip.get_public_key(self.config)

    def test_public_key_cache_bounds_success_and_failure_without_caching_payment_state(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
        response = MagicMock(status_code=200)
        response.json.return_value = pem
        with patch.object(chip.requests, "get", return_value=response) as get, patch.object(chip, "monotonic", return_value=300) as clock:
            for _ in range(20):
                self.assertEqual(chip.get_public_key(self.config), pem)
            self.assertEqual(get.call_count, 1)
            chip.get_public_key(replace(self.config, api_key="another-synthetic-key"))
            self.assertEqual(get.call_count, 2)
            clock.return_value = 600
            response.status_code = 503
            for _ in range(20):
                with self.assertRaises(chip.ChipAPIError):
                    chip.get_public_key(self.config)
            self.assertEqual(get.call_count, 3)
            clock.return_value = 900
            response.status_code = 200
            self.assertEqual(chip.get_public_key(self.config), pem)
            self.assertEqual(get.call_count, 4)
            response.json.return_value = self.paid_purchase()
            chip.get_purchase(self.config, PURCHASE_ID)
            chip.get_purchase(self.config, PURCHASE_ID)
            self.assertEqual(get.call_count, 6)


if __name__ == "__main__":
    unittest.main()
