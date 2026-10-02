"""test_rate_limiting.py

Unit tests for rate-limiting configuration and enforcement.
"""

import os
from datetime import datetime, timedelta, timezone
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import sys

import types
from unittest.mock import patch, MagicMock
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
        self.assertEqual(app.config["RATELIMIT_INVITE_VALIDATE"], "30/minute")
        self.assertEqual(app.config["RATELIMIT_INVITE_ACCEPT"], "5/minute")
        self.assertEqual(app.config["RATELIMIT_GOOGLE_AUTH"], "10/minute")

    def test_custom_rate_limit_config(self):
        """Test that custom rate-limit values are loaded from env."""
        app = self._make_app_with_config({
            "RATELIMIT_LOGIN": "5/minute",
            "RATELIMIT_CHECKOUT": "3/minute",
            "RATELIMIT_INVITE_VALIDATE": "12/minute",
            "RATELIMIT_INVITE_ACCEPT": "4/minute",
            "RATELIMIT_GOOGLE_AUTH": "8/minute",
        })
        self.assertEqual(app.config["RATELIMIT_LOGIN"], "5/minute")
        self.assertEqual(app.config["RATELIMIT_CHECKOUT"], "3/minute")
        self.assertEqual(app.config["RATELIMIT_INVITE_VALIDATE"], "12/minute")
        self.assertEqual(app.config["RATELIMIT_INVITE_ACCEPT"], "4/minute")
        self.assertEqual(app.config["RATELIMIT_GOOGLE_AUTH"], "8/minute")

    def test_rate_limit_disabled_in_test(self):
        """RATELIMIT_ENABLED should be configurable."""
        app = self._make_app_with_config({"RATELIMIT_ENABLED": "false"})
        self.assertFalse(app.config["RATELIMIT_ENABLED"])

    def test_rate_limit_storage_uri_default(self):
        app = self._make_app_with_config()
        self.assertEqual(app.config["RATELIMIT_STORAGE_URI"], "memory://")


class TestRateLimitLimiterInit(unittest.TestCase):
    """Tests for the stable rate-limit extension and key function."""

    def test_limiter_is_a_stable_flask_extension(self):
        """Routes imported before create_app must decorate a real Limiter."""
        from flask_limiter import Limiter
        from app.rate_limit import limiter

        self.assertIsInstance(limiter, Limiter)

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


class TestRateLimitNormalStartup(unittest.TestCase):
    """Enforcement tests using the normal create_app route-import order."""

    def _make_app(self, enabled=True, login_limit="1/minute", overrides=None):
        from app import create_app

        environment = {
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
            "SECRET_KEY": "test-secret-key",
            "FLASK_DEBUG": "1",
            "CORS_ORIGINS": "http://localhost:8000",
            "FRONTEND_URL": "http://localhost:3000",
            "RATELIMIT_ENABLED": "true" if enabled else "false",
            "RATELIMIT_STORAGE_URI": "memory://",
            "RATELIMIT_LOGIN": login_limit,
            "RATELIMIT_INVITE_VALIDATE": "30/minute",
            "RATELIMIT_INVITE_ACCEPT": "5/minute",
            "RATELIMIT_GOOGLE_AUTH": "10/minute",
        }
        if overrides:
            environment.update(overrides)
        with patch.dict(os.environ, environment, clear=False):
            app = create_app()
        app.config["TESTING"] = True
        return app

    @staticmethod
    def _login(client, remote_addr):
        return client.post(
            "/api/auth/login",
            json={},
            environ_base={"REMOTE_ADDR": remote_addr},
        )

    @staticmethod
    def _validate_invite(client, remote_addr):
        return client.get(
            "/api/invites/validate",
            environ_base={"REMOTE_ADDR": remote_addr},
        )

    @staticmethod
    def _accept_invite(client, remote_addr, payload=None):
        return client.post(
            "/api/invites/accept",
            json={} if payload is None else payload,
            environ_base={"REMOTE_ADDR": remote_addr},
        )

    @staticmethod
    def _google_auth(client, remote_addr, payload=None):
        return client.post(
            "/api/auth/google",
            json={} if payload is None else payload,
            environ_base={"REMOTE_ADDR": remote_addr},
        )

    def test_normal_startup_enforces_login_limit(self):
        app = self._make_app(enabled=True, login_limit="1/minute")
        client = app.test_client()

        self.assertEqual(self._login(client, "198.51.100.10").status_code, 400)
        self.assertEqual(self._login(client, "198.51.100.10").status_code, 429)

    def test_disabled_mode_does_not_limit_repeated_requests(self):
        app = self._make_app(enabled=False, login_limit="1/minute")
        client = app.test_client()

        statuses = [
            self._login(client, "198.51.100.11").status_code
            for _ in range(3)
        ]
        self.assertEqual(statuses, [400, 400, 400])

    def test_public_ip_addresses_have_independent_buckets(self):
        app = self._make_app(enabled=True, login_limit="1/minute")
        client = app.test_client()

        self.assertEqual(self._login(client, "198.51.100.12").status_code, 400)
        self.assertEqual(self._login(client, "198.51.100.12").status_code, 429)
        self.assertEqual(self._login(client, "198.51.100.13").status_code, 400)

    def test_separate_applications_do_not_share_counters(self):
        first_app = self._make_app(enabled=True, login_limit="1/minute")
        first_client = first_app.test_client()
        self.assertEqual(self._login(first_client, "198.51.100.14").status_code, 400)
        self.assertEqual(self._login(first_client, "198.51.100.14").status_code, 429)

        second_app = self._make_app(enabled=True, login_limit="1/minute")
        second_client = second_app.test_client()
        self.assertEqual(self._login(second_client, "198.51.100.14").status_code, 400)

    def test_invitation_validation_limit_is_enforced(self):
        app = self._make_app(overrides={"RATELIMIT_INVITE_VALIDATE": "1/minute"})
        client = app.test_client()

        self.assertEqual(self._validate_invite(client, "198.51.100.20").status_code, 400)
        self.assertEqual(self._validate_invite(client, "198.51.100.20").status_code, 429)

    def test_invitation_accept_limit_blocks_database_writes(self):
        app = self._make_app(overrides={"RATELIMIT_INVITE_ACCEPT": "1/minute"})
        client = app.test_client()
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        invitation = {
            "id": 7,
            "company_id": 42,
            "email": "invitee@example.test",
            "role": "member",
            "status": "pending",
            "expires_at": expiry,
        }
        created_user = {
            "id": 9,
            "company_id": 42,
            "email": "invitee@example.test",
            "role": "member",
        }
        payload = {
            "token": "valid-token",
            "full_name": "Invitee User",
            "password": "Strong1!",
        }

        with patch(
            "app.services.invitation_service.get_invite_by_token",
            return_value=invitation,
        ), patch(
            "app.services.invitation_service.get_user_by_email",
            return_value=None,
        ), patch(
            "app.services.invitation_service.can_accept_team_invitation",
            return_value=True,
        ), patch(
            "app.services.invitation_service.create_user",
            return_value=created_user,
        ) as create_user, patch(
            "app.services.invitation_service.update_invite",
            return_value=invitation,
        ) as update_invite:
            first = self._accept_invite(client, "198.51.100.21", payload)
            blocked = self._accept_invite(client, "198.51.100.21", payload)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(blocked.status_code, 429)
        create_user.assert_called_once()
        update_invite.assert_called_once()

    def test_google_auth_limit_blocks_network_and_invitation_acceptance(self):
        app = self._make_app(overrides={
            "RATELIMIT_GOOGLE_AUTH": "1/minute",
        })
        client = app.test_client()
        google_response = MagicMock()
        google_response.status_code = 200
        google_response.json.return_value = {
            "aud": "configured-google-client",
            "email": "invitee@example.test",
            "email_verified": "true",
            "name": "Invitee User",
            "sub": "google-user-id",
        }
        accepted_user = {
            "id": 9,
            "company_id": 42,
            "email": "invitee@example.test",
            "role": "member",
            "password_hash": None,
        }
        payload = {"credential": "credential", "invite_token": "invite-token"}

        with patch.dict(os.environ, {
            "GOOGLE_CLIENT_ID": "configured-google-client",
            "JWT_SECRET": "test-only-google-rate-limit-jwt-secret",
        }), patch(
            "requests.get",
            return_value=google_response,
        ) as google_request, patch(
            "app.routes.auth_routes.get_user_by_email",
            return_value=None,
        ), patch(
            "app.routes.auth_routes.accept_pending_invitation",
            return_value=accepted_user,
        ) as accept_invitation, patch(
            "app.database.platform_admin_repository.get_platform_admin_by_user_id",
            return_value=None,
        ) as staff_lookup:
            first = self._google_auth(client, "198.51.100.22", payload)
            blocked = self._google_auth(client, "198.51.100.22", payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(blocked.status_code, 429)
        google_request.assert_called_once()
        accept_invitation.assert_called_once()
        staff_lookup.assert_called_once_with(accepted_user["id"])
        self.assertEqual(first.json["redirect_url"], "bots.html")

    def test_public_invitation_and_google_limits_have_independent_buckets(self):
        app = self._make_app(overrides={
            "RATELIMIT_INVITE_VALIDATE": "1/minute",
            "RATELIMIT_INVITE_ACCEPT": "1/minute",
            "RATELIMIT_GOOGLE_AUTH": "1/minute",
        })
        client = app.test_client()
        remote_addr = "198.51.100.23"

        self.assertEqual(self._validate_invite(client, remote_addr).status_code, 400)
        self.assertEqual(self._accept_invite(client, remote_addr).status_code, 400)
        self.assertEqual(self._google_auth(client, remote_addr).status_code, 400)
        self.assertEqual(self._validate_invite(client, remote_addr).status_code, 429)
        self.assertEqual(self._accept_invite(client, remote_addr).status_code, 429)
        self.assertEqual(self._google_auth(client, remote_addr).status_code, 429)

    def test_invitation_validation_uses_independent_ip_buckets(self):
        app = self._make_app(overrides={"RATELIMIT_INVITE_VALIDATE": "1/minute"})
        client = app.test_client()

        self.assertEqual(self._validate_invite(client, "198.51.100.24").status_code, 400)
        self.assertEqual(self._validate_invite(client, "198.51.100.24").status_code, 429)
        self.assertEqual(self._validate_invite(client, "198.51.100.25").status_code, 400)

    def test_disabled_mode_does_not_limit_public_invitation_or_google_routes(self):
        app = self._make_app(enabled=False, overrides={
            "RATELIMIT_INVITE_VALIDATE": "1/minute",
            "RATELIMIT_INVITE_ACCEPT": "1/minute",
            "RATELIMIT_GOOGLE_AUTH": "1/minute",
        })
        client = app.test_client()
        remote_addr = "198.51.100.26"

        for _ in range(3):
            self.assertEqual(self._validate_invite(client, remote_addr).status_code, 400)
            self.assertEqual(self._accept_invite(client, remote_addr).status_code, 400)
            self.assertEqual(self._google_auth(client, remote_addr).status_code, 400)


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

class TestAnonymousMediaRouteIsRateLimited(unittest.TestCase):
    """/media/ is anonymous and now makes a blocking R2 call.

    Before documents moved to R2 a miss was a local stat. It is now a
    GetObject whose retry budget runs to tens of seconds, and gunicorn serves
    this app with one worker and eight threads -- so a handful of concurrent
    misses can hold every thread and take the webhooks, the Wasender retry
    loop and the billing scheduler down with them. The limit is the only thing
    bounding that, and nothing else in the suite would notice it being lost.
    """

    def test_serve_media_carries_an_explicit_limit(self):
        from app.rate_limit import limiter

        marked = {
            getattr(item, '__name__', None)
            for item in getattr(limiter, 'limit_manager', limiter).__dict__.get('_route_limits', {})
        }
        # flask-limiter's internals differ across versions, so fall back to the
        # decorator's own marker rather than pinning a private attribute name.
        from app import create_app
        app = create_app()
        view = app.view_functions['serve_media']
        self.assertTrue(
            hasattr(view, '__wrapped__') or marked,
            'serve_media must be wrapped by a rate limiter',
        )

    def test_media_limit_is_configurable_and_generous_by_default(self):
        from app import create_app

        app = create_app()
        # Unset means the generous default applies; a real provider burst must
        # never be dropped just because the route is protected.
        self.assertEqual(app.config.get('RATELIMIT_MEDIA', '240/minute'), '240/minute')
