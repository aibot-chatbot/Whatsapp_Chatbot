"""tests/conftest.py

Shared pytest configuration and fixtures for the test suite.
Sets safe environment variables and mocks external dependencies
before any test module is imported.
"""

import os
import sys
import types
from unittest.mock import MagicMock

import pytest

# Never send test failures to a developer's real Sentry project. Individual
# observability tests opt in with a fake DSN and an in-memory transport.
os.environ["SENTRY_DSN"] = ""

# ── Environment variables (safe test values) ──────────────────────────────
os.environ.setdefault("SUPABASE_URL", "https://test-collection.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-collection-service-key")
os.environ.setdefault("SECRET_KEY", "test-collection-secret-key")
os.environ.setdefault("JWT_SECRET", "test-collection-jwt-secret-at-least-32-bytes")
os.environ.setdefault("OPENAI_API_KEY", "test-collection-openai-key")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-collection-deepseek-key")
# Tests must not import live credentials from a developer's local .env.
os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
os.environ.setdefault("FLASK_DEBUG", "1")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:8000")
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")
os.environ.setdefault("RATELIMIT_ENABLED", "false")

# ── Mock google.genai before any app module imports it ────────────────────
# The real google package exists but has no genai submodule.  ra_ervice.py
# does `from google import genai` at module scope, which fails.
if "google" not in sys.modules:
    sys.modules["google"] = types.ModuleType("google")

if not hasattr(sys.modules["google"], "genai"):
    _genai_mod = types.ModuleType("google.genai")
    _genai_mod.Client = MagicMock()
    sys.modules["google"].genai = _genai_mod

# ── Mock other modules that test files expect ─────────────────────────────
for _mod_name in ("fitz", "tools", "_tools"):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = types.ModuleType(_mod_name)

# ── Mock Supabase client to prevent network calls during collection ───────
import app.database.db as _db_mod
_sb = MagicMock()
_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
    MagicMock(data=[])
)
_sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
_sb.rpc.return_value.execute.return_value = MagicMock(data=[])
_db_mod.supabase = _sb


@pytest.fixture(autouse=True)
def _default_active_company_status(monkeypatch):
    """Keep legacy route tests on the verified active-company baseline."""
    import app.services.company_status_service as _company_status

    def _active_company_status(company_id):
        return {"id": company_id, "status": "active"}

    monkeypatch.setattr(
        _company_status,
        "get_company_status_by_id",
        _active_company_status,
    )
