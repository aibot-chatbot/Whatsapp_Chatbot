import unittest
from unittest.mock import patch

from flask import Flask

from app.rate_limit import init_limiter
from app.routes.support_routes import support_bp
from app.services import tenant_support_service


class TenantSupportRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            RATELIMIT_ENABLED=False,
            RATELIMIT_STORAGE_URI="memory://",
        )
        init_limiter(self.app)
        self.app.register_blueprint(support_bp)
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer token"}
        self.patches = [
            patch("app.decorators.auth_decorator.get_jwt_secret", return_value="secret"),
            patch(
                "app.decorators.auth_decorator.jwt.decode",
                return_value={"user_id": 7, "company_id": 100, "role": "member"},
            ),
            patch(
                "app.database.user_repository.get_user_by_id",
                return_value={
                    "id": 7,
                    "company_id": 100,
                    "email": "tenant@example.test",
                    "status": "active",
                    "role": "member",
                },
            ),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.post("/api/support/requests", json={})
        self.assertEqual(response.status_code, 401)

    def test_valid_request_uses_refreshed_server_context_and_safe_response(self):
        with patch.object(
            tenant_support_service.tenant_support_repository,
            "create_tenant_support_request",
            return_value=31,
        ) as rpc:
            response = self.client.post(
                "/api/support/requests",
                json={
                    "category": "technical",
                    "title": "Widget setup question",
                    "redacted_description": "The test widget needs review.",
                },
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "success", "data": {"request_id": 31}})
        rpc.assert_called_once_with(
            company_id=100,
            requester_user_id=7,
            category="technical",
            title="Widget setup question",
            redacted_description="The test widget needs review.",
        )

    def test_browser_identity_and_admin_fields_are_rejected(self):
        payload = {
            "company_id": 999,
            "user_id": 999,
            "platform_admin_user_id": 9,
            "status": "closed",
            "priority": "urgent",
            "assignment": 9,
            "closed_at": "2026-08-05T00:00:00Z",
            "audit_metadata": {"secret": "omit"},
            "category": "technical",
            "title": "Test",
            "redacted_description": "Test description",
        }
        with patch.object(tenant_support_service.tenant_support_repository, "create_tenant_support_request") as rpc:
            response = self.client.post(
                "/api/support/requests", json=payload, headers=self.headers
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["code"], "unsupported_field")
        rpc.assert_not_called()

    def test_invalid_category_and_text_lengths_are_rejected(self):
        cases = [
            ({"category": "billing", "title": "Test", "redacted_description": "Test"}, "invalid_category"),
            ({"category": "technical", "title": "", "redacted_description": "Test"}, "invalid_title"),
            ({"category": "technical", "title": "Test", "redacted_description": ""}, "invalid_redacted_description"),
            ({"category": "technical", "title": "x" * 161, "redacted_description": "Test"}, "invalid_title"),
            ({"category": "technical", "title": "Test", "redacted_description": "x" * 2001}, "invalid_redacted_description"),
        ]
        for payload, code in cases:
            with self.subTest(code=code):
                response = self.client.post(
                    "/api/support/requests", json=payload, headers=self.headers
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json["code"], code)

    def test_sensitive_text_is_rejected_without_logging_or_rpc(self):
        with patch.object(tenant_support_service.tenant_support_repository, "create_tenant_support_request") as rpc:
            response = self.client.post(
                "/api/support/requests",
                json={
                    "category": "technical",
                    "title": "Password question",
                    "redacted_description": "Synthetic test text.",
                },
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["code"], "invalid_title")
        rpc.assert_not_called()

    def test_rpc_failure_fails_closed(self):
        with patch.object(
            tenant_support_service.tenant_support_repository,
            "create_tenant_support_request",
            side_effect=RuntimeError("database unavailable"),
        ):
            response = self.client.post(
                "/api/support/requests",
                json={
                    "category": "technical",
                    "title": "Test",
                    "redacted_description": "Test description",
                },
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["code"], "tenant_support_unavailable")
        self.assertNotIn("database unavailable", response.get_data(as_text=True))

    def test_tenant_route_is_separate_from_platform_admin_routes(self):
        rules = [rule.rule for rule in self.app.url_map.iter_rules()]
        self.assertIn("/api/support/requests", rules)
        self.assertNotIn("/api/platform-admin/support-requests", rules)


if __name__ == "__main__":
    unittest.main()
