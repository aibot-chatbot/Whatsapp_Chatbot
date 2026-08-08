import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from flask import Flask

from app.routes.platform_admin_routes import platform_admin_bp
from app.database import platform_admin_repository
from app.database import platform_support_case_repository
from app.services import platform_admin_service


class PlatformAdminSupportCaseRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(platform_admin_bp)
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer token"}
        self.patches = [
            patch("app.decorators.auth_decorator.get_jwt_secret", return_value="secret"),
            patch("app.decorators.auth_decorator.jwt.decode", return_value={
                "user_id": 7, "company_id": 100, "role": "member",
                "is_platform_admin": False,
            }),
            patch("app.database.user_repository.get_user_by_id", return_value={
                "id": 7, "company_id": 100, "email": "internal@example.test",
                "status": "active", "role": "member",
            }),
            patch(
                "app.decorators.platform_admin_decorator.get_active_platform_admin_by_user_id",
                return_value={"id": 3, "user_id": 7, "is_active": True},
            ),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_support_case_routes_require_existing_platform_guard(self):
        for method, path in [
            (self.client.get, "/api/platform-admin/support-cases"),
            (self.client.post, "/api/platform-admin/support-cases"),
            (self.client.get, "/api/platform-admin/support-cases/1"),
            (self.client.post, "/api/platform-admin/support-cases/1/notes"),
            (self.client.patch, "/api/platform-admin/support-cases/1"),
        ]:
            with self.subTest(path=path):
                self.assertEqual(method(path).status_code, 401)

    def test_create_route_passes_safe_json_to_service(self):
        with patch.object(
            platform_admin_service,
            "create_support_case",
            return_value={"case": {"id": 9, "company_id": 31}},
        ) as service:
            response = self.client.post(
                "/api/platform-admin/support-cases",
                headers=self.headers,
                json={
                    "company_id": 31,
                    "title": "Review tenant activation",
                    "redacted_summary": "Review the safe activation state.",
                },
            )
        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with({
            "company_id": 31,
            "title": "Review tenant activation",
            "redacted_summary": "Review the safe activation state.",
        }, 3)

    def test_list_detail_note_and_update_routes_use_expected_methods(self):
        with patch.object(platform_admin_service, "list_support_cases", return_value={"cases": []}), \
             patch.object(platform_admin_service, "get_support_case", return_value={"case": {}, "events": []}), \
             patch.object(platform_admin_service, "add_support_case_note", return_value={"event": {}}), \
             patch.object(platform_admin_service, "update_support_case", return_value={"case": {}}):
            responses = [
                self.client.get("/api/platform-admin/support-cases", headers=self.headers),
                self.client.get("/api/platform-admin/support-cases/1", headers=self.headers),
                self.client.post(
                    "/api/platform-admin/support-cases/1/notes",
                    headers=self.headers, json={"redacted_note": "Internal note"},
                ),
                self.client.patch(
                    "/api/platform-admin/support-cases/1",
                    headers=self.headers, json={"status": "resolved"},
                ),
            ]
        self.assertTrue(all(response.status_code == 200 for response in responses))


class PlatformAdminSupportCaseServiceTests(unittest.TestCase):
    def test_create_uses_safe_projection_and_audits_after_event(self):
        company = {"id": 31, "company_name": "Safe Tenant", "status": "active"}
        case = {
            "id": 9, "company_id": 31, "status": "open", "priority": "normal",
            "title": "Review activation", "redacted_summary": "Safe summary",
        }
        calls = []
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin", return_value=company,
        ), patch.object(
            platform_admin_service.platform_support_case_repository,
            "create_support_case_for_platform_admin", return_value=case,
        ), patch.object(
            platform_admin_service.platform_support_case_repository,
            "create_support_case_event_for_platform_admin",
            side_effect=lambda payload: calls.append(("event", payload)) or {"id": 1, **payload},
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=lambda *args: calls.append(("audit", args)),
        ):
            result = platform_admin_service.create_support_case({
                "company_id": 31,
                "title": "Review activation",
                "redacted_summary": "Safe summary",
            }, 3)
        self.assertEqual(result["case"]["company"], {
            "id": 31, "company_name": "Safe Tenant", "status": "active",
        })
        self.assertNotIn("email", result["case"])
        self.assertEqual([item[0] for item in calls], ["event", "audit"])
        self.assertEqual(calls[1][1][1], "platform_admin.support_case.create")

    def test_redaction_boundary_rejects_sensitive_case_text(self):
        with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
            platform_admin_service.create_support_case({
                "company_id": 31,
                "title": "Review secret token",
                "redacted_summary": "Safe summary",
            }, 3)
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.code, "invalid_title")

    def test_support_case_audit_write_methods_and_safe_metadata_are_validated(self):
        platform_admin_repository.validate_audit_event(
            3,
            "platform_admin.support_case.create",
            "platform_support_cases",
            "9",
            {
                "outcome": "success",
                "endpoint": "/api/platform-admin/support-cases",
                "http_method": "POST",
                "company_id": 31,
                "status": "open",
                "priority": "normal",
            },
        )
        with self.assertRaises(ValueError):
            platform_admin_repository.validate_audit_event(
                3,
                "platform_admin.support_case.create",
                "platform_support_cases",
                "9",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/support-cases",
                    "http_method": "GET",
                    "company_id": 31,
                },
            )


class PlatformAdminSupportCaseRepositoryTests(unittest.TestCase):
    def test_list_uses_safe_projection_and_filters(self):
        query = MagicMock()
        for method in ("select", "eq", "order", "range"):
            getattr(query, method).return_value = query
        query.execute.return_value = SimpleNamespace(
            data=[{"id": 9, "company_id": 31, "title": "Safe"}], count=1
        )
        with patch.object(platform_support_case_repository.supabase, "table", return_value=query):
            rows, total = platform_support_case_repository.list_support_cases_for_platform_admin(
                limit=25, offset=0, company_id=31, status="open", priority="normal",
            )
        query.select.assert_called_once_with(platform_support_case_repository.CASE_FIELDS, count="exact")
        query.eq.assert_any_call("company_id", 31)
        query.eq.assert_any_call("status", "open")
        query.eq.assert_any_call("priority", "normal")
        self.assertEqual((rows, total), ([{"id": 9, "company_id": 31, "title": "Safe"}], 1))
        self.assertNotIn("*", platform_support_case_repository.CASE_FIELDS)


if __name__ == "__main__":
    unittest.main()
