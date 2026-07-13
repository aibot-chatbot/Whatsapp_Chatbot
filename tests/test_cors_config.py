"""test_cors_config.py

Unit tests for CORS configuration hardening.
"""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import sys
sys.path.insert(0, r"C:\Users\User\PycharmProjects\python-whatsapp-bot-main")

import types
from unittest.mock import patch, MagicMock

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
import unittest


class TestCorsConfigProduction(unittest.TestCase):
    def _load_config(self, env_vars):
        from app.config import load_configurations
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test"
        with patch.dict(os.environ, env_vars, clear=False):
            load_configurations(app)
        return app

    def test_valid_single_origin(self):
        app = self._load_config({
            "CORS_ORIGINS": "https://app.example.com",
            "FRONTEND_URL": "https://app.example.com",
            "FLASK_DEBUG": "0",
        })
        self.assertEqual(app.config["CORS_ORIGINS"], ["https://app.example.com"])

    def test_valid_multiple_origins(self):
        app = self._load_config({
            "CORS_ORIGINS": "https://app.example.com,https://admin.example.com",
            "FRONTEND_URL": "https://app.example.com",
            "FLASK_DEBUG": "0",
        })
        self.assertEqual(
            app.config["CORS_ORIGINS"],
            ["https://app.example.com", "https://admin.example.com"],
        )

    def test_whitespace_normalized(self):
        app = self._load_config({
            "CORS_ORIGINS": "  https://app.example.com , https://admin.example.com  ",
            "FRONTEND_URL": "https://app.example.com",
            "FLASK_DEBUG": "0",
        })
        self.assertEqual(
            app.config["CORS_ORIGINS"],
            ["https://app.example.com", "https://admin.example.com"],
        )

    def test_missing_production_origin_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._load_config({
                "CORS_ORIGINS": "",
                "FRONTEND_URL": "https://app.example.com",
                "FLASK_DEBUG": "0",
            })
        self.assertIn("CORS_ORIGINS", str(ctx.exception))

    def test_empty_production_origin_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._load_config({
                "CORS_ORIGINS": "   ",
                "FRONTEND_URL": "https://app.example.com",
                "FLASK_DEBUG": "0",
            })
        self.assertIn("CORS_ORIGINS", str(ctx.exception))

    def test_wildcard_production_origin_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._load_config({
                "CORS_ORIGINS": "*",
                "FRONTEND_URL": "https://app.example.com",
                "FLASK_DEBUG": "0",
            })
        self.assertIn("wildcard", str(ctx.exception).lower())

    def test_malformed_origin_with_empty_entries(self):
        app = self._load_config({
            "CORS_ORIGINS": "https://app.example.com,,https://other.com",
            "FRONTEND_URL": "https://app.example.com",
            "FLASK_DEBUG": "0",
        })
        self.assertEqual(
            app.config["CORS_ORIGINS"],
            ["https://app.example.com", "https://other.com"],
        )


class TestCorsConfigDevelopment(unittest.TestCase):
    def _load_config(self, env_vars):
        from app.config import load_configurations
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test"
        with patch.dict(os.environ, env_vars, clear=False):
            load_configurations(app)
        return app

    def test_development_localhost_fallback(self):
        app = self._load_config({
            "CORS_ORIGINS": "",
            "FRONTEND_URL": "",
            "FLASK_DEBUG": "1",
        })
        self.assertIn("http://localhost:8000", app.config["CORS_ORIGINS"])
        self.assertIn("http://127.0.0.1:8000", app.config["CORS_ORIGINS"])

    def test_development_explicit_origins(self):
        app = self._load_config({
            "CORS_ORIGINS": "http://localhost:3000",
            "FRONTEND_URL": "",
            "FLASK_DEBUG": "1",
        })
        self.assertEqual(app.config["CORS_ORIGINS"], ["http://localhost:3000"])

    def test_development_wildcard_allowed(self):
        app = self._load_config({
            "CORS_ORIGINS": "*",
            "FRONTEND_URL": "",
            "FLASK_DEBUG": "1",
        })
        self.assertEqual(app.config["CORS_ORIGINS"], ["*"])


if __name__ == "__main__":
    unittest.main()
