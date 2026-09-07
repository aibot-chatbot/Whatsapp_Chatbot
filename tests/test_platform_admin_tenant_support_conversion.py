import unittest
from unittest.mock import Mock, patch

from flask import Flask

from app.database import tenant_support_repository
from app.database import platform_admin_repository
from app.routes.platform_admin_routes import platform_admin_bp
from app.services import platform_admin_service


class PlatformAdminTenantSupportConversionTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(platform_admin_bp)
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer token"}
        patches = [
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
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_authentication_and_platform_admin_guard_apply_to_writes(self):
        for path, method in (
            ("/api/platform-admin/tenant-support-requests/31", "patch"),
            ("/api/platform-admin/tenant-support-requests/31/convert", "post"),
        ):
            with self.subTest(path=path):
                self.assertEqual(getattr(self.client, method)(path).status_code, 401)
        with patch(
            "app.decorators.platform_admin_decorator.get_active_platform_admin_by_user_id",
            return_value=None,
        ):
            response = self.client.patch(
                "/api/platform-admin/tenant-support-requests/31",
                json={"status": "reviewed"}, headers=self.headers,
            )
        self.assertEqual(response.status_code, 403)

    def test_status_patch_accepts_only_reviewed_or_closed(self):
        for status in ("reviewed", "closed"):
            with patch.object(
                platform_admin_service.tenant_support_repository,
                "set_tenant_support_request_status_for_platform_admin",
                return_value={"request_id": 31, "status": status, "old_status": "new"},
            ) as rpc:
                response = self.client.patch(
                    "/api/platform-admin/tenant-support-requests/31",
                    json={"status": status}, headers=self.headers,
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["data"], {
                "request_id": 31, "status": status, "old_status": "new",
            })
            rpc.assert_called_once_with(31, 3, status)

    def test_status_patch_rejects_extra_fields_and_invalid_status(self):
        for payload in (
            {"status": "reviewed", "company_id": 2},
            {"status": "reviewed", "title": "not accepted"},
            {"status": "converted"},
        ):
            with self.subTest(payload=payload):
                response = self.client.patch(
                    "/api/platform-admin/tenant-support-requests/31",
                    json=payload, headers=self.headers,
                )
                self.assertEqual(response.status_code, 400)

    def test_conversion_requires_empty_body_and_returns_safe_result(self):
        with patch.object(
            platform_admin_service.tenant_support_repository,
            "convert_tenant_support_request_for_platform_admin",
            return_value={
                "request_id": 31, "status": "converted",
                "converted_platform_support_case_id": 44,
            },
        ) as rpc:
            response = self.client.post(
                "/api/platform-admin/tenant-support-requests/31/convert",
                json={}, headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"], {
            "request_id": 31, "status": "converted",
            "converted_platform_support_case_id": 44,
        })
        rpc.assert_called_once_with(31, 3)
        response = self.client.post(
            "/api/platform-admin/tenant-support-requests/31/convert",
            json={"priority": "urgent"}, headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_service_does_not_insert_duplicate_platform_audit_event(self):
        with patch.object(
            platform_admin_service.tenant_support_repository,
            "set_tenant_support_request_status_for_platform_admin",
            return_value={"request_id": 31, "status": "reviewed", "old_status": "new"},
        ), patch.object(platform_admin_service.platform_admin_repository,
                       "insert_platform_admin_audit_event") as audit:
            result = platform_admin_service.update_tenant_support_request(
                31, {"status": "reviewed"}, 3
            )
        self.assertEqual(result["status"], "reviewed")
        audit.assert_not_called()

    def test_audit_allowlist_accepts_new_actions_and_rejects_unsafe_metadata(self):
        common = {
            "outcome": "success", "endpoint": "/api/platform-admin/tenant-support-requests/<request_id>",
            "http_method": "PATCH", "old_status": "new", "new_status": "reviewed",
        }
        for action, metadata in (
            ("platform_admin.tenant_support_request.review", common),
            ("platform_admin.tenant_support_request.close", {
                **common, "new_status": "closed",
            }),
            ("platform_admin.tenant_support_request.convert", {
                **common,
                "endpoint": "/api/platform-admin/tenant-support-requests/<request_id>/convert",
                "http_method": "POST", "new_status": "converted",
                "converted_platform_support_case_id": 44,
            }),
        ):
            with self.subTest(action=action):
                platform_admin_repository.validate_audit_event(
                    3, action, "tenant_support_requests", "31", metadata
                )
        with self.assertRaises(ValueError):
            platform_admin_repository.validate_audit_event(
                3, "platform_admin.tenant_support_request.review",
                "tenant_support_requests", "31", {**common, "title": "unsafe"}
            )


class TenantSupportConversionRepositoryTests(unittest.TestCase):
    def test_status_repository_calls_rpc_and_validates_result(self):
        response = Mock(data={"request_id": 31, "status": "reviewed", "old_status": "new"})
        with patch.object(tenant_support_repository.supabase, "rpc", return_value=Mock(execute=Mock(return_value=response))) as rpc:
            result = tenant_support_repository.set_tenant_support_request_status_for_platform_admin(
                31, 3, "reviewed"
            )
        rpc.assert_called_once_with("set_tenant_support_request_status", {
            "p_request_id": 31, "p_platform_admin_user_id": 3, "p_status": "reviewed",
        })
        self.assertEqual(result["request_id"], 31)

    def test_repository_rejects_invalid_rpc_results(self):
        status_results = (None, {}, {"request_id": 0, "status": "reviewed"},
                          {"request_id": "31", "status": "reviewed"},
                          {"request_id": 31, "status": "new"})
        for result in status_results:
            with self.subTest(result=result), patch.object(
                tenant_support_repository.supabase, "rpc",
                return_value=Mock(execute=Mock(return_value=Mock(data=result))),
            ):
                with self.assertRaises(RuntimeError):
                    tenant_support_repository.set_tenant_support_request_status_for_platform_admin(
                        31, 3, "reviewed"
                    )
        conversion_results = (
            None, {}, {"request_id": 30, "status": "converted", "converted_platform_support_case_id": 44},
            {"request_id": 31, "status": "new", "converted_platform_support_case_id": 44},
            {"request_id": 31, "status": "converted", "converted_platform_support_case_id": 0},
            {"request_id": 31, "status": "converted", "converted_platform_support_case_id": "44"},
        )
        for result in conversion_results:
            with self.subTest(result=result), patch.object(
                tenant_support_repository.supabase, "rpc",
                return_value=Mock(execute=Mock(return_value=Mock(data=result))),
            ):
                with self.assertRaises(RuntimeError):
                    tenant_support_repository.convert_tenant_support_request_for_platform_admin(31, 3)

    def test_conversion_repository_never_uses_table_writes(self):
        response = Mock(data={
            "request_id": 31, "status": "converted",
            "converted_platform_support_case_id": 44,
        })
        with patch.object(tenant_support_repository.supabase, "rpc", return_value=Mock(execute=Mock(return_value=response))), \
             patch.object(tenant_support_repository.supabase, "table") as table:
            tenant_support_repository.convert_tenant_support_request_for_platform_admin(31, 3)
        table.assert_not_called()


if __name__ == "__main__":
    unittest.main()
