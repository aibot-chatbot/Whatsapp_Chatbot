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
            "redacted_note": "Internal note must not cross tenant boundary.",
            "internal_note": "Internal note must not cross tenant boundary.",
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
        self.assertNotIn("redacted_note", response.get_data(as_text=True))
        self.assertNotIn("internal_note", response.get_data(as_text=True))
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

    def test_tenant_request_list_uses_refreshed_context_and_safe_projection(self):
        with patch.object(
            tenant_support_service.tenant_support_repository,
            "list_tenant_support_requests_for_tenant",
            return_value=([
                {
                    "id": 31,
                    "company_id": 100,
                    "requester_user_id": 7,
                    "category": "technical",
                    "status": "converted",
                    "priority": "urgent",
                    "converted_platform_support_case_id": 9,
                    "created_at": "2026-08-06T00:00:00+00:00",
                }
            ], 1),
        ) as repo:
            response = self.client.get("/api/support/requests", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        repo.assert_called_once_with(
            company_id=100, requester_user_id=7, limit=25, offset=0
        )
        row = response.json["data"]["requests"][0]
        self.assertEqual(row["request_id"], 31)
        self.assertNotIn("company_id", row)
        self.assertNotIn("requester_user_id", row)
        self.assertNotIn("priority", row)
        self.assertNotIn("converted_platform_support_case_id", row)

    def test_tenant_request_detail_includes_public_replies_without_internal_fields(self):
        with patch.object(
            tenant_support_service.tenant_support_repository,
            "get_tenant_support_request_for_tenant",
            return_value={
                "id": 31,
                "company_id": 100,
                "requester_user_id": 7,
                "category": "technical",
                "status": "converted",
                "priority": "urgent",
                "title": "Safe title",
                "redacted_description": "Safe description",
                "converted_platform_support_case_id": 9,
            },
        ), patch.object(
            tenant_support_service.tenant_support_repository,
            "list_tenant_support_replies_for_tenant",
            return_value=[{
                "id": 44,
                "request_id": 31,
                "company_id": 100,
                "author_type": "platform_admin",
                "author_platform_admin_user_id": 3,
                "redacted_body": "Visible reply",
                "redacted_note": "Internal note",
                "visibility_status": "visible",
            }],
        ) as replies:
            response = self.client.get("/api/support/requests/31", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        replies.assert_called_once_with(31, company_id=100)
        data = response.json["data"]
        self.assertEqual(data["request"]["title"], "Safe title")
        self.assertEqual(data["replies"][0]["redacted_body"], "Visible reply")
        body = response.get_data(as_text=True)
        self.assertNotIn("redacted_note", body)
        self.assertNotIn("author_platform_admin_user_id", body)
        self.assertNotIn("converted_platform_support_case_id", body)
        self.assertNotIn("urgent", body)

    def test_tenant_request_detail_missing_or_cross_company_returns_404(self):
        with patch.object(
            tenant_support_service.tenant_support_repository,
            "get_tenant_support_request_for_tenant",
            return_value=None,
        ), patch.object(
            tenant_support_service.tenant_support_repository,
            "list_tenant_support_replies_for_tenant",
        ) as replies:
            response = self.client.get("/api/support/requests/99", headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json["code"], "tenant_support_request_not_found")
        replies.assert_not_called()

    def test_tenant_route_is_separate_from_platform_admin_routes(self):
        rules = [rule.rule for rule in self.app.url_map.iter_rules()]
        self.assertIn("/api/support/requests", rules)
        self.assertIn("/api/support/requests/<int:request_id>", rules)
        self.assertNotIn("/api/platform-admin/support-requests", rules)


if __name__ == "__main__":
    unittest.main()
