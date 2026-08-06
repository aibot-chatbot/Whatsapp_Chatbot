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

    def test_approved_platform_admin_routes_have_read_and_support_case_boundaries(self):
        rules = [rule for rule in self.app.url_map.iter_rules() if rule.rule.startswith("/api/platform-admin")]
        self.assertEqual({rule.rule for rule in rules}, {
            "/api/platform-admin/me",
            "/api/platform-admin/overview",
            "/api/platform-admin/audit-events",
            "/api/platform-admin/companies",
            "/api/platform-admin/companies/<int:company_id>",
            "/api/platform-admin/companies/<int:company_id>/subscription",
            "/api/platform-admin/companies/<int:company_id>/subscription-history",
            "/api/platform-admin/companies/<int:company_id>/ai-credit-usage",
            "/api/platform-admin/companies/<int:company_id>/ai-credit-transactions",
            "/api/platform-admin/companies/<int:company_id>/billing-orders",
            "/api/platform-admin/companies/<int:company_id>/users",
            "/api/platform-admin/companies/<int:company_id>/chatbots",
            "/api/platform-admin/support-cases",
            "/api/platform-admin/support-case-assignees",
            "/api/platform-admin/support-cases/<int:case_id>",
            "/api/platform-admin/support-cases/<int:case_id>/notes",
            "/api/platform-admin/support-cases/<int:case_id>/assignment",
            "/api/platform-admin/support-cases/<int:case_id>/status",
            "/api/platform-admin/support-cases/<int:case_id>/priority",
            "/api/platform-admin/tenant-support-requests",
            "/api/platform-admin/tenant-support-requests/<int:request_id>",
            "/api/platform-admin/tenant-support-requests/<int:request_id>/convert",
        })
        methods = {}
        for rule in rules:
            methods.setdefault(rule.rule, set()).update(rule.methods - {"HEAD", "OPTIONS"})
        self.assertTrue(all(
            value == {"GET"}
            for key, value in methods.items()
            if "support-cases" not in key
            and "support-case-assignees" not in key
            and "tenant-support-requests" not in key
        ))
        self.assertEqual(methods["/api/platform-admin/support-cases"], {"GET", "POST"})
        self.assertEqual(methods["/api/platform-admin/support-case-assignees"], {"GET"})
        self.assertEqual(methods["/api/platform-admin/support-cases/<int:case_id>"], {"GET"})
        self.assertEqual(methods["/api/platform-admin/support-cases/<int:case_id>/notes"], {"POST"})
        self.assertEqual(methods["/api/platform-admin/support-cases/<int:case_id>/assignment"], {"PATCH"})
        self.assertEqual(methods["/api/platform-admin/support-cases/<int:case_id>/status"], {"PATCH"})
        self.assertEqual(methods["/api/platform-admin/support-cases/<int:case_id>/priority"], {"PATCH"})
        self.assertEqual(methods["/api/platform-admin/tenant-support-requests"], {"GET"})
        self.assertEqual(methods["/api/platform-admin/tenant-support-requests/<int:request_id>"], {"GET", "PATCH"})
        self.assertEqual(methods["/api/platform-admin/tenant-support-requests/<int:request_id>/convert"], {"POST"})

    def test_blueprint_wide_guard_covers_all_routes(self):
        rules = [
            rule for rule in self.app.url_map.iter_rules()
            if rule.rule.startswith("/api/platform-admin")
        ]
        self.assertEqual(len(rules), 24)
        for rule in rules:
            path = (
                rule.rule.replace("<int:company_id>", "2")
                .replace("<int:case_id>", "1")
                .replace("<int:request_id>", "1")
            )
            method = next(iter(rule.methods - {"HEAD", "OPTIONS"}))
            with self.subTest(path=path):
                self.assertEqual(self.client.open(path, method=method).status_code, 401)

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
            "/api/platform-admin/companies/2/subscription-history?limit=0": "invalid_limit",
            "/api/platform-admin/companies/2/subscription-history?offset=-1": "invalid_offset",
            "/api/platform-admin/companies/2/subscription-history?status=paused": "invalid_status",
            "/api/platform-admin/companies/2/ai-credit-transactions?limit=0": "invalid_limit",
            "/api/platform-admin/companies/2/ai-credit-transactions?offset=-1": "invalid_offset",
            "/api/platform-admin/companies/2/ai-credit-transactions?transaction_type=provider_cost": "invalid_transaction_type",
            "/api/platform-admin/companies/2/billing-orders?limit=0": "invalid_limit",
            "/api/platform-admin/companies/2/billing-orders?limit=101": "invalid_limit",
            "/api/platform-admin/companies/2/billing-orders?limit=true": "invalid_limit",
            "/api/platform-admin/companies/2/billing-orders?offset=-1": "invalid_offset",
            "/api/platform-admin/companies/2/billing-orders?offset=false": "invalid_offset",
            "/api/platform-admin/companies/2/billing-orders?status=": "invalid_status",
            "/api/platform-admin/companies/2/billing-orders?status=%20%20": "invalid_status",
            f"/api/platform-admin/companies/2/billing-orders?status={'x' * 21}": "invalid_status",
            "/api/platform-admin/companies/2/billing-orders?created_after=not-a-date": "invalid_created_after",
            "/api/platform-admin/companies/2/billing-orders?created_after=2026-07-31T00:00:00": "invalid_created_after",
            "/api/platform-admin/companies/2/billing-orders?created_before=not-a-date": "invalid_created_before",
            "/api/platform-admin/companies/2/billing-orders?created_before=2026-07-31T00:00:00": "invalid_created_before",
            "/api/platform-admin/companies/2/billing-orders?created_after=2026-08-01T00:00:00%2B00:00&created_before=2026-07-31T00:00:00%2B00:00": "invalid_created_before",
            "/api/platform-admin/audit-events?limit=0": "invalid_limit",
            "/api/platform-admin/audit-events?offset=-1": "invalid_offset",
            "/api/platform-admin/audit-events?action=unknown": "invalid_action",
            "/api/platform-admin/audit-events?resource_type=raw_payload": "invalid_resource_type",
            "/api/platform-admin/audit-events?actor_user_id=0": "invalid_actor_user_id",
            f"/api/platform-admin/audit-events?resource_id={'x' * 256}": "invalid_resource_id",
            "/api/platform-admin/audit-events?created_after=2026-07-31T00:00:00": "invalid_created_after",
            "/api/platform-admin/audit-events?created_before=2026-07-31T00:00:00": "invalid_created_before",
            "/api/platform-admin/audit-events?created_after=2026-08-01T00:00:00%2B00:00&created_before=2026-07-31T00:00:00%2B00:00": "invalid_created_before",
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
            (
                "/api/platform-admin/companies/404/subscription-history",
                "platform_admin.company.subscription_history.read",
            ),
            (
                "/api/platform-admin/companies/404/ai-credit-transactions",
                "platform_admin.company.ai_credit_transactions.read",
            ),
            (
                "/api/platform-admin/companies/404/billing-orders",
                "platform_admin.company.billing_orders.read",
            ),
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
                platform_admin_service.platform_billing_repository,
                "list_subscription_history_for_platform_admin",
            ) as history, patch.object(
                platform_admin_service.platform_billing_repository,
                "list_ai_credit_transactions_for_platform_admin",
            ) as transactions, patch.object(
                platform_admin_service.platform_billing_repository,
                "list_billing_orders_for_platform_admin",
            ) as billing_orders, patch.object(
                platform_admin_service.platform_admin_repository,
                "insert_platform_admin_audit_event",
                return_value={"id": 1},
            ) as audit:
                response = self.client.get(path, headers=self.headers)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json["code"], "company_not_found")
                users.assert_not_called()
                chatbots.assert_not_called()
                history.assert_not_called()
                transactions.assert_not_called()
                billing_orders.assert_not_called()
                self.assertEqual(audit.call_args.args[1], action)
                endpoint_key = (
                    "company_users" if path.endswith("/users")
                    else "company_chatbots" if path.endswith("/chatbots")
                    else "company_ai_credit_transactions" if path.endswith("/ai-credit-transactions")
                    else "company_billing_orders" if path.endswith("/billing-orders")
                    else "company_subscription_history"
                )
                self.assertEqual(audit.call_args.args[4], {
                    "outcome": "not_found",
                    "endpoint": platform_admin_service.platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS[endpoint_key],
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
            ("/api/platform-admin/overview", "platform_admin.operations.overview.read"),
            ("/api/platform-admin/companies", "platform_admin.company.list"),
            ("/api/platform-admin/audit-events", "platform_admin.audit_events.list"),
            (
                "/api/platform-admin/companies/2/subscription",
                "platform_admin.company.subscription.read",
            ),
            (
                "/api/platform-admin/companies/2/ai-credit-usage",
                "platform_admin.company.ai_credit_usage.read",
            ),
            (
                "/api/platform-admin/companies/2/ai-credit-transactions",
                "platform_admin.company.ai_credit_transactions.read",
            ),
            (
                "/api/platform-admin/companies/2/billing-orders",
                "platform_admin.company.billing_orders.read",
            ),
            (
                "/api/platform-admin/companies/2/subscription-history",
                "platform_admin.company.subscription_history.read",
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
                "get_company_counts_for_platform_admin",
                return_value={"total": 0, "active": 0, "inactive": 0},
            ), patch.object(
                platform_admin_service.platform_company_repository,
                "get_companies_by_ids_for_platform_admin", return_value={},
            ), patch.object(
                platform_admin_service.platform_admin_repository,
                "list_platform_admin_audit_events_for_platform_admin",
                return_value=([], 0),
            ), patch.object(
                platform_admin_service.platform_billing_repository,
                "get_latest_subscription_overview_for_platform_admin",
                return_value={
                    "by_status": {
                        "trialing": 0, "active": 0, "past_due": 0,
                        "expired": 0, "cancelled": 0,
                    },
                    "by_plan": [],
                    "attention_subscriptions": [],
                },
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
                platform_admin_service.platform_billing_repository,
                "list_subscription_history_for_platform_admin", return_value=([], 0),
            ), patch.object(
                platform_admin_service.platform_billing_repository,
                "list_ai_credit_transactions_for_platform_admin", return_value=([], 0),
            ), patch.object(
                platform_admin_service.platform_billing_repository,
                "list_billing_orders_for_platform_admin", return_value=([], 0),
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

    def test_audit_events_success_shape_filters_and_audit_metadata(self):
        rows = [{
            "id": 5,
            "platform_admin_user_id": 3,
            "action": "platform_admin.company.read",
            "resource_type": "company",
            "resource_id": "29",
            "metadata": {
                "outcome": "success",
                "endpoint": "/api/platform-admin/companies/<company_id>",
                "http_method": "GET",
                "company_filter_applied": True,
                "priority_filter_applied": False,
                "company_id": 31,
                "status": "open",
                "priority": "normal",
                "token": "must be omitted",
                "raw_payload": {"nested": "must be omitted"},
            },
            "created_at": "2026-07-31T08:00:00+00:00",
            "secret_extra": "must be omitted",
        }]
        calls = []
        with patch.object(
            platform_admin_service.platform_admin_repository,
            "list_platform_admin_audit_events_for_platform_admin",
            side_effect=lambda **kwargs: calls.append("read") or (rows, 7),
        ) as repository, patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=lambda *args, **kwargs: calls.append("audit") or {"id": 99},
        ) as audit:
            response = self.client.get(
                "/api/platform-admin/audit-events?limit=1&offset=2"
                "&action=platform_admin.company.read&resource_type=company"
                "&actor_user_id=32&resource_id=29"
                "&created_after=2026-07-01T00:00:00%2B00:00"
                "&created_before=2026-08-01T00:00:00%2B00:00",
                headers=self.headers,
            )
            calls.append("response")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["read", "audit", "response"])
        repository.assert_called_once()
        kwargs = repository.call_args.kwargs
        self.assertEqual(kwargs["limit"], 1)
        self.assertEqual(kwargs["offset"], 2)
        self.assertEqual(kwargs["action"], "platform_admin.company.read")
        self.assertEqual(kwargs["resource_type"], "company")
        self.assertEqual(kwargs["actor_user_id"], 32)
        self.assertEqual(kwargs["resource_id"], "29")
        event = response.json["data"]["audit_events"][0]
        self.assertEqual(set(event), {
            "id", "actor", "action", "resource_type", "resource_id",
            "metadata", "created_at",
        })
        self.assertEqual(event["actor"], {"platform_admin_user_id": 3})
        self.assertEqual(event["metadata"], {
            "outcome": "success",
            "endpoint": "/api/platform-admin/companies/<company_id>",
            "http_method": "GET",
            "company_filter_applied": True,
            "priority_filter_applied": False,
            "company_id": 31,
            "status": "open",
            "priority": "normal",
        })
        response_text = response.get_data(as_text=True)
        self.assertNotIn("must be omitted", response_text)
        self.assertNotIn("secret_extra", response_text)
        self.assertEqual(response.json["data"]["pagination"]["total"], 7)
        self.assertEqual(response.json["data"]["ordering"]["tie_breaker"], "id desc")
        audit.assert_called_once()
        self.assertEqual(audit.call_args.args[1], "platform_admin.audit_events.list")
        self.assertEqual(audit.call_args.args[2], "platform_admin_audit_events")
        self.assertIsNone(audit.call_args.args[3])
        self.assertEqual(audit.call_args.args[4], {
            "outcome": "success",
            "endpoint": "/api/platform-admin/audit-events",
            "http_method": "GET",
            "limit": 1,
            "offset": 2,
            "action_filter_applied": True,
            "resource_type_filter_applied": True,
            "actor_user_id_filter_applied": True,
            "resource_id_filter_applied": True,
            "created_after_filter_applied": True,
            "created_before_filter_applied": True,
            "returned_count": 1,
        })

    def test_audit_events_empty_list_and_repository_failure_are_sanitized(self):
        with patch.object(
            platform_admin_service.platform_admin_repository,
            "list_platform_admin_audit_events_for_platform_admin",
            return_value=([], 0),
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            return_value={"id": 1},
        ):
            response = self.client.get("/api/platform-admin/audit-events", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["audit_events"], [])
        self.assertEqual(response.json["data"]["pagination"]["returned"], 0)

        with patch.object(
            platform_admin_service.platform_admin_repository,
            "list_platform_admin_audit_events_for_platform_admin",
            side_effect=RuntimeError("Supabase service_role raw detail"),
        ):
            failure_response = self.client.get("/api/platform-admin/audit-events", headers=self.headers)
        self.assertEqual(failure_response.status_code, 503)
        self.assertEqual(failure_response.json["code"], "platform_admin_data_unavailable")
        self.assertNotIn("supabase", failure_response.get_data(as_text=True).lower())
        self.assertNotIn("service_role", failure_response.get_data(as_text=True).lower())

    def test_audit_events_audit_failure_withholds_rows(self):
        with patch.object(
            platform_admin_service.platform_admin_repository,
            "list_platform_admin_audit_events_for_platform_admin",
            return_value=([
                {
                    "id": 5,
                    "platform_admin_user_id": 3,
                    "action": "platform_admin.company.read",
                    "resource_type": "company",
                    "resource_id": "29",
                    "metadata": {"outcome": "success"},
                    "created_at": "2026-07-31T08:00:00+00:00",
                }
            ], 1),
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=RuntimeError("audit insert raw detail"),
        ):
            response = self.client.get("/api/platform-admin/audit-events", headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["code"], "platform_admin_audit_unavailable")
        self.assertNotIn("audit_events", response.get_data(as_text=True))
        self.assertNotIn("audit insert raw detail", response.get_data(as_text=True))

    def test_subscription_history_success_shape_and_audit_metadata(self):
        calls = []
        rows = [{
            "id": 123,
            "status": "past_due",
            "plan": {
                "code": "pro",
                "name": "Pro",
                "price": 16900,
                "is_active": False,
                "gateway_reference": "gateway-secret",
                "included_ai_credit_micro_myr": 60000000,
            },
            "pending_plan": {
                "code": "advanced",
                "name": "Advanced",
                "price": 8900,
                "is_active": True,
                "gateway_reference": "gateway-pending",
                "included_ai_credit_micro_myr": 20000000,
            },
            "starts_at": None,
            "current_period_start": None,
            "current_period_end": None,
            "trial_ends_at": None,
            "cancelled_at": None,
            "ends_at": None,
            "plan_change_effective_at": None,
            "cancellation_scheduled_at": None,
            "cancellation_effective_at": None,
            "status_updated_at": None,
            "created_at": "2026-07-01T00:00:00+00:00",
            "updated_at": "2026-07-02T00:00:00+00:00",
            "company_id": 2,
            "plan_id": 3,
        }]
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            side_effect=lambda company_id: calls.append("company") or {"id": company_id},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "list_subscription_history_for_platform_admin",
            side_effect=lambda **kwargs: calls.append("history") or (rows, 4),
        ) as history, patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=lambda *args: calls.append("audit") or {"id": 1},
        ) as audit:
            response = self.client.get(
                "/api/platform-admin/companies/2/subscription-history?limit=1&offset=1&status=past_due",
                headers=self.headers,
            )
            calls.append("response")
        self.assertEqual(response.status_code, 200)
        data = response.json["data"]
        self.assertEqual(calls, ["company", "history", "audit", "response"])
        history.assert_called_once_with(company_id=2, limit=1, offset=1, status="past_due")
        self.assertEqual(data["pagination"], {
            "limit": 1,
            "offset": 1,
            "returned": 1,
            "total": 4,
            "has_more": True,
        })
        self.assertEqual(data["filters"], {"status": "past_due", "status_applied": True})
        self.assertEqual(data["ordering"], {
            "by": "created_at",
            "order": "desc",
            "tie_breaker": "id desc",
        })
        self.assertNotIn("company", data)
        self.assertNotIn("company_id", data["subscriptions"][0])
        self.assertNotIn("plan_id", data["subscriptions"][0])
        self.assertEqual(
            set(data["subscriptions"][0]["plan"]),
            {"code", "name"},
        )
        self.assertEqual(
            data["subscriptions"][0]["plan"],
            {"code": "pro", "name": "Pro"},
        )
        self.assertEqual(
            set(data["subscriptions"][0]["pending_plan"]),
            {"code", "name"},
        )
        self.assertEqual(
            data["subscriptions"][0]["pending_plan"],
            {"code": "advanced", "name": "Advanced"},
        )
        self.assertEqual(audit.call_args.args[1], "platform_admin.company.subscription_history.read")
        self.assertEqual(audit.call_args.args[2], "company_subscription_history")
        self.assertEqual(audit.call_args.args[3], "2")
        self.assertEqual(audit.call_args.args[4], {
            "outcome": "success",
            "endpoint": platform_admin_service.platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS[
                "company_subscription_history"
            ],
            "http_method": "GET",
            "limit": 1,
            "offset": 1,
            "status_filter": "past_due",
            "returned_count": 1,
        })

    def test_subscription_history_empty_and_null_optional_values(self):
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 2},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "list_subscription_history_for_platform_admin",
            return_value=([], 0),
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            return_value={"id": 1},
        ):
            response = self.client.get(
                "/api/platform-admin/companies/2/subscription-history",
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["subscriptions"], [])
        self.assertEqual(response.json["data"]["pagination"]["returned"], 0)
        self.assertFalse(response.json["data"]["pagination"]["has_more"])

    def test_subscription_history_data_and_audit_failures_are_sanitized(self):
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 2},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "list_subscription_history_for_platform_admin",
            side_effect=RuntimeError("Supabase service_role secret"),
        ):
            response = self.client.get(
                "/api/platform-admin/companies/2/subscription-history",
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["code"], "platform_admin_data_unavailable")
        self.assertNotIn("supabase", response.get_data(as_text=True).lower())
        self.assertNotIn("data", response.json)

        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 2},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "list_subscription_history_for_platform_admin",
            return_value=([{"id": 123, "status": "past_due"}], 1),
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=RuntimeError("audit secret"),
        ):
            audit_response = self.client.get(
                "/api/platform-admin/companies/2/subscription-history",
                headers=self.headers,
            )
        self.assertEqual(audit_response.status_code, 503)
        self.assertEqual(audit_response.json["code"], "platform_admin_audit_unavailable")
        self.assertNotIn("past_due", audit_response.get_data(as_text=True))
        self.assertNotIn("data", audit_response.json)

    def test_ai_credit_transactions_success_shape_and_audit_metadata(self):
        calls = []
        rows = [{
            "id": 321,
            "transaction_type": "usage_debit",
            "included_delta_micro_myr": -500000,
            "topup_delta_micro_myr": 0,
            "included_balance_after_micro_myr": 9500000,
            "topup_balance_after_micro_myr": 2000000,
            "customer_charge_micro_myr": None,
            "uncovered_charge_micro_myr": 0,
            "period_start": None,
            "period_end": None,
            "created_at": "2026-07-15T12:00:00+00:00",
            "provider_cost_micro_usd": 123,
            "fx_rate_micro_myr_per_usd": 456,
            "markup_basis_points": 2500,
            "description": "sensitive",
            "payment_reference": "payment-secret",
            "idempotency_key": "idem-secret",
            "company_id": 2,
            "subscription_id": 4,
            "ai_usage_log_id": 5,
            "reversal_of_transaction_id": 6,
        }]
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            side_effect=lambda company_id: calls.append("company") or {"id": company_id},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "list_ai_credit_transactions_for_platform_admin",
            side_effect=lambda **kwargs: calls.append("transactions") or (rows, 4),
        ) as transactions, patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=lambda *args: calls.append("audit") or {"id": 1},
        ) as audit:
            response = self.client.get(
                "/api/platform-admin/companies/2/ai-credit-transactions?limit=1&offset=1&transaction_type=usage_debit",
                headers=self.headers,
            )
            calls.append("response")
        self.assertEqual(response.status_code, 200)
        data = response.json["data"]
        self.assertEqual(calls, ["company", "transactions", "audit", "response"])
        transactions.assert_called_once_with(
            company_id=2, limit=1, offset=1, transaction_type="usage_debit"
        )
        self.assertEqual(data["pagination"], {
            "limit": 1,
            "offset": 1,
            "returned": 1,
            "total": 4,
            "has_more": True,
        })
        self.assertEqual(data["filters"], {"transaction_type": "usage_debit"})
        self.assertEqual(data["ordering"], {
            "by": "created_at",
            "order": "desc",
            "tie_breaker": "id desc",
        })
        transaction = data["transactions"][0]
        self.assertEqual(set(transaction), {
            "id",
            "transaction_type",
            "included_delta_micro_myr",
            "topup_delta_micro_myr",
            "included_balance_after_micro_myr",
            "topup_balance_after_micro_myr",
            "customer_charge_micro_myr",
            "uncovered_charge_micro_myr",
            "period_start",
            "period_end",
            "created_at",
        })
        self.assertIsNone(transaction["customer_charge_micro_myr"])
        self.assertIsNone(transaction["period_start"])
        self.assertIsNone(transaction["period_end"])
        self.assertEqual(transaction["included_delta_micro_myr"], -500000)
        response_text = response.get_data(as_text=True)
        for prohibited in (
            "provider_cost_micro_usd", "fx_rate_micro_myr_per_usd",
            "markup_basis_points", "description", "payment_reference",
            "idempotency_key", "company_id", "subscription_id",
            "ai_usage_log_id", "reversal_of_transaction_id", "payment-secret",
        ):
            self.assertNotIn(prohibited, response_text)
        self.assertEqual(audit.call_args.args[1], "platform_admin.company.ai_credit_transactions.read")
        self.assertEqual(audit.call_args.args[2], "company_ai_credit_transactions")
        self.assertEqual(audit.call_args.args[3], "2")
        self.assertEqual(audit.call_args.args[4], {
            "outcome": "success",
            "endpoint": platform_admin_service.platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS[
                "company_ai_credit_transactions"
            ],
            "http_method": "GET",
            "limit": 1,
            "offset": 1,
            "transaction_type_filter": "usage_debit",
            "returned_count": 1,
        })

    def test_ai_credit_transactions_empty_and_failures_are_sanitized(self):
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 2},
            ), patch.object(
                platform_admin_service.platform_billing_repository,
                "list_ai_credit_transactions_for_platform_admin",
                return_value=([], 0),
            ), patch.object(
                platform_admin_service.platform_billing_repository,
                "list_billing_orders_for_platform_admin",
                return_value=([], 0),
            ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            return_value={"id": 1},
        ):
            response = self.client.get(
                "/api/platform-admin/companies/2/ai-credit-transactions",
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["transactions"], [])
        self.assertEqual(response.json["data"]["pagination"]["returned"], 0)
        self.assertFalse(response.json["data"]["pagination"]["has_more"])

        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 2},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "list_ai_credit_transactions_for_platform_admin",
            side_effect=RuntimeError("Supabase service_role secret"),
        ):
            data_response = self.client.get(
                "/api/platform-admin/companies/2/ai-credit-transactions",
                headers=self.headers,
            )
        self.assertEqual(data_response.status_code, 503)
        self.assertEqual(data_response.json["code"], "platform_admin_data_unavailable")
        self.assertNotIn("supabase", data_response.get_data(as_text=True).lower())
        self.assertNotIn("data", data_response.json)

        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 2},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "list_ai_credit_transactions_for_platform_admin",
            return_value=([{"id": 123, "transaction_type": "usage_debit"}], 1),
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=RuntimeError("audit secret"),
        ):
            audit_response = self.client.get(
                "/api/platform-admin/companies/2/ai-credit-transactions",
                headers=self.headers,
            )
        self.assertEqual(audit_response.status_code, 503)
        self.assertEqual(audit_response.json["code"], "platform_admin_audit_unavailable")
        self.assertNotIn("usage_debit", audit_response.get_data(as_text=True))
        self.assertNotIn("data", audit_response.json)

    def test_ai_credit_transactions_accept_all_approved_type_filters(self):
        for transaction_type in sorted(platform_admin_service.platform_billing_repository.AI_CREDIT_TRANSACTION_TYPES):
            with self.subTest(transaction_type=transaction_type), patch.object(
                platform_admin_service.platform_company_repository,
                "get_company_for_platform_admin",
                return_value={"id": 2},
            ), patch.object(
                platform_admin_service.platform_billing_repository,
                "list_ai_credit_transactions_for_platform_admin",
                return_value=([], 0),
            ) as transactions, patch.object(
                platform_admin_service.platform_admin_repository,
                "insert_platform_admin_audit_event",
                return_value={"id": 1},
            ) as audit:
                response = self.client.get(
                    f"/api/platform-admin/companies/2/ai-credit-transactions?transaction_type={transaction_type}",
                    headers=self.headers,
                )
                self.assertEqual(response.status_code, 200)
                transactions.assert_called_once_with(
                    company_id=2, limit=25, offset=0, transaction_type=transaction_type
                )
                self.assertEqual(
                    audit.call_args.args[4]["transaction_type_filter"],
                    transaction_type,
                )

    def test_ai_credit_transaction_type_blank_is_rejected_but_omitted_is_unfiltered(self):
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 2},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "list_ai_credit_transactions_for_platform_admin",
            return_value=([], 0),
        ) as transactions, patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            return_value={"id": 1},
        ) as audit:
            response = self.client.get(
                "/api/platform-admin/companies/2/ai-credit-transactions",
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        transactions.assert_called_once_with(
            company_id=2, limit=25, offset=0, transaction_type=None
        )
        self.assertEqual(response.json["data"]["filters"], {"transaction_type": None})
        self.assertIsNone(audit.call_args.args[4]["transaction_type_filter"])

        for query in ("transaction_type=", "transaction_type=%20%20"):
            with self.subTest(query=query):
                response = self.client.get(
                    f"/api/platform-admin/companies/2/ai-credit-transactions?{query}",
                    headers=self.headers,
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json["code"], "invalid_transaction_type")

        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 2},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "list_ai_credit_transactions_for_platform_admin",
            return_value=([], 0),
        ) as trimmed_transactions, patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            return_value={"id": 1},
        ):
            response = self.client.get(
                "/api/platform-admin/companies/2/ai-credit-transactions?transaction_type=%20usage_debit%20",
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        trimmed_transactions.assert_called_once_with(
            company_id=2, limit=25, offset=0, transaction_type="usage_debit"
        )

    def test_billing_orders_success_shape_filters_and_audit_metadata(self):
        calls = []
        rows = [{
            "id": 901,
            "status": "credited",
            "amount_sen": 3900,
            "new_plan": {
                "code": "pro",
                "name": "Pro",
                "price": 16900,
                "currency": "MYR",
                "is_active": False,
            },
            "source_plan": {
                "code": "advanced",
                "name": "Advanced",
                "billing_interval": "monthly",
            },
            "activation_status": "completed",
            "activation_type": "upgrade",
            "reconciliation_required": False,
            "created_at": "2026-07-01T00:00:00+00:00",
            "updated_at": "2026-07-01T00:03:00+00:00",
            "paid_at": "2026-07-01T00:01:00+00:00",
            "credited_at": None,
            "expires_at": "2026-07-02T00:00:00+00:00",
            "activation_claimed_at": "2026-07-01T00:01:10+00:00",
            "activation_completed_at": "2026-07-01T00:02:00+00:00",
            "credit_granted_at": None,
            "company_id": 2,
            "subscription_id": 4,
            "order_reference": "11111111-1111-4111-8111-111111111111",
            "gateway_order_id": "gateway-secret",
            "checkout_url": "https://pay.example/secret",
            "payment_reference": "payment-secret",
            "payment_gateway": "toyyibpay",
            "idempotency_key": "idem-secret",
            "activation_error_message": "raw error",
            "last_reconciliation_error": "stack trace",
        }]
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            side_effect=lambda company_id: calls.append("company") or {"id": company_id},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "list_billing_orders_for_platform_admin",
            side_effect=lambda **kwargs: calls.append("orders") or (rows, 4),
        ) as orders, patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=lambda *args: calls.append("audit") or {"id": 1},
        ) as audit:
            response = self.client.get(
                "/api/platform-admin/companies/2/billing-orders?limit=1&offset=1&status=credited&created_after=2026-07-01T00:00:00%2B00:00&created_before=2026-08-01T00:00:00%2B00:00",
                headers=self.headers,
            )
            calls.append("response")
        self.assertEqual(response.status_code, 200)
        data = response.json["data"]
        self.assertEqual(calls, ["company", "orders", "audit", "response"])
        called_kwargs = orders.call_args.kwargs
        self.assertEqual(called_kwargs["company_id"], 2)
        self.assertEqual(called_kwargs["limit"], 1)
        self.assertEqual(called_kwargs["offset"], 1)
        self.assertEqual(called_kwargs["status"], "credited")
        self.assertEqual(called_kwargs["created_after"].isoformat(), "2026-07-01T00:00:00+00:00")
        self.assertEqual(called_kwargs["created_before"].isoformat(), "2026-08-01T00:00:00+00:00")
        self.assertEqual(data["pagination"], {
            "limit": 1,
            "offset": 1,
            "returned": 1,
            "total": 4,
            "has_more": True,
        })
        self.assertEqual(data["filters"]["status"], "credited")
        self.assertTrue(data["filters"]["status_applied"])
        self.assertEqual(data["ordering"], {
            "by": "created_at",
            "order": "desc",
            "tie_breaker": "id desc",
        })
        self.assertEqual(data["amount_units"], {
            "amount_sen": "integer sen as stored; currency is not returned or inferred",
        })
        order = data["billing_orders"][0]
        self.assertEqual(set(order), {
            "id", "status", "amount_sen", "new_plan", "source_plan",
            "activation_status", "activation_type", "reconciliation_required",
            "created_at", "updated_at", "paid_at", "credited_at", "expires_at",
            "activation_claimed_at", "activation_completed_at", "credit_granted_at",
        })
        self.assertEqual(order["amount_sen"], 3900)
        self.assertIsNone(order["credited_at"])
        self.assertEqual(order["new_plan"], {"code": "pro", "name": "Pro"})
        self.assertEqual(order["source_plan"], {"code": "advanced", "name": "Advanced"})
        response_text = response.get_data(as_text=True).lower()
        for prohibited in (
            "company_id", "subscription_id", "order_reference", "gateway_order_id",
            "checkout_url", "payment_reference", "payment_gateway",
            "idempotency_key", "activation_error_message",
            "last_reconciliation_error", "gateway-secret", "payment-secret",
            "myr", "price", "billing_interval",
        ):
            self.assertNotIn(prohibited, response_text)
        self.assertEqual(audit.call_args.args[1], "platform_admin.company.billing_orders.read")
        self.assertEqual(audit.call_args.args[2], "company_billing_orders")
        self.assertEqual(audit.call_args.args[3], "2")
        self.assertEqual(audit.call_args.args[4], {
            "outcome": "success",
            "endpoint": platform_admin_service.platform_admin_repository.PLATFORM_ADMIN_ENDPOINTS[
                "company_billing_orders"
            ],
            "http_method": "GET",
            "limit": 1,
            "offset": 1,
            "status_filter_applied": True,
            "created_after_filter_applied": True,
            "created_before_filter_applied": True,
            "returned_count": 1,
        })

    def test_billing_orders_empty_and_failures_are_sanitized(self):
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 2},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "list_billing_orders_for_platform_admin",
            return_value=([], 0),
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            return_value={"id": 1},
        ):
            response = self.client.get(
                "/api/platform-admin/companies/2/billing-orders",
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["billing_orders"], [])
        self.assertEqual(response.json["data"]["pagination"]["returned"], 0)
        self.assertFalse(response.json["data"]["pagination"]["has_more"])
        self.assertIsNone(response.json["data"]["filters"]["status"])

        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 2},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "list_billing_orders_for_platform_admin",
            side_effect=RuntimeError("Supabase service_role secret"),
        ):
            data_response = self.client.get(
                "/api/platform-admin/companies/2/billing-orders",
                headers=self.headers,
            )
        self.assertEqual(data_response.status_code, 503)
        self.assertEqual(data_response.json["code"], "platform_admin_data_unavailable")
        self.assertNotIn("supabase", data_response.get_data(as_text=True).lower())
        self.assertNotIn("data", data_response.json)

        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 2},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "list_billing_orders_for_platform_admin",
            return_value=([{"id": 123, "status": "credited"}], 1),
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=RuntimeError("audit secret"),
        ):
            audit_response = self.client.get(
                "/api/platform-admin/companies/2/billing-orders",
                headers=self.headers,
            )
        self.assertEqual(audit_response.status_code, 503)
        self.assertEqual(audit_response.json["code"], "platform_admin_audit_unavailable")
        self.assertNotIn("credited", audit_response.get_data(as_text=True))
        self.assertNotIn("data", audit_response.json)

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

    def test_operations_overview_success_shape_and_audit_metadata(self):
        calls = []
        overview = {
            "by_status": {
                "trialing": 1, "active": 2, "past_due": 1,
                "expired": 1, "cancelled": 0,
            },
            "by_plan": [{"code": "free", "name": "Free", "count": 1}],
            "attention_subscriptions": [
                {
                    "company_id": 2,
                    "subscription_status": "past_due",
                    "plan_code": "pro",
                    "plan_name": "Pro",
                    "status_updated_at": "2026-07-29T00:00:00+00:00",
                    "current_period_end": "2026-07-28T00:00:00+00:00",
                },
                {
                    "company_id": 3,
                    "subscription_status": "expired",
                    "plan_code": "free",
                    "plan_name": "Free",
                    "status_updated_at": "2026-07-20T00:00:00+00:00",
                    "current_period_end": "2026-07-19T00:00:00+00:00",
                },
                {
                    "company_id": 4,
                    "subscription_status": "paused",
                    "plan_code": "legacy",
                    "plan_name": "Legacy",
                    "status_updated_at": "2026-07-18T00:00:00+00:00",
                    "current_period_end": "2026-07-17T00:00:00+00:00",
                },
                {
                    "company_id": "bad",
                    "subscription_status": "expired",
                    "plan_code": "pro",
                    "plan_name": "Pro",
                    "status_updated_at": "2026-07-18T00:00:00+00:00",
                    "current_period_end": "2026-07-17T00:00:00+00:00",
                },
            ],
        }
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_counts_for_platform_admin",
            side_effect=lambda: calls.append("companies") or {"total": 5, "active": 4, "inactive": 1},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "get_latest_subscription_overview_for_platform_admin",
            side_effect=lambda: calls.append("subscriptions") or overview,
        ), patch.object(
            platform_admin_service.platform_company_repository,
            "get_companies_by_ids_for_platform_admin",
            side_effect=lambda ids: calls.append("company_ids") or {
                2: {"id": 2, "company_name": "Tenant", "status": "active"},
                3: {"id": 3, "company_name": "Expired Tenant", "status": "active"},
                4: {"id": 4, "company_name": "Paused Tenant", "status": "active"},
            },
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=lambda *args: calls.append("audit") or {"id": 1},
        ) as audit:
            response = self.client.get("/api/platform-admin/overview", headers=self.headers)
            calls.append("response")
        self.assertEqual(response.status_code, 200)
        data = response.json["data"]
        self.assertEqual(set(data), {
            "generated_at", "companies", "subscriptions",
            "attention_companies", "operational_alerts",
        })
        self.assertEqual(data["companies"], {"total": 5, "active": 4, "inactive": 1})
        self.assertEqual(data["subscriptions"]["by_status"]["past_due"], 1)
        self.assertEqual(data["subscriptions"]["by_plan"], [{"code": "free", "name": "Free", "count": 1}])
        self.assertEqual(set(data["attention_companies"][0]), {
            "company_id",
            "company_name",
            "company_status",
            "subscription_status",
            "plan_code",
            "plan_name",
            "status_updated_at",
            "current_period_end",
        })
        self.assertEqual(data["attention_companies"][0]["company_name"], "Tenant")
        self.assertEqual(data["attention_companies"][0]["subscription_status"], "past_due")
        self.assertEqual(len(data["attention_companies"]), 3)
        alerts = data["operational_alerts"]["alerts"]
        self.assertEqual(len(alerts), 2)
        self.assertEqual(alerts[0], {
            "type": "subscription_past_due",
            "severity": "warning",
            "company_id": 2,
            "company_name": "Tenant",
            "company_status": "active",
            "summary": "Subscription is past due",
            "details": {
                "subscription_status": "past_due",
                "plan_code": "pro",
                "plan_name": "Pro",
                "current_period_end": "2026-07-28T00:00:00+00:00",
                "status_updated_at": "2026-07-29T00:00:00+00:00",
            },
            "investigation_url": "platform-admin-company.html?company_id=2",
        })
        self.assertEqual(alerts[1]["type"], "subscription_expired")
        self.assertEqual(alerts[1]["severity"], "critical")
        self.assertEqual(alerts[1]["summary"], "Subscription is expired")
        self.assertEqual(data["operational_alerts"]["summary"], {
            "total": 2, "critical": 1, "warning": 1, "info": 0,
        })
        self.assertEqual(data["operational_alerts"]["limits"], {"max_alerts": 10})
        self.assertEqual(calls, ["companies", "subscriptions", "company_ids", "audit", "response"])
        self.assertEqual(audit.call_args.args[1], "platform_admin.operations.overview.read")
        self.assertEqual(audit.call_args.args[2], "platform_operations_overview")
        self.assertIsNone(audit.call_args.args[3])
        self.assertEqual(set(audit.call_args.args[4]), {
            "outcome", "endpoint", "http_method", "attention_company_count", "generated_at",
        })

    def test_operations_overview_empty_data_returns_zeroes(self):
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_counts_for_platform_admin",
            return_value={"total": 0, "active": 0, "inactive": 0},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "get_latest_subscription_overview_for_platform_admin",
            return_value={"by_status": {}, "by_plan": [], "attention_subscriptions": []},
        ), patch.object(
            platform_admin_service.platform_company_repository,
            "get_companies_by_ids_for_platform_admin", return_value={},
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event", return_value={"id": 1},
        ):
            response = self.client.get("/api/platform-admin/overview", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["companies"], {"total": 0, "active": 0, "inactive": 0})
        self.assertEqual(response.json["data"]["subscriptions"]["by_status"], {
            "trialing": 0, "active": 0, "past_due": 0, "expired": 0, "cancelled": 0,
        })
        self.assertEqual(response.json["data"]["subscriptions"]["by_plan"], [])
        self.assertEqual(response.json["data"]["attention_companies"], [])
        self.assertEqual(response.json["data"]["operational_alerts"], {
            "alerts": [],
            "summary": {"total": 0, "critical": 0, "warning": 0, "info": 0},
            "limits": {"max_alerts": 10},
        })

    def test_operations_overview_operational_alerts_are_capped_at_ten(self):
        subscriptions = [
            {
                "company_id": company_id,
                "subscription_status": "expired" if company_id % 2 else "past_due",
                "plan_code": "pro",
                "plan_name": "Pro",
                "status_updated_at": f"2026-07-{company_id:02d}T00:00:00+00:00",
                "current_period_end": f"2026-07-{company_id:02d}T00:00:00+00:00",
            }
            for company_id in range(1, 13)
        ]
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_counts_for_platform_admin",
            return_value={"total": 12, "active": 12, "inactive": 0},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "get_latest_subscription_overview_for_platform_admin",
            return_value={
                "by_status": {"past_due": 6, "expired": 6},
                "by_plan": [],
                "attention_subscriptions": subscriptions,
            },
        ), patch.object(
            platform_admin_service.platform_company_repository,
            "get_companies_by_ids_for_platform_admin",
            return_value={
                company_id: {"id": company_id, "company_name": f"Tenant {company_id}", "status": "active"}
                for company_id in range(1, 13)
            },
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event", return_value={"id": 1},
        ):
            response = self.client.get("/api/platform-admin/overview", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        alerts = response.json["data"]["operational_alerts"]["alerts"]
        self.assertEqual(len(alerts), 10)
        self.assertEqual(response.json["data"]["operational_alerts"]["summary"]["total"], 10)
        self.assertEqual(response.json["data"]["operational_alerts"]["limits"], {"max_alerts": 10})

    def test_operations_overview_repository_and_audit_failures_are_sanitized(self):
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_counts_for_platform_admin",
            side_effect=RuntimeError("Supabase service_role secret"),
        ):
            response = self.client.get("/api/platform-admin/overview", headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["code"], "platform_admin_data_unavailable")
        self.assertNotIn("secret", response.get_data(as_text=True).lower())
        self.assertNotIn("data", response.json)

        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_counts_for_platform_admin",
            return_value={"total": 1, "active": 1, "inactive": 0},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "get_latest_subscription_overview_for_platform_admin",
            side_effect=RuntimeError("subscription overview scan exceeded bounded row limit"),
        ):
            scan_response = self.client.get("/api/platform-admin/overview", headers=self.headers)
        self.assertEqual(scan_response.status_code, 503)
        self.assertEqual(scan_response.json["code"], "platform_admin_data_unavailable")
        self.assertNotIn("data", scan_response.json)
        scan_body = scan_response.get_data(as_text=True).lower()
        self.assertNotIn("subscription overview scan", scan_body)
        self.assertNotIn("bounded row limit", scan_body)

        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_counts_for_platform_admin",
            return_value={"total": 1, "active": 1, "inactive": 0},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "get_latest_subscription_overview_for_platform_admin",
            return_value={
                "by_status": {"active": 1},
                "by_plan": [{"code": "pro", "name": "Pro", "count": 1}],
                "attention_subscriptions": [],
            },
        ), patch.object(
            platform_admin_service.platform_company_repository,
            "get_companies_by_ids_for_platform_admin", return_value={},
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=RuntimeError("audit down"),
        ):
            audit_response = self.client.get("/api/platform-admin/overview", headers=self.headers)
        self.assertEqual(audit_response.status_code, 503)
        self.assertEqual(audit_response.json["code"], "platform_admin_audit_unavailable")
        self.assertNotIn("data", audit_response.json)

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
