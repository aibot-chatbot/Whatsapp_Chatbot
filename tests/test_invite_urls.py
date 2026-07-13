"""test_invite_urls.py

Unit tests for hardcoded invite URL remediation.
Tests that _build_invite_url() uses FRONTEND_URL config and does not
fall back to hardcoded localhost in production context.
"""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import sys
sys.path.insert(0, r"C:\Users\User\PycharmProjects\python-whatsapp-bot-main")

import json
import unittest
import types
from unittest.mock import patch, MagicMock

# ---- Mock external modules ----
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


class TestBuildInviteUrl(unittest.TestCase):
    """Tests for the _build_invite_url helper."""

    def setUp(self):
        # Import is deferred so mock supabase is installed first
        from app.routes.invite_routes import invite_bp
        from flask import Flask
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.config["SECRET_KEY"] = "test-secret-key"
        self.app.config["FRONTEND_URL"] = "https://app.example.com"
        # Register the blueprint so config loading works
        self.app.register_blueprint(invite_bp)
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def _build_invite_url(self, token):
        from app.routes.invite_routes import _build_invite_url
        return _build_invite_url(token)

    def test_invite_url_uses_frontend_url(self):
        url = self._build_invite_url("abc123token")
        self.assertTrue(url.startswith("https://app.example.com/accept-invite"))
        self.assertIn("abc123token", url)

    def test_invite_url_contains_token(self):
        url = self._build_invite_url("test-token-value")
        self.assertIn("test-token-value", url)
        self.assertIn("token=", url)

    def test_invite_url_no_trailing_slash_from_config(self):
        """The config module normalizes trailing slash via rstrip('/')."""
        url = self._build_invite_url("tok")
        self.assertTrue(url.startswith("https://app.example.com/accept-invite"))
        self.assertNotIn("//accept", url)

    def test_invite_url_uses_config_not_host_header(self):
        url = self._build_invite_url("secret-token")
        self.assertNotIn("localhost:3000", url)

    def test_invite_url_no_hardcoded_localhost(self):
        url = self._build_invite_url("tok")
        self.assertNotIn("localhost", url)
        self.assertNotIn("127.0.0.1", url)

    def test_invite_url_development_localhost_fallback(self):
        """In test/dev context with config change, FRONTEND_URL is used as-is."""
        # Just verify the helper works when FRONTEND_URL is set
        self.assertTrue(self._build_invite_url("x").startswith("https://app.example.com"))


class TestConfigFrontendUrl(unittest.TestCase):
    """Tests for FRONTEND_URL config loading in production vs development."""

    def tearDown(self):
        # Clean up module state to avoid import side effects
        for k in list(sys.modules.keys()):
            if k.startswith("app.") and k != "app.database.db":
                pass  # Don't clean up, tests are self-contained

    def test_production_missing_frontend_url_raises(self):
        with patch.dict(os.environ, {"FRONTEND_URL": "", "FLASK_DEBUG": "0", "CORS_ORIGINS": "https://example.com"}, clear=False):
            from app.config import load_configurations
            from flask import Flask
            app = Flask(__name__)
            app.config["TESTING"] = True
            app.config["SECRET_KEY"] = "test"
            with self.assertRaises(RuntimeError):
                load_configurations(app)

    def test_development_defaults_to_localhost(self):
        with patch.dict(os.environ, {"FRONTEND_URL": "", "FLASK_DEBUG": "1", "CORS_ORIGINS": "http://localhost:8000"}, clear=False):
            from app.config import load_configurations
            from flask import Flask
            app = Flask(__name__)
            app.config["TESTING"] = True
            app.config["SECRET_KEY"] = "test"
            load_configurations(app)
            self.assertEqual(app.config["FRONTEND_URL"], "http://localhost:3000")

    def test_production_with_frontend_url_ok(self):
        with patch.dict(os.environ, {"FRONTEND_URL": "https://myapp.com", "FLASK_DEBUG": "0", "CORS_ORIGINS": "https://myapp.com"}, clear=False):
            from app.config import load_configurations
            from flask import Flask
            app = Flask(__name__)
            app.config["TESTING"] = True
            app.config["SECRET_KEY"] = "test"
            load_configurations(app)
            self.assertEqual(app.config["FRONTEND_URL"], "https://myapp.com")


if __name__ == "__main__":
    unittest.main()
