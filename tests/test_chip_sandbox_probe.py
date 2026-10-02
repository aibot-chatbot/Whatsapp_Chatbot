"""The standalone sandbox probe never imports the app or uses live credentials."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from scripts import chip_sandbox_probe as probe


PURCHASE_ID = "00000000-0000-4000-8000-000000000001"
BRAND_ID = "00000000-0000-4000-8000-000000000002"


class TestChipSandboxProbe(unittest.TestCase):
    def setUp(self):
        self.adapter = probe._load_adapter()
        self.env = {
            "CHIP_TEST_API_KEY": "synthetic-test-key", "CHIP_TEST_BRAND_ID": BRAND_ID,
            "CHIP_REDIRECT_URL": "https://example.test/billing.html",
            "CHIP_WEBHOOK_URL": "https://example.test/api/billing/chip/callback",
        }
        self.purchase = {
            "id": PURCHASE_ID, "type": "purchase", "reference": "test-order",
            "brand_id": BRAND_ID, "is_test": True, "status": "created",
            "purchase": {"currency": "MYR", "total": 101}, "payment": None,
            "marked_as_paid": False, "force_recurring": False, "skip_capture": False,
            "checkout_url": f"https://gate.chip-in.asia/p/{PURCHASE_ID}/",
            "client": {"email": "not-in-output@example.test"},
        }

    def run_probe(self, args=(), env=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, self.env if env is None else env, clear=True), patch.object(probe, "_load_adapter", return_value=self.adapter), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = probe.main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_default_only_reads_public_key_and_does_not_claim_mode_verified(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        response = MagicMock(status_code=200)
        response.json.return_value = pem
        with patch.object(self.adapter.requests, "get", return_value=response) as get, patch.object(self.adapter.requests, "post") as post:
            code, output, errors = self.run_probe()
        self.assertEqual(code, 0)
        self.assertFalse(errors)
        self.assertEqual(json.loads(output), {"public_key_valid": True, "test_mode_requested": True, "purchase_mode_verified": False})
        self.assertEqual(get.call_args.args[0], "https://gate.chip-in.asia/api/v1/public_key/")
        post.assert_not_called()
        self.assertNotIn("BEGIN PUBLIC KEY", output)

    def test_creation_is_explicit_synthetic_and_disables_receipts(self):
        def create_response(*args, **kwargs):
            response = MagicMock(status_code=201)
            response.json.return_value = self.purchase | {"reference": kwargs["json"]["reference"]}
            return response
        with patch.object(self.adapter.requests, "post", side_effect=create_response) as post:
            code, output, errors = self.run_probe(["--create-checkout"])
        self.assertEqual(code, 0)
        self.assertFalse(errors)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["purchase"]["products"][0]["price"], 101)
        self.assertEqual(payload["client"], {"full_name": "Integration Test", "email": "chip-test@example.com"})
        self.assertFalse(payload["send_receipt"])
        self.assertFalse(payload["force_recurring"])
        self.assertEqual(json.loads(output)["purchase_id"], PURCHASE_ID)
        self.assertNotIn("example.com", output)
        self.assertEqual(post.call_count, 1)

    def test_retrieve_outputs_only_normalized_test_payment_proof(self):
        response = MagicMock(status_code=200)
        response.json.return_value = self.purchase | {
            "status": "paid", "payment": {
                "amount": 101, "currency": "MYR", "is_outgoing": False,
                "payment_type": "purchase", "paid_on": 1700000000,
            },
        }
        with patch.object(self.adapter.requests, "get", return_value=response), patch.object(self.adapter.requests, "post") as post:
            code, output, errors = self.run_probe(["--purchase-id", PURCHASE_ID])
        self.assertEqual(code, 0)
        self.assertFalse(errors)
        self.assertTrue(json.loads(output)["paid"])
        self.assertTrue(json.loads(output)["brand_validated"])
        self.assertNotIn("not-in-output", output)
        self.assertNotIn("reference", output)
        post.assert_not_called()

    def test_retrieve_rejects_live_mode_or_unexpected_brand(self):
        for changes in ({"is_test": False}, {"brand_id": "00000000-0000-4000-8000-000000000003"}):
            response = MagicMock(status_code=200)
            response.json.return_value = self.purchase | changes
            with self.subTest(changes=changes), patch.object(self.adapter.requests, "get", return_value=response):
                code, output, errors = self.run_probe(["--purchase-id", PURCHASE_ID])
            self.assertEqual(code, 1)
            self.assertFalse(output)
            self.assertFalse(json.loads(errors)["ok"])

    def test_missing_test_key_or_explicit_live_environment_never_sends_http(self):
        for env in ({"CHIP_LIVE_API_KEY": "synthetic-live-key", "CHIP_BRAND_ID": BRAND_ID}, self.env | {"CHIP_ENV": "live"}):
            with self.subTest(env_keys=list(env)), patch.object(self.adapter.requests, "get") as get, patch.object(self.adapter.requests, "post") as post:
                code, output, errors = self.run_probe(["--create-checkout"], env)
                self.assertEqual(code, 1)
                self.assertFalse(output)
                self.assertNotIn("synthetic", errors)
                get.assert_not_called()
                post.assert_not_called()

    def test_ambiguous_create_reports_manual_reconciliation_without_raw_errors(self):
        with patch.object(self.adapter.requests, "post", side_effect=self.adapter.requests.Timeout("private-token-data")) as post:
            code, output, errors = self.run_probe(["--create-checkout"])
        self.assertEqual(code, 1)
        self.assertFalse(output)
        self.assertEqual(json.loads(errors), {"ok": False, "manual_reconciliation_required": True})
        self.assertNotIn("private-token-data", errors)
        self.assertEqual(post.call_count, 1)

    def test_standalone_adapter_import_does_not_load_flask_database_or_dotenv(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-c", "import runpy, sys; p=runpy.run_path('scripts/chip_sandbox_probe.py'); p['_load_adapter'](); assert not any(n == 'app' or n.startswith('app.') or n == 'flask' or n == 'dotenv' for n in sys.modules)"],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, "Standalone adapter imports must not initialize the application")
        self.assertFalse(result.stdout)


if __name__ == "__main__":
    unittest.main()
