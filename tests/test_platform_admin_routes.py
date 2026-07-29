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
                "id": 7, "company_id": 100, "email": "internal@example.test", "status": "active", "role": "member",
            }),
            patch(
                "app.decorators.platform_admin_decorator.get_active_platform_admin_by_user_id",
                return_value={"id": 3, "user_id": 7, "is_active": True},
            ),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_only_seven_approved_get_routes_exist(self):
        rules = [rule for rule in self.app.url_map.iter_rules() if rule.rule.startswith("/api/platform-admin")]
        self.assertEqual({rule.rule for rule in rules}, {
            "/api/platform-admin/me",
            "/api/platform-admin/companies",
            "/api/platform-admin/companies/<int:company_id>",
            "/api/platform-admin/companies/<int:company_id>/subscription",
            "/api/platform-admin/companies/<int:company_id>/ai-credit-usage",
            "/api/platform-admin/companies/<int:company_id>/users",
            "/api/platform-admin/companies/<int:company_id>/chatbots",
        })
        self.assertTrue(all((rule.methods - {"HEAD", "OPTIONS"}) == {"GET"} for rule in rules))

    def test_blueprint_wide_guard_covers_all_routes(self):
        rules = [
            rule for rule in self.app.url_map.iter_rules()
            if rule.rule.startswith("/api/platform-admin")
        ]
        self.assertEqual(len(rules), 7)
        for rule in rules:
            path = rule.rule.replace("<int:company_id>", "2")
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

    def test_invalid_user_and_chatbot_list_parameters_have_stable_400_codes(self):
        cases = {
            "/api/platform-admin/companies/2/users?limit=0": "invalid_limit",
            "/api/platform-admin/companies/2/users?offset=-1": "invalid_offset",
            "/api/platform-admin/companies/2/users?sort_by=status": "invalid_sort_by",
            "/api/platform-admin/companies/2/users?sort_order=sideways": "invalid_sort_order",
            f"/api/platform-admin/companies/2/users?search={'x' * 101}": "invalid_search",
            "/api/platform-admin/companies/2/chatbots?state=deleted": "invalid_state",
            "/api/platform-admin/companies/2/chatbots?sort_by=status": "invalid_sort_by",
        }
        for path, code in cases.items():
            with self.subTest(path=path):
                response = self.client.get(path, headers=self.headers)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json["code"], code)

    def test_invalid_zero_company_id_rejected(self):
        response = self.client.get("/api/platform-admin/companies/0", headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["code"], "invalid_company_id")

    def test_audit_failure_response_never_contains_tenant_data(self):
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 2, "company_name": "Sensitive Tenant"},
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=RuntimeError("Supabase insert failed with secret details"),
        ):
            response = self.client.get("/api/platform-admin/companies/2", headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["code"], "platform_admin_audit_unavailable")
        self.assertNotIn("data", response.json)
        response_text = response.get_data(as_text=True).lower()
        self.assertNotIn("sensitive tenant", response_text)
        self.assertNotIn("supabase", response_text)
        self.assertNotIn("secret details", response_text)

    def test_audit_validation_failure_is_sanitized(self):
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 2, "company_name": "Sensitive Tenant"},
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=ValueError("Unsupported audit resource type"),
        ):
            response = self.client.get("/api/platform-admin/companies/2", headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["code"], "platform_admin_audit_unavailable")
        self.assertNotIn("data", response.json)
        response_text = response.get_data(as_text=True).lower()
        self.assertNotIn("sensitive tenant", response_text)
        self.assertNotIn("unsupported audit resource type", response_text)

    def test_authorized_missing_company_returns_audited_404(self):
        calls = []
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            side_effect=lambda company_id: calls.append("read") or None,
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=lambda *args, **kwargs: calls.append("audit") or {"id": 1},
        ) as audit:
            response = self.client.get(
                "/api/platform-admin/companies/404", headers=self.headers
            )
            calls.append("response")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json["code"], "company_not_found")
        self.assertEqual(calls, ["read", "audit", "response"])
        self.assertEqual(audit.call_args.args[4]["outcome"], "not_found")

    def test_missing_company_for_child_lists_does_not_query_child_repository(self):
        for path, action in (
            ("/api/platform-admin/companies/404/users", "platform_admin.company.users.read"),
            ("/api/platform-admin/companies/404/chatbots", "platform_admin.company.chatbots.read"),
        ):
            with self.subTest(path=path), patch.object(
                platform_admin_service.platform_company_repository,
                "get_company_for_platform_admin",
                return_value=None,
            ), patch.object(
                platform_admin_service.platform_company_user_repository,
                "list_company_users_for_platform_admin",
            ) as users, patch.object(
                platform_admin_service.platform_chatbot_repository,
                "list_company_chatbots_for_platform_admin",
            ) as chatbots, patch.object(
                platform_admin_service.platform_admin_repository,
                "insert_platform_admin_audit_event",
                return_value={"id": 1},
            ) as audit:
                response = self.client.get(path, headers=self.headers)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json["code"], "company_not_found")
                users.assert_not_called()
                chatbots.assert_not_called()
                self.assertEqual(audit.call_args.args[1], action)
                self.assertEqual(audit.call_args.args[4], {
                    "outcome": "not_found",
                    "endpoint": platform_admin_service.platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS[
                        "company_users" if path.endswith("/users") else "company_chatbots"
                    ],
                    "http_method": "GET",
                })

    def test_successful_company_audit_precedes_http_response(self):
        calls = []
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            side_effect=lambda company_id: calls.append("read") or {"id": company_id},
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=lambda *args, **kwargs: calls.append("audit") or {"id": 1},
        ):
            response = self.client.get(
                "/api/platform-admin/companies/2", headers=self.headers
            )
            calls.append("response")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["read", "audit", "response"])

    def test_company_and_billing_failures_are_sanitized(self):
        raw_detail = "Supabase connection failed: service_role=secret"
        with patch.object(
            platform_admin_service.platform_company_repository,
            "list_companies_for_platform_admin",
            side_effect=RuntimeError(raw_detail),
        ):
            company_response = self.client.get(
                "/api/platform-admin/companies", headers=self.headers
            )
        self.assertEqual(company_response.status_code, 503)
        self.assertEqual(
            company_response.json["code"], "platform_admin_data_unavailable"
        )

        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 2, "company_name": "Tenant Secret"},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "get_subscription_summary_for_platform_admin",
            side_effect=RuntimeError(raw_detail),
        ):
            billing_response = self.client.get(
                "/api/platform-admin/companies/2/subscription", headers=self.headers
            )
        self.assertEqual(billing_response.status_code, 503)
        self.assertEqual(
            billing_response.json["code"], "platform_admin_data_unavailable"
        )
        for response in (company_response, billing_response):
            body = response.get_data(as_text=True).lower()
            self.assertNotIn("supabase", body)
            self.assertNotIn("service_role", body)
            self.assertNotIn("secret", body)
            self.assertNotIn("data", response.json)

    def test_read_endpoints_create_expected_audit_events(self):
        cases = (
            ("/api/platform-admin/me", "platform_admin.identity.read"),
            ("/api/platform-admin/companies", "platform_admin.company.list"),
            (
                "/api/platform-admin/companies/2/subscription",
                "platform_admin.company.subscription.read",
            ),
            (
                "/api/platform-admin/companies/2/ai-credit-usage",
                "platform_admin.company.ai_credit_usage.read",
            ),
            (
                "/api/platform-admin/companies/2/users",
                "platform_admin.company.users.read",
            ),
            (
                "/api/platform-admin/companies/2/chatbots",
                "platform_admin.company.chatbots.read",
            ),
        )
        for path, expected_action in cases:
            with self.subTest(path=path), patch.object(
                platform_admin_service.platform_company_repository,
                "list_companies_for_platform_admin", return_value=([], 0),
            ), patch.object(
                platform_admin_service.platform_company_repository,
                "get_company_for_platform_admin", return_value={"id": 2},
            ), patch.object(
                platform_admin_service.platform_billing_repository,
                "get_subscription_summary_for_platform_admin", return_value=None,
            ), patch.object(
                platform_admin_service.platform_billing_repository,
                "get_ai_credit_balance_for_platform_admin", return_value=None,
            ), patch.object(
                platform_admin_service.platform_company_user_repository,
                "list_company_users_for_platform_admin", return_value=([], 0),
            ), patch.object(
                platform_admin_service.platform_chatbot_repository,
                "list_company_chatbots_for_platform_admin", return_value=([], 0),
            ), patch.object(
                platform_admin_service.platform_admin_repository,
                "insert_platform_admin_audit_event", return_value={"id": 1},
            ) as audit:
                response = self.client.get(path, headers=self.headers)
                self.assertEqual(response.status_code, 200)
                audit.assert_called_once()
                self.assertEqual(audit.call_args.args[1], expected_action)

    def test_child_lists_return_empty_success_without_company_or_search_echo(self):
        for path, key in (
            ("/api/platform-admin/companies/2/users?search=operator", "users"),
            ("/api/platform-admin/companies/2/chatbots?search=support&state=all", "chatbots"),
        ):
            with self.subTest(path=path), patch.object(
                platform_admin_service.platform_company_repository,
                "get_company_for_platform_admin", return_value={"id": 2},
            ), patch.object(
                platform_admin_service.platform_company_user_repository,
                "list_company_users_for_platform_admin", return_value=([], 0),
            ), patch.object(
                platform_admin_service.platform_chatbot_repository,
                "list_company_chatbots_for_platform_admin", return_value=([], 0),
            ), patch.object(
                platform_admin_service.platform_admin_repository,
                "insert_platform_admin_audit_event", return_value={"id": 1},
            ):
                response = self.client.get(path, headers=self.headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["data"][key], [])
                self.assertNotIn("company", response.json["data"])
                self.assertNotIn("search", response.json["data"]["filters"])
                self.assertTrue(response.json["data"]["filters"]["search_applied"])

    def test_child_data_failure_and_audit_failure_are_sanitized(self):
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin", return_value={"id": 2},
        ), patch.object(
            platform_admin_service.platform_company_user_repository,
            "list_company_users_for_platform_admin",
            side_effect=RuntimeError("Supabase secret detail"),
        ):
            response = self.client.get("/api/platform-admin/companies/2/users", headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["code"], "platform_admin_data_unavailable")
        self.assertNotIn("supabase", response.get_data(as_text=True).lower())

        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin", return_value={"id": 2},
        ), patch.object(
            platform_admin_service.platform_chatbot_repository,
            "list_company_chatbots_for_platform_admin",
            return_value=([{"bot_name": "Sensitive Bot"}], 1),
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=RuntimeError("audit secret"),
        ):
            audit_response = self.client.get("/api/platform-admin/companies/2/chatbots", headers=self.headers)
        self.assertEqual(audit_response.status_code, 503)
        self.assertEqual(audit_response.json["code"], "platform_admin_audit_unavailable")
        self.assertNotIn("Sensitive Bot", audit_response.get_data(as_text=True))

    def test_missing_ai_credit_balance_is_read_only_and_uninitialized(self):
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin", return_value={"id": 2},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "get_subscription_summary_for_platform_admin", return_value=None,
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "get_ai_credit_balance_for_platform_admin", return_value=None,
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "get_ai_usage_summary_for_platform_admin",
        ) as usage, patch.object(
            platform_admin_service.platform_billing_repository,
            "get_ai_credit_charge_summary_for_platform_admin",
        ) as charges, patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event", return_value={"id": 1},
        ):
            response = self.client.get(
                "/api/platform-admin/companies/2/ai-credit-usage",
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["data"]["credit_balance"]["initialized"])
        usage.assert_not_called()
        charges.assert_not_called()


if __name__ == "__main__":
    unittest.main()
