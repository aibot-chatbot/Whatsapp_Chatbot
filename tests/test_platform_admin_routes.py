import unittest
from unittest.mock import patch

from flask import Flask

from app.routes.platform_admin_routes import platform_admin_bp
from app.services import platform_admin_service


class PlatformAdminRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(platform_admin_bp)
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer token"}
        self.patches = [
            patch("app.decorators.auth_decorator.get_jwt_secret", return_value="secret"),
            patch("app.decorators.auth_decorator.jwt.decode", return_value={
                "user_id": 7, "company_id": 100, "role": "member", "is_platform_admin": False,
            }),
            patch("app.database.user_repository.get_user_by_id", return_value={
                "id": 7, "email": "internal@example.test", "status": "active", "role": "member",
            }),
            patch(
                "app.decorators.platform_admin_decorator.get_active_platform_admin_by_user_id",
                return_value={"id": 3, "user_id": 7, "is_active": True},
            ),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_only_five_approved_get_routes_exist(self):
        rules = [rule for rule in self.app.url_map.iter_rules() if rule.rule.startswith("/api/platform-admin")]
        self.assertEqual({rule.rule for rule in rules}, {
            "/api/platform-admin/me",
            "/api/platform-admin/companies",
            "/api/platform-admin/companies/<int:company_id>",
            "/api/platform-admin/companies/<int:company_id>/subscription",
            "/api/platform-admin/companies/<int:company_id>/ai-credit-usage",
        })
        self.assertTrue(all((rule.methods - {"HEAD", "OPTIONS"}) == {"GET"} for rule in rules))

    def test_blueprint_wide_guard_covers_all_routes(self):
        paths = (
            "/api/platform-admin/me", "/api/platform-admin/companies",
            "/api/platform-admin/companies/2",
            "/api/platform-admin/companies/2/subscription",
            "/api/platform-admin/companies/2/ai-credit-usage",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)

    def test_cross_tenant_target_comes_from_path_not_jwt_company(self):
        with patch.object(
            platform_admin_service, "get_company_detail", return_value={"id": 200}
        ) as service:
            response = self.client.get("/api/platform-admin/companies/200", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["id"], 200)
        service.assert_called_once_with(200, 3)

    def test_invalid_list_parameters_have_stable_400_codes(self):
        cases = {
            "limit=0": "invalid_limit",
            "limit=101": "invalid_limit",
            "offset=-1": "invalid_offset",
            "status=pending": "invalid_status",
            "sort_by=email": "invalid_sort_by",
            "sort_order=sideways": "invalid_sort_order",
            "search=%20%20": "invalid_search",
            f"search={'x' * 101}": "invalid_search",
        }
        for query, code in cases.items():
            with self.subTest(query=query):
                response = self.client.get(
                    f"/api/platform-admin/companies?{query}", headers=self.headers
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json["code"], code)

    def test_invalid_zero_company_id_rejected(self):
        response = self.client.get("/api/platform-admin/companies/0", headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["code"], "invalid_company_id")

    def test_audit_failure_response_never_contains_tenant_data(self):
        error = platform_admin_service.PlatformAdminServiceError(
            503, "platform_admin_audit_unavailable", "Platform audit logging is temporarily unavailable."
        )
        with patch.object(platform_admin_service, "get_company_detail", side_effect=error):
            response = self.client.get("/api/platform-admin/companies/2", headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["code"], "platform_admin_audit_unavailable")
        self.assertNotIn("data", response.json)


if __name__ == "__main__":
    unittest.main()
