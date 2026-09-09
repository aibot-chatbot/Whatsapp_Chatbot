import unittest
from unittest.mock import patch

from flask import Flask

from app.routes.platform_admin_routes import platform_admin_bp
from app.services import platform_admin_service


class PlatformAdminTenantSupportIntakeTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(platform_admin_bp)
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer token"}
        self.patches = [
            patch("app.decorators.auth_decorator.get_jwt_secret", return_value="secret"),
            patch("app.decorators.auth_decorator.jwt.decode", return_value={"user_id": 7}),
            patch("app.database.user_repository.get_user_by_id", return_value={
                "id": 7, "company_id": 100, "role": "member", "status": "active",
            }),
            patch(
                "app.decorators.platform_admin_decorator.get_active_platform_admin_by_user_id",
                return_value={"platform_role": "super_admin", "modules": {"billing": True, "support": True, "customers": True}, "id": 3, "user_id": 7, "is_active": True},
            ),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_authentication_and_active_platform_admin_guard_apply(self):
        self.assertEqual(self.client.get("/api/platform-admin/tenant-support-requests").status_code, 401)
        with patch(
            "app.decorators.platform_admin_decorator.get_active_platform_admin_by_user_id",
            return_value=None,
        ):
            response = self.client.get(
                "/api/platform-admin/tenant-support-requests", headers=self.headers
            )
        self.assertEqual(response.status_code, 403)

    def test_routes_are_get_only(self):
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    "/api/platform-admin/tenant-support-requests", headers=self.headers
                )
                self.assertEqual(response.status_code, 405)

    def test_list_returns_safe_projection_and_audits_before_response(self):
        row = {
            "id": 31, "company_id": 2, "requester_user_id": 7,
            "category": "technical", "status": "new", "priority": "normal",
            "source": "tenant", "created_at": "now", "updated_at": "now", "closed_at": None,
            "title": "private title", "redacted_description": "private description",
        }
        with patch.object(
            platform_admin_service.tenant_support_repository,
            "list_tenant_support_requests_for_platform_admin",
            return_value=([row], 1),
        ), patch.object(platform_admin_service, "_audit") as audit:
            response = self.client.get(
                "/api/platform-admin/tenant-support-requests?limit=10&offset=0&category=technical",
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        item = response.json["data"]["requests"][0]
        self.assertEqual(item["request_id"], 31)
        self.assertNotIn("title", item)
        self.assertNotIn("redacted_description", item)
        metadata = audit.call_args.args[4]
        self.assertEqual(metadata["outcome"], "success")
        self.assertNotIn("title", metadata)
        self.assertNotIn("redacted_description", metadata)
        self.assertNotIn("metadata", metadata)

    def test_detail_returns_content_only_in_response_and_not_audit_metadata(self):
        row = {
            "id": 31, "company_id": 2, "requester_user_id": 7,
            "category": "technical", "status": "new", "priority": "normal",
            "source": "tenant", "created_at": "now", "updated_at": "now", "closed_at": None,
            "title": "redacted title", "redacted_description": "redacted description",
        }
        event = {"event_type": "created", "actor_type": "tenant", "created_at": "now",
                 "raw_metadata": "must not escape"}
        with patch.object(
            platform_admin_service.tenant_support_repository,
            "get_tenant_support_request_for_platform_admin", return_value=row,
        ), patch.object(
            platform_admin_service.tenant_support_repository,
            "list_tenant_support_request_events_for_platform_admin", return_value=[event],
        ), patch.object(platform_admin_service, "_audit") as audit:
            response = self.client.get(
                "/api/platform-admin/tenant-support-requests/31", headers=self.headers
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["request"]["title"], "redacted title")
        self.assertNotIn("escalation_context", response.json["data"]["request"])
        self.assertEqual(response.json["data"]["request"]["priority"], "normal")
        self.assertEqual(response.json["data"]["request"]["source"], "tenant")
        self.assertEqual(response.json["data"]["events"], [{
            "event_type": "created", "actor_type": "tenant", "created_at": "now",
        }])
        metadata = audit.call_args.args[4]
        self.assertNotIn("title", metadata)
        self.assertNotIn("redacted_description", metadata)
        self.assertNotIn("raw_metadata", metadata)
        self.assertNotIn("escalation_context", metadata)

    def test_filter_and_request_id_validation(self):
        cases = {
            "company_id=0": "invalid_company_id",
            "category=unsupported": "invalid_category",
            "status=unsupported": "invalid_status",
            "limit=101": "invalid_limit",
            "offset=-1": "invalid_offset",
        }
        for query, code in cases.items():
            with self.subTest(query=query):
                response = self.client.get(
                    "/api/platform-admin/tenant-support-requests?" + query,
                    headers=self.headers,
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json["code"], code)

    def test_missing_request_is_safe_not_found_and_audited(self):
        with patch.object(
            platform_admin_service.tenant_support_repository,
            "get_tenant_support_request_for_platform_admin", return_value=None,
        ), patch.object(platform_admin_service, "_audit") as audit:
            response = self.client.get(
                "/api/platform-admin/tenant-support-requests/999", headers=self.headers
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json["code"], "tenant_support_request_not_found")
        self.assertEqual(audit.call_args.args[1], "platform_admin.tenant_support_request.read")


if __name__ == "__main__":
    unittest.main()
