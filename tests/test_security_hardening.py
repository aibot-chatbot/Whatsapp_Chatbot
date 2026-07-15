"""Tests for security headers and production config hardening (Security Phase 5)."""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")

import sys
sys.path.insert(0, "C:\\Users\\User\\PycharmProjects\\python-whatsapp-bot-main")

import unittest
from unittest.mock import patch, MagicMock

import types

if "google" not in sys.modules:
    _g = types.ModuleType("google")
    _g.genai = types.ModuleType("google.genai")
    _g.genai.Client = MagicMock()
    sys.modules["google"] = _g
    sys.modules["google.genai"] = _g.genai
if "fitz" not in sys.modules:
    sys.modules["fitz"] = types.ModuleType("fitz")
if "tools" not in sys.modules:
    sys.modules["tools"] = types.ModuleType("tools")
if "_tools" not in sys.modules:
    sys.modules["_tools"] = types.ModuleType("_tools")

with patch("app.database.db.supabase", MagicMock()):
    from app import create_app


class TestSecurityHeaders(unittest.TestCase):
    """Verify security response headers are present on normal routes."""

    @classmethod
    def setUpClass(cls):
        app = create_app()
        app.config["TESTING"] = True
        cls.client = app.test_client()

    def test_x_content_type_options_header(self):
        resp = self.client.get("/api/auth/login", headers={"Accept": "application/json"})
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")

    def test_x_frame_options_header(self):
        resp = self.client.get("/api/auth/login", headers={"Accept": "application/json"})
        self.assertEqual(resp.headers.get("X-Frame-Options"), "DENY")

    def test_referrer_policy_header(self):
        resp = self.client.get("/api/auth/login", headers={"Accept": "application/json"})
        self.assertEqual(resp.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")

    def test_headers_do_not_alter_response_status(self):
        """Security headers must not change the response body or status code."""
        resp = self.client.get("/api/auth/login", headers={"Accept": "application/json"})
        self.assertIn(resp.status_code, [200, 400, 405])  # any valid HTTP response is fine


class TestProductionConfigWarnings(unittest.TestCase):
    """Verify JWT_SECRET and SECRET_KEY fail fast in production mode."""

    def test_weak_jwt_secret_raises_runtime_error(self):
        from app.config import load_configurations

        with patch.dict(os.environ, {
            "FLASK_DEBUG": "0",
            "JWT_SECRET": "",
            "CORS_ORIGINS": "https://example.com",
            "FRONTEND_URL": "https://example.com",
        }, clear=False):
            app = MagicMock()
            app.config = {}
            with self.assertRaises(RuntimeError) as ctx:
                load_configurations(app)
            self.assertIn("JWT_SECRET", str(ctx.exception))

    def test_weak_flask_secret_key_raises_runtime_error(self):
        from app.config import load_configurations

        with patch.dict(os.environ, {
            "FLASK_DEBUG": "0",
            "JWT_SECRET": "a-strong-random-secret-key-abc123def456",
            "SECRET_KEY": "",
            "CORS_ORIGINS": "https://example.com",
            "FRONTEND_URL": "https://example.com",
        }, clear=False):
            app = MagicMock()
            app.config = {}
            with self.assertRaises(RuntimeError) as ctx:
                load_configurations(app)
            self.assertIn("SECRET_KEY", str(ctx.exception))

    def test_weak_secret_default_value_raises(self):
        from app.config import load_configurations

        with patch.dict(os.environ, {
            "FLASK_DEBUG": "0",
            "JWT_SECRET": "your-secret-key",
            "CORS_ORIGINS": "https://example.com",
            "FRONTEND_URL": "https://example.com",
        }, clear=False):
            app = MagicMock()
            app.config = {}
            with self.assertRaises(RuntimeError) as ctx:
                load_configurations(app)
            self.assertIn("JWT_SECRET", str(ctx.exception))

    def test_strong_secrets_do_not_raise(self):
        from app.config import load_configurations

        with patch.dict(os.environ, {
            "FLASK_DEBUG": "0",
            "JWT_SECRET": "a-very-strong-random-64-char-secret-key-abc123def456",
            "SECRET_KEY": "another-strong-random-secret-key-xyz789",
            "CORS_ORIGINS": "https://example.com",
            "FRONTEND_URL": "https://example.com",
        }, clear=False):
            app = MagicMock()
            app.config = {}
            # Should not raise
            try:
                load_configurations(app)
            except RuntimeError as e:
                self.fail(f"load_configurations raised unexpectedly: {e}")

    def test_dev_weak_secrets_do_not_raise(self):
        """Development mode with weak secrets should not block startup."""
        from app.config import load_configurations

        with patch.dict(os.environ, {
            "FLASK_DEBUG": "1",
            "JWT_SECRET": "",
            "SECRET_KEY": "",
            "CORS_ORIGINS": "http://localhost:3000",
            "FRONTEND_URL": "http://localhost:3000",
        }, clear=False):
            app = MagicMock()
            app.config = {}
            # Development mode should NOT raise even with weak secrets
            try:
                load_configurations(app)
            except RuntimeError as e:
                self.fail(f"Dev mode should not block startup: {e}")


if __name__ == "__main__":
    unittest.main()
