"""test_rate_limiting.py

Unit tests for rate-limiting configuration and enforcement.
"""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("RATELIMIT_ENABLED", "true")

import sys
sys.path.insert(0, r"C:\Users\User\PycharmProjects\python-whatsapp-bot-main")

import types
from unittest.mock import patch, MagicMock, PropertyMock
import unittest

# Mock external modules
for _mod_name in ("google", "google.genai", "fitz", "tools", "_tools"):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = types.ModuleType(_mod_name)

if hasattr(sys.modules["google"], "genai") is False:
    sys.modules["google"].genai = types.ModuleType("google.genai")
    sys.modules["google"].genai.Client = MagicMock()

import app.database.db as _db_mod
_sb = MagicMock()
_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
_sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
_sb.rpc.return_value.execute.return_value = MagicMock(data=[])
_db_mod.supabase = _sb


class TestRateLimitConfig(unittest.TestCase):
    """Tests for rate-limit config values."""

    def _make_app_with_config(self, overrides=None):
        from app import create_app
        base_env = {
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "test",
            "SECRET_KEY": "test-secret-key",
            "FLASK_DEBUG": "1",
            "CORS_ORIGINS": "http://localhost:8000",
            "FRONTEND_URL": "http://localhost:3000",
            "RATELIMIT_ENABLED": "true",
        }
        if overrides:
            base_env.update(overrides)
        with patch.dict(os.environ, base_env, clear=False):
            return create_app()

    def test_default_config_values(self):
        """Test that default rate-limit config values exist."""
        app = self._make_app_with_config()
        self.assertIn("RATELIMIT_LOGIN", app.config)
        self.assertIn("RATELIMIT_OTP", app.config)
        self.assertIn("RATELIMIT_CHECKOUT", app.config)
        self.assertIn("RATELIMIT_RETRY", app.config)
        self.assertIn("RATELIMIT_RECEIPT", app.config)
        self.assertIn("RATELIMIT_EXPORT", app.config)

    def test_custom_rate_limit_config(self):
        """Test that custom rate-limit values are loaded from env."""
        app = self._make_app_with_config({
            "RATELIMIT_LOGIN": "5/minute",
            "RATELIMIT_CHECKOUT": "3/minute",
        })
        self.assertEqual(app.config["RATELIMIT_LOGIN"], "5/minute")
        self.assertEqual(app.config["RATELIMIT_CHECKOUT"], "3/minute")

    def test_rate_limit_disabled_in_test(self):
        """RATELIMIT_ENABLED should be configurable."""
        app = self._make_app_with_config({"RATELIMIT_ENABLED": "false"})
        self.assertFalse(app.config["RATELIMIT_ENABLED"])

    def test_rate_limit_storage_uri_default(self):
        app = self._make_app_with_config()
        self.assertEqual(app.config["RATELIMIT_STORAGE_URI"], "memory://")


class TestRateLimitLimiterInit(unittest.TestCase):
    """Tests for the rate-limit init and proxy."""

    def test_limiter_proxy_before_init(self):
        """The limiter proxy should return a no-op decorator before init."""
        # Import only the module, don't trigger init_limiter
        import importlib
        import app.rate_limit as rl_mod
        importlib.reload(rl_mod)
        limiter = rl_mod.limiter
        # Before init, limiter is a _LimiterProxy
        decorator = limiter.limit("1/minute")
        # It should be callable and return the function unchanged
        def fake_func():
            return 42
        result = decorator(fake_func)
        self.assertIs(result, fake_func, "No-op decorator should return original function")
        self.assertEqual(result(), 42)
        # Reload the module again to restore the real limiter from other imports
        importlib.reload(rl_mod)

    def test_limiter_after_init(self):
        """After init_limiter, calling .limit should create a real limit."""
        from app.config import load_configurations
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test"
        app.config["RATELIMIT_ENABLED"] = False

        from app.rate_limit import init_limiter
        init_limiter(app)

        from app.rate_limit import limiter
        decorator = limiter.limit("1/minute")
        self.assertIsNotNone(decorator)

    def test_key_function_company(self):
        """_get_company_or_ip should return company: prefix for authenticated requests."""
        from app.rate_limit import _get_company_or_ip
        from flask import Flask, g
        app = Flask(__name__)
        with app.app_context():
            g.company_id = 42
            key = _get_company_or_ip()
            self.assertEqual(key, "company:42")

    def test_key_function_ip_fallback(self):
        """_get_company_or_ip should fall back to IP when not authenticated."""
        from app.rate_limit import _get_company_or_ip
        from flask import Flask
        app = Flask(__name__)
        with app.test_request_context():
            key = _get_company_or_ip()
            # Should return an IP string (e.g., "127.0.0.1")
            self.assertIsNotNone(key)
            self.assertNotIn("company:", key)


class TestRateLimitBillingRoutes(unittest.TestCase):
    """Integration tests for rate-limited billing endpoints."""

    def setUp(self):
        """Create a test app with rate limiting enabled but weak limits."""
        from flask import Flask
        from app.routes.billing_routes import billing_bp
        from app.rate_limit import init_limiter

        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.config["SECRET_KEY"] = "test-secret-key"
        self.app.config["RATELIMIT_ENABLED"] = True
        self.app.config["RATELIMIT_STORAGE_URI"] = "memory://"
        self.app.config["RATELIMIT_CHECKOUT"] = "5/minute"
        self.app.config["RATELIMIT_RECEIPT"] = "30/minute"
        self.app.config["RATELIMIT_EXPORT"] = "20/minute"
        init_limiter(self.app)
        self.app.register_blueprint(billing_bp)
        self.client = self.app.test_client()

    @patch("app.decorators.auth_decorator.jwt.decode")
    def test_health_endpoint_not_rate_limited(self, mock_jwt):
        """The health endpoint should not have a rate-limit decorator."""
        mock_jwt.return_value = {"company_id": 1, "user_id": 1}
        for _ in range(10):
            resp = self.client.get("/api/billing/health")
            self.assertIn(resp.status_code, (200, 401, 429))
            if resp.status_code == 429:
                self.fail("Health endpoint should not be rate limited")

    def test_unauthenticated_request_returns_401_not_429(self):
        """Unauthenticated requests should fail auth before rate limiting."""
        resp = self.client.get("/api/billing/reports/summary")
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()
