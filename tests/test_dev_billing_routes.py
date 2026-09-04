"""test_dev_billing_routes.py

Unit tests for dev-only billing route registration.
Ensures that:
- The dev billing blueprint is NOT registered in production config.
- The dev billing blueprint IS registered when ENABLE_DEV_BILLING_ROUTES is true.
- Production cannot enable dev billing routes.
- Normal billing routes are always registered.
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
import types
from unittest.mock import patch, MagicMock

# Mock external modules
for _mod in ("google", "google.genai", "fitz", "tools", "_tools"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)
        if _mod == "google":
            sys.modules["google"].genai = types.ModuleType("google.genai")
            sys.modules["google"].genai.Client = MagicMock()

import app.database.db as _db_mod
_sb = MagicMock()
_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
_sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
_sb.rpc.return_value.execute.return_value = MagicMock(data=[])
_db_mod.supabase = _sb

STRONG_TEST_SECRET = "test-only-production-secret-9f5c2d7a4b8e1f6c3a0d"


class TestDevBillingRoutesRegistration(unittest.TestCase):
    """Tests that dev billing routes are registered conditionally."""

    def _get_production_config(self):
        return {
            "FLASK_DEBUG": "0",
            "CORS_ORIGINS": "https://app.example.com",
            "FRONTEND_URL": "https://app.example.com",
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "test",
            "SECRET_KEY": STRONG_TEST_SECRET,
        }

    def test_dev_route_absent_in_production(self):
        """Production config must NOT register dev billing blueprint."""
        with patch.dict(os.environ, self._get_production_config(), clear=False):
            from app import create_app
            app = create_app()
            rules = [r.rule for r in app.url_map.iter_rules()]
            dev_routes = [r for r in rules if "/dev/" in r]
            self.assertEqual(
                len(dev_routes), 0,
                f"Dev routes should not be registered in production, found: {dev_routes}"
            )

    def test_dev_route_present_in_dev_config(self):
        """Dev config with ENABLE_DEV_BILLING_ROUTES must register dev blueprint."""
        config = self._get_production_config()
        config["FLASK_DEBUG"] = "1"
        config["ENABLE_DEV_BILLING_ROUTES"] = "true"
        with patch.dict(os.environ, config, clear=False):
            from app import create_app
            app = create_app()
            rules = [r.rule for r in app.url_map.iter_rules()]
            dev_routes = [r for r in rules if "/dev/" in r]
            self.assertGreater(
                len(dev_routes), 0,
                "Dev routes should be present when ENABLE_DEV_BILLING_ROUTES=true"
            )

    def test_production_cannot_enable_dev_routes(self):
        """Production must raise RuntimeError if ENABLE_DEV_BILLING_ROUTES is set."""
        from app.config import load_configurations
        from flask import Flask
        with self.assertRaises(RuntimeError):
            with patch.dict(
                os.environ,
                {
                    "FLASK_DEBUG": "0",
                    "CORS_ORIGINS": "https://app.example.com",
                    "FRONTEND_URL": "https://app.example.com",
                    "ENABLE_DEV_BILLING_ROUTES": "true",
                },
                clear=False,
            ):
                from app.config import load_configurations as lc
                app = Flask(__name__)
                app.config["TESTING"] = True
                app.config["SECRET_KEY"] = "test"
                lc(app)

    def test_normal_billing_routes_always_registered(self):
        """Normal billing routes must be registered regardless of dev flag."""
        with patch.dict(os.environ, self._get_production_config(), clear=False):
            from app import create_app
            app = create_app()
            rules = [r.rule for r in app.url_map.iter_rules()]
            billing_routes = [r for r in rules if "/api/billing/" in r and "/dev/" not in r]
            self.assertGreater(len(billing_routes), 0, "Normal billing routes must be registered")
            # Verify specific known routes
            self.assertTrue(any("/plans" in r for r in billing_routes), "/plans route missing")
            self.assertTrue(any("/subscription" in r for r in billing_routes), "/subscription route missing")
            self.assertTrue(any("/health" in r for r in billing_routes), "/health route missing")


if __name__ == "__main__":
    unittest.main()
