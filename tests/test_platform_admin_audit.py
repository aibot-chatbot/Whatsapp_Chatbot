import unittest
import math
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.database import platform_admin_repository
from app.services import platform_admin_service


class PlatformAdminAuditTests(unittest.TestCase):
    VALID_EVENTS = (
        (
            "identity",
            2,
            "platform_admin.identity.read",
            "platform_admin",
            "2",
            {
                "outcome": "success",
                "endpoint": "/api/platform-admin/me",
                "http_method": "GET",
            },
        ),
        (
            "company_list",
            2,
            "platform_admin.company.list",
            "company",
            None,
            {
                "outcome": "success",
                "endpoint": "/api/platform-admin/companies",
                "http_method": "GET",
                "limit": 25,
                "offset": 0,
                "sort_by": "created_at",
                "sort_order": "desc",
                "search_applied": False,
                "status_filter": None,
                "returned_count": 0,
            },
        ),
        (
            "company_detail_success",
            2,
            "platform_admin.company.read",
            "company",
            "9",
            {
                "outcome": "success",
                "endpoint": "/api/platform-admin/companies/<company_id>",
                "http_method": "GET",
            },
        ),
        (
            "company_detail_not_found",
            2,
            "platform_admin.company.read",
            "company",
            "9",
            {
                "outcome": "not_found",
                "endpoint": "/api/platform-admin/companies/<company_id>",
                "http_method": "GET",
            },
        ),
        (
            "subscription_success",
            2,
            "platform_admin.company.subscription.read",
            "company_subscription",
            "9",
            {
                "outcome": "success",
                "endpoint": "/api/platform-admin/companies/<company_id>/subscription",
                "http_method": "GET",
            },
        ),
        (
            "subscription_not_found",
            2,
            "platform_admin.company.subscription.read",
            "company_subscription",
            "9",
            {
                "outcome": "not_found",
                "endpoint": "/api/platform-admin/companies/<company_id>/subscription",
                "http_method": "GET",
            },
        ),
        (
            "ai_credit_usage_success_without_available_period",
            2,
            "platform_admin.company.ai_credit_usage.read",
            "company_ai_credit_usage",
            "9",
            {
                "outcome": "success",
                "endpoint": "/api/platform-admin/companies/<company_id>/ai-credit-usage",
                "http_method": "GET",
                "period_start": None,
                "period_end": None,
            },
        ),
        (
            "ai_credit_usage_success_with_available_period",
            2,
            "platform_admin.company.ai_credit_usage.read",
            "company_ai_credit_usage",
            "9",
            {
                "outcome": "success",
                "endpoint": "/api/platform-admin/companies/<company_id>/ai-credit-usage",
                "http_method": "GET",
                "period_start": "2026-07-01T00:00:00+00:00",
                "period_end": "2026-08-01T00:00:00+00:00",
            },
        ),
        (
            "ai_credit_usage_not_found",
            2,
            "platform_admin.company.ai_credit_usage.read",
            "company_ai_credit_usage",
            "9",
            {
                "outcome": "not_found",
                "endpoint": "/api/platform-admin/companies/<company_id>/ai-credit-usage",
                "http_method": "GET",
            },
        ),
    )

    def test_valid_event_is_inserted(self):
        query = MagicMock()
        query.insert.return_value = query
        query.execute.return_value = SimpleNamespace(data=[{"id": 1}])
        with patch.object(platform_admin_repository.supabase, "table", return_value=query):
            event = platform_admin_repository.insert_platform_admin_audit_event(
                2, "platform_admin.company.read", "company", "9",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>",
                    "http_method": "GET",
                },
            )
        self.assertEqual(event["id"], 1)

    def test_all_current_action_resource_and_metadata_shapes_are_valid(self):
        for name, *event in self.VALID_EVENTS:
            with self.subTest(name=name):
                platform_admin_repository.validate_audit_event(*event)

    def test_metadata_must_be_object_allowlisted_and_free_of_prohibited_keys(self):
        base = (
            2, "platform_admin.company.read", "company", "9",
        )
        for invalid in (
            None,
            [],
            {
                "outcome": "success",
                "endpoint": "/api/platform-admin/companies/<company_id>",
                "http_method": "GET",
                "unknown": True,
            },
            {
                "outcome": "success",
                "endpoint": "/api/platform-admin/companies/<company_id>",
                "http_method": "GET",
                "message": "secret",
            },
            {
                "outcome": "success",
                "endpoint": "/api/platform-admin/companies/<company_id>",
                "http_method": "GET",
                "period_start": {"nested": {"access_token": "secret"}},
            },
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                platform_admin_repository.validate_audit_event(*base, invalid)

    def test_non_finite_json_values_are_rejected(self):
        base = (2, "platform_admin.company.list", "company", None)
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                platform_admin_repository.validate_audit_event(
                    *base, {
                        "outcome": "success",
                        "endpoint": "/api/platform-admin/companies",
                        "http_method": "GET",
                        "limit": value,
                        "offset": 0,
                        "sort_by": "created_at",
                        "sort_order": "desc",
                        "search_applied": False,
                        "status_filter": None,
                        "returned_count": 0,
                    }
                )

    def test_blank_and_oversized_resource_ids_are_rejected(self):
        base = (2, "platform_admin.company.read", "company")
        for resource_id in ("", "   ", "x" * 256):
            with self.subTest(resource_id=resource_id), self.assertRaises(ValueError):
                platform_admin_repository.validate_audit_event(
                    *base, resource_id, {
                        "outcome": "success",
                        "endpoint": "/api/platform-admin/companies/<company_id>",
                        "http_method": "GET",
                    }
                )

    def test_actor_action_resource_and_size_are_validated(self):
        for actor_id in (True, 0, -1, "2", None):
            with self.subTest(actor_id=actor_id), self.assertRaises(ValueError):
                platform_admin_repository.validate_audit_event(
                    actor_id, "platform_admin.company.read", "company", "1",
                    {
                        "outcome": "success",
                        "endpoint": "/api/platform-admin/companies/<company_id>",
                        "http_method": "GET",
                    }
                )
        with self.assertRaises(ValueError):
            platform_admin_repository.validate_audit_event(
                1, "", "company", "1",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>",
                    "http_method": "GET",
                }
            )
        with self.assertRaises(ValueError):
            platform_admin_repository.validate_audit_event(
                1, "platform_admin.company.read", "", "1",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>",
                    "http_method": "GET",
                }
            )
        with patch.object(platform_admin_repository, "MAX_AUDIT_METADATA_BYTES", 10):
            with self.assertRaises(ValueError):
                platform_admin_repository.validate_audit_event(
                    1, "platform_admin.company.read", "company", "1",
                    {
                        "outcome": "success",
                        "endpoint": "/api/platform-admin/companies/<company_id>",
                        "http_method": "GET",
                    },
                )

    def test_action_resource_pairs_are_exact(self):
        invalid_pairs = (
            ("platform_admin.identity.read", "company", "1"),
            ("platform_admin.company.list", "company_subscription", None),
            ("platform_admin.company.subscription.read", "company", "1"),
            ("platform_admin.company.ai_credit_usage.read", "company_subscription", "1"),
        )
        for action, resource_type, resource_id in invalid_pairs:
            with self.subTest(action=action, resource_type=resource_type), self.assertRaises(ValueError):
                schema = platform_admin_repository.AUDIT_EVENT_SCHEMAS[action]
                metadata = {
                    "outcome": "success",
                    "endpoint": schema["endpoint"],
                    "http_method": "GET",
                }
                if action == "platform_admin.company.list":
                    metadata.update({
                        "limit": 25,
                        "offset": 0,
                        "sort_by": "created_at",
                        "sort_order": "desc",
                        "search_applied": False,
                        "status_filter": None,
                        "returned_count": 0,
                    })
                if action == "platform_admin.company.ai_credit_usage.read":
                    metadata.update({"period_start": None, "period_end": None})
                platform_admin_repository.validate_audit_event(
                    1, action, resource_type, resource_id, metadata
                )

    def test_unknown_action_and_resource_type_are_rejected(self):
        with self.assertRaises(ValueError):
            platform_admin_repository.validate_audit_event(
                1, "platform_admin.company.export", "company", "1", {}
            )
        with self.assertRaises(ValueError):
            platform_admin_repository.validate_audit_event(
                1, "platform_admin.company.read", "tenant", "1",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>",
                    "http_method": "GET",
                },
            )

    def test_missing_required_metadata_and_wrong_value_types_are_rejected(self):
        invalid_cases = (
            (
                "missing_endpoint",
                "platform_admin.company.read",
                "company",
                "1",
                {"outcome": "success", "http_method": "GET"},
            ),
            (
                "wrong_method",
                "platform_admin.company.read",
                "company",
                "1",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>",
                    "http_method": "POST",
                },
            ),
            (
                "wrong_outcome",
                "platform_admin.company.list",
                "company",
                None,
                {
                    "outcome": "not_found",
                    "endpoint": "/api/platform-admin/companies",
                    "http_method": "GET",
                    "limit": 25,
                    "offset": 0,
                    "sort_by": "created_at",
                    "sort_order": "desc",
                    "search_applied": False,
                    "status_filter": None,
                    "returned_count": 0,
                },
            ),
            (
                "missing_period_on_success",
                "platform_admin.company.ai_credit_usage.read",
                "company_ai_credit_usage",
                "1",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>/ai-credit-usage",
                    "http_method": "GET",
                },
            ),
            (
                "period_on_not_found",
                "platform_admin.company.ai_credit_usage.read",
                "company_ai_credit_usage",
                "1",
                {
                    "outcome": "not_found",
                    "endpoint": "/api/platform-admin/companies/<company_id>/ai-credit-usage",
                    "http_method": "GET",
                    "period_start": None,
                    "period_end": None,
                },
            ),
            (
                "start_string_end_none",
                "platform_admin.company.ai_credit_usage.read",
                "company_ai_credit_usage",
                "1",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>/ai-credit-usage",
                    "http_method": "GET",
                    "period_start": "2026-07-01T00:00:00+00:00",
                    "period_end": None,
                },
            ),
            (
                "start_none_end_string",
                "platform_admin.company.ai_credit_usage.read",
                "company_ai_credit_usage",
                "1",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>/ai-credit-usage",
                    "http_method": "GET",
                    "period_start": None,
                    "period_end": "2026-08-01T00:00:00+00:00",
                },
            ),
            (
                "malformed_start",
                "platform_admin.company.ai_credit_usage.read",
                "company_ai_credit_usage",
                "1",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>/ai-credit-usage",
                    "http_method": "GET",
                    "period_start": "not-a-date",
                    "period_end": "2026-08-01T00:00:00+00:00",
                },
            ),
            (
                "malformed_end",
                "platform_admin.company.ai_credit_usage.read",
                "company_ai_credit_usage",
                "1",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>/ai-credit-usage",
                    "http_method": "GET",
                    "period_start": "2026-07-01T00:00:00+00:00",
                    "period_end": "not-a-date",
                },
            ),
            (
                "timezone_naive_start",
                "platform_admin.company.ai_credit_usage.read",
                "company_ai_credit_usage",
                "1",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>/ai-credit-usage",
                    "http_method": "GET",
                    "period_start": "2026-07-01T00:00:00",
                    "period_end": "2026-08-01T00:00:00+00:00",
                },
            ),
            (
                "timezone_naive_end",
                "platform_admin.company.ai_credit_usage.read",
                "company_ai_credit_usage",
                "1",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>/ai-credit-usage",
                    "http_method": "GET",
                    "period_start": "2026-07-01T00:00:00+00:00",
                    "period_end": "2026-08-01T00:00:00",
                },
            ),
            (
                "equal_period_bounds",
                "platform_admin.company.ai_credit_usage.read",
                "company_ai_credit_usage",
                "1",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>/ai-credit-usage",
                    "http_method": "GET",
                    "period_start": "2026-07-01T00:00:00+00:00",
                    "period_end": "2026-07-01T00:00:00+00:00",
                },
            ),
            (
                "start_later_than_end",
                "platform_admin.company.ai_credit_usage.read",
                "company_ai_credit_usage",
                "1",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>/ai-credit-usage",
                    "http_method": "GET",
                    "period_start": "2026-08-01T00:00:00+00:00",
                    "period_end": "2026-07-01T00:00:00+00:00",
                },
            ),
            (
                "invalid_status_filter",
                "platform_admin.company.list",
                "company",
                None,
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies",
                    "http_method": "GET",
                    "limit": 25,
                    "offset": 0,
                    "sort_by": "created_at",
                    "sort_order": "desc",
                    "search_applied": False,
                    "status_filter": "pending",
                    "returned_count": 0,
                },
            ),
        )
        for name, action, resource_type, resource_id, metadata in invalid_cases:
            with self.subTest(name=name), self.assertRaises(ValueError):
                platform_admin_repository.validate_audit_event(
                    1, action, resource_type, resource_id, metadata
                )

    def test_boolean_values_are_rejected_where_integers_are_expected(self):
        metadata = {
            "outcome": "success",
            "endpoint": "/api/platform-admin/companies",
            "http_method": "GET",
            "limit": True,
            "offset": 0,
            "sort_by": "created_at",
            "sort_order": "desc",
            "search_applied": False,
            "status_filter": None,
            "returned_count": 0,
        }
        with self.assertRaises(ValueError):
            platform_admin_repository.validate_audit_event(
                1, "platform_admin.company.list", "company", None, metadata
            )

    def test_validation_failure_does_not_insert_audit_event(self):
        with patch.object(platform_admin_repository.supabase, "table") as table:
            with self.assertRaises(ValueError):
                platform_admin_repository.insert_platform_admin_audit_event(
                    1,
                    "platform_admin.company.read",
                    "company_subscription",
                    "1",
                    {
                        "outcome": "success",
                        "endpoint": "/api/platform-admin/companies/<company_id>",
                        "http_method": "GET",
                    },
                )
        table.assert_not_called()

    def test_audit_happens_before_successful_service_return(self):
        calls = []
        with patch.object(
            platform_company_repository := platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            side_effect=lambda company_id: calls.append("read") or {"id": company_id},
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=lambda *args, **kwargs: calls.append("audit") or {"id": 1},
        ):
            result = platform_admin_service.get_company_detail(5, 2)
        calls.append("return")
        self.assertEqual(result["id"], 5)
        self.assertEqual(calls, ["read", "audit", "return"])

    def test_audit_failure_withholds_data(self):
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin", return_value={"id": 5, "secret": "not returned"},
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event", side_effect=RuntimeError("down"),
        ):
            with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                platform_admin_service.get_company_detail(5, 2)
        self.assertEqual(raised.exception.code, "platform_admin_audit_unavailable")

    def test_missing_company_is_audited_before_not_found_is_returned(self):
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
            with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                platform_admin_service.get_company_detail(77, 2)
            calls.append("not_found")
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.code, "company_not_found")
        self.assertEqual(calls, ["read", "audit", "not_found"])
        self.assertEqual(audit.call_args.args[4]["outcome"], "not_found")

    def test_invalid_service_actor_ids_are_rejected_before_tenant_reads(self):
        for actor_id in (True, 0, -1, "2", None):
            with self.subTest(actor_id=actor_id), patch.object(
                platform_admin_service.platform_company_repository,
                "get_company_for_platform_admin",
            ) as company_lookup:
                with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                    platform_admin_service.get_company_detail(5, actor_id)
                self.assertEqual(raised.exception.code, "platform_admin_context_invalid")
                company_lookup.assert_not_called()

    def test_ai_credit_usage_audit_payload_validates_when_no_period_exists(self):
        captured = []

        def validate_and_capture(*args, **kwargs):
            platform_admin_repository.validate_audit_event(*args)
            captured.append(args)
            return {"id": 1}

        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin", return_value={"id": 5},
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
            "insert_platform_admin_audit_event", side_effect=validate_and_capture,
        ):
            platform_admin_service.get_company_ai_credit_usage(5, 2)

        usage.assert_not_called()
        charges.assert_not_called()
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][1], "platform_admin.company.ai_credit_usage.read")
        self.assertEqual(captured[0][4]["period_start"], None)
        self.assertEqual(captured[0][4]["period_end"], None)

    def test_ai_credit_usage_audit_payload_validates_with_ordered_period(self):
        captured = []

        def validate_and_capture(*args, **kwargs):
            platform_admin_repository.validate_audit_event(*args)
            captured.append(args)
            return {"id": 1}

        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin", return_value={"id": 5},
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "get_subscription_summary_for_platform_admin", return_value=None,
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "get_ai_credit_balance_for_platform_admin",
            return_value={
                "period_start": "2026-07-01T00:00:00Z",
                "period_end": "2026-08-01T00:00:00Z",
            },
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "get_ai_usage_summary_for_platform_admin",
            return_value={
                "request_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "provider_cost_micro_usd": 0,
            },
        ), patch.object(
            platform_admin_service.platform_billing_repository,
            "get_ai_credit_charge_summary_for_platform_admin",
            return_value={
                "transaction_count": 0,
                "customer_charge_micro_myr": 0,
                "uncovered_charge_micro_myr": 0,
                "provider_cost_micro_usd": 0,
            },
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event", side_effect=validate_and_capture,
        ):
            platform_admin_service.get_company_ai_credit_usage(5, 2)

        self.assertEqual(len(captured), 1)
        metadata = captured[0][4]
        self.assertEqual(metadata["period_start"], "2026-07-01T00:00:00+00:00")
        self.assertEqual(metadata["period_end"], "2026-08-01T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
