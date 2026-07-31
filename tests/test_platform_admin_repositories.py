import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.database import platform_admin_repository
from app.database import platform_billing_repository
from app.database import platform_chatbot_repository
from app.database import platform_company_repository
from app.database import platform_company_user_repository
from app.database import ai_credit_repository
from app.database import billing_usage_repository
from app.database import company_repository
from app.database import company_subscription_repository
from app.services import platform_admin_service


def fluent_query(data=None, count=None):
    query = MagicMock()
    for method in ("select", "eq", "limit", "order", "range", "or_", "gte", "lt", "is_", "in_"):
        getattr(query, method).return_value = query
    query.execute.return_value = SimpleNamespace(data=data or [], count=count)
    return query


class PlatformAdminRepositoryTests(unittest.TestCase):
    def test_mapping_lookup_filters_user_and_active_with_explicit_projection(self):
        query = fluent_query([{"id": 3, "user_id": 9, "is_active": True}])
        with patch.object(platform_admin_repository.supabase, "table", return_value=query):
            result = platform_admin_repository.get_active_platform_admin_by_user_id(9)
        self.assertEqual(result["id"], 3)
        query.select.assert_called_once_with(platform_admin_repository.PLATFORM_ADMIN_FIELDS)
        query.eq.assert_any_call("user_id", 9)
        query.eq.assert_any_call("is_active", True)

    def test_audit_event_list_uses_safe_projection_filters_count_and_ordering(self):
        rows = [{
            "id": 11,
            "platform_admin_user_id": 3,
            "action": "platform_admin.company.read",
            "resource_type": "company",
            "resource_id": "29",
            "metadata": {"outcome": "success"},
            "created_at": "2026-07-31T00:00:00+00:00",
            "raw_payload": "must not be projected",
        }]
        query = fluent_query(rows, count=9)
        with patch.object(platform_admin_repository.supabase, "table", return_value=query) as table:
            result, count = platform_admin_repository.list_platform_admin_audit_events_for_platform_admin(
                limit=5,
                offset=10,
                action="platform_admin.company.read",
                resource_type="company",
                resource_id="29",
                created_after=platform_admin_service.datetime.fromisoformat("2026-07-01T00:00:00+00:00"),
                created_before=platform_admin_service.datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
            )
        table.assert_called_once_with("platform_admin_audit_events")
        query.select.assert_called_once_with(
            platform_admin_repository.AUDIT_EVENT_FIELDS,
            count="exact",
        )
        self.assertNotIn("*", platform_admin_repository.AUDIT_EVENT_FIELDS)
        query.eq.assert_any_call("action", "platform_admin.company.read")
        query.eq.assert_any_call("resource_type", "company")
        query.eq.assert_any_call("resource_id", "29")
        query.gte.assert_called_once()
        query.lt.assert_called_once()
        query.order.assert_any_call("created_at", desc=True)
        query.order.assert_any_call("id", desc=True)
        query.range.assert_called_once_with(10, 14)
        self.assertEqual((result, count), (rows, 9))

    def test_audit_event_actor_user_filter_uses_mapping_lookup(self):
        mapping_query = fluent_query([{"id": 3}, {"id": 4}])
        audit_query = fluent_query([], count=0)
        with patch.object(
            platform_admin_repository.supabase, "table",
            side_effect=[mapping_query, audit_query],
        ) as table:
            rows, count = platform_admin_repository.list_platform_admin_audit_events_for_platform_admin(
                limit=25, offset=0, actor_user_id=32,
            )
        self.assertEqual(table.call_args_list[0].args[0], "platform_admin_users")
        mapping_query.select.assert_called_once_with("id")
        mapping_query.eq.assert_called_once_with("user_id", 32)
        audit_query.in_.assert_called_once_with("platform_admin_user_id", [3, 4])
        self.assertEqual((rows, count), ([], 0))

    def test_audit_event_actor_user_filter_with_no_mapping_skips_audit_table(self):
        mapping_query = fluent_query([])
        with patch.object(platform_admin_repository.supabase, "table", return_value=mapping_query) as table:
            rows, count = platform_admin_repository.list_platform_admin_audit_events_for_platform_admin(
                limit=25, offset=0, actor_user_id=999,
            )
        table.assert_called_once_with("platform_admin_users")
        self.assertEqual((rows, count), ([], 0))

    def test_company_list_uses_count_range_escaped_search_and_stable_order(self):
        query = fluent_query([{"id": 2}], count=3)
        with patch.object(platform_company_repository.supabase, "table", return_value=query):
            rows, count = platform_company_repository.list_companies_for_platform_admin(
                limit=10, offset=5, search='a*%,._"', status="active",
                sort_by="created_at", sort_order="desc",
            )
        query.select.assert_called_once_with(platform_company_repository.LIST_FIELDS, count="exact")
        query.range.assert_called_once_with(5, 14)
        self.assertEqual(query.order.call_args_list[1].args[0], "id")
        expression = query.or_.call_args.args[0]
        self.assertIn(r"\%", expression)
        self.assertIn(r"\_", expression)
        self.assertIn(r"\*", expression)
        self.assertEqual((rows, count), ([{"id": 2}], 3))

    def test_company_counts_use_exact_count_status_filters(self):
        total = fluent_query(count=3)
        active = fluent_query(count=2)
        inactive = fluent_query(count=1)
        with patch.object(platform_company_repository.supabase, "table", side_effect=[total, active, inactive]):
            result = platform_company_repository.get_company_counts_for_platform_admin()
        self.assertEqual(result, {"total": 3, "active": 2, "inactive": 1})
        total.eq.assert_not_called()
        active.eq.assert_called_once_with("status", "active")
        inactive.eq.assert_called_once_with("status", "inactive")
        for query in (total, active, inactive):
            query.select.assert_called_once_with(platform_company_repository.COUNT_FIELDS, count="exact")
            query.limit.assert_called_once_with(1)

    def test_detail_uses_requested_company_id(self):
        query = fluent_query([{"id": 88}])
        with patch.object(platform_company_repository.supabase, "table", return_value=query):
            platform_company_repository.get_company_for_platform_admin(88)
        query.eq.assert_called_once_with("id", 88)

    def test_usage_and_charges_keep_integer_micro_values(self):
        usage_query = fluent_query([
            {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5, "provider_cost_micro_usd": 11},
            {"prompt_tokens": None, "completion_tokens": 1, "total_tokens": 1, "provider_cost_micro_usd": 7},
        ])
        charge_query = fluent_query([
            {"customer_charge_micro_myr": 9, "uncovered_charge_micro_myr": 2, "provider_cost_micro_usd": 4}
        ])
        with patch.object(platform_billing_repository.supabase, "table", side_effect=[usage_query, charge_query]):
            usage = platform_billing_repository.get_ai_usage_summary_for_platform_admin(4, "s", "e")
            charges = platform_billing_repository.get_ai_credit_charge_summary_for_platform_admin(4, "s", "e")
        self.assertEqual(usage["total_tokens"], 6)
        self.assertEqual(usage["provider_cost_micro_usd"], 18)
        self.assertEqual(charges["customer_charge_micro_myr"], 9)
        usage_query.eq.assert_any_call("company_id", 4)
        usage_query.eq.assert_any_call("request_status", "completed")

    def test_latest_subscription_overview_uses_latest_row_per_company_and_stable_order(self):
        subscriptions = fluent_query([
            {
                "id": 12, "company_id": 1, "plan_id": 4, "status": "past_due",
                "status_updated_at": "2026-07-29T12:00:00+00:00",
                "current_period_end": "2026-07-28T00:00:00+00:00",
                "created_at": "2026-07-29T00:00:00+00:00",
            },
            {
                "id": 11, "company_id": 1, "plan_id": 2, "status": "active",
                "created_at": "2026-07-28T00:00:00+00:00",
            },
            {
                "id": 21, "company_id": 2, "plan_id": 3, "status": "expired",
                "status_updated_at": "2026-07-29T11:00:00+00:00",
                "created_at": "2026-07-29T00:00:00+00:00",
            },
            {
                "id": 22, "company_id": 3, "plan_id": 99, "status": "trialing",
                "created_at": "2026-07-29T00:00:00+00:00",
            },
        ])
        plans = fluent_query([
            {"id": 4, "code": "pro", "name": "Pro"},
            {"id": 3, "code": "advanced", "name": "Advanced"},
            {"id": 99, "code": "custom", "name": "Custom"},
        ])
        with patch.object(platform_billing_repository.supabase, "table", side_effect=[subscriptions, plans]):
            result = platform_billing_repository.get_latest_subscription_overview_for_platform_admin()
        self.assertEqual(result["by_status"], {
            "trialing": 1, "active": 0, "past_due": 1, "expired": 1, "cancelled": 0,
        })
        self.assertEqual(result["by_plan"], [
            {"code": "advanced", "name": "Advanced", "count": 1},
            {"code": "pro", "name": "Pro", "count": 1},
            {"code": "custom", "name": "Custom", "count": 1},
        ])
        self.assertEqual([row["company_id"] for row in result["attention_subscriptions"]], [1, 2])
        subscriptions.select.assert_called_once_with(platform_billing_repository.OVERVIEW_SUBSCRIPTION_FIELDS)
        subscriptions.order.assert_any_call("created_at", desc=True)
        subscriptions.order.assert_any_call("id", desc=True)
        plans.select.assert_called_once_with(platform_billing_repository.OVERVIEW_PLAN_FIELDS)
        plans.eq.assert_not_called()

    def test_latest_subscription_overview_includes_retired_referenced_plan(self):
        subscriptions = fluent_query([
            {
                "id": 44,
                "company_id": 7,
                "plan_id": 91,
                "status": "expired",
                "status_updated_at": "2026-07-29T12:00:00+00:00",
                "current_period_end": "2026-07-28T00:00:00+00:00",
                "created_at": "2026-07-29T00:00:00+00:00",
            },
            {
                "id": 43,
                "company_id": 7,
                "plan_id": 2,
                "status": "active",
                "created_at": "2026-07-28T00:00:00+00:00",
            },
        ])
        plans = fluent_query([{"id": 91, "code": "legacy", "name": "Legacy"}])
        with patch.object(platform_billing_repository.supabase, "table", side_effect=[subscriptions, plans]):
            result = platform_billing_repository.get_latest_subscription_overview_for_platform_admin()
        self.assertEqual(result["by_status"]["expired"], 1)
        self.assertEqual(result["by_status"]["active"], 0)
        self.assertEqual(result["by_plan"], [{"code": "legacy", "name": "Legacy", "count": 1}])
        self.assertEqual(result["attention_subscriptions"][0]["plan_code"], "legacy")
        self.assertEqual(result["attention_subscriptions"][0]["plan_name"], "Legacy")
        plans.select.assert_called_once_with(platform_billing_repository.OVERVIEW_PLAN_FIELDS)
        plans.in_.assert_called_once_with("id", [91])
        plans.eq.assert_not_called()

    def test_subscription_history_uses_exact_projection_count_scope_and_ordering(self):
        subscriptions = fluent_query([
            {
                "id": 8,
                "plan_id": 3,
                "pending_plan_id": 4,
                "status": "past_due",
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
                "created_at": "2026-07-02T00:00:00+00:00",
                "updated_at": "2026-07-02T00:00:00+00:00",
                "company_id": 2,
                "price": 9900,
            }
        ], count=7)
        plans = fluent_query([
            {"id": 3, "code": "pro", "name": "Pro", "price": 9900, "is_active": False},
            {"id": 4, "code": "advanced", "name": "Advanced", "price": 5900},
        ])
        with patch.object(platform_billing_repository.supabase, "table", side_effect=[subscriptions, plans]) as table:
            rows, count = platform_billing_repository.list_subscription_history_for_platform_admin(
                company_id=2, limit=1, offset=3, status="past_due",
            )
        self.assertEqual(table.call_args_list[0].args[0], "company_subscriptions")
        self.assertEqual(table.call_args_list[1].args[0], "subscription_plans")
        subscriptions.select.assert_called_once_with(
            platform_billing_repository.SUBSCRIPTION_HISTORY_FIELDS,
            count="exact",
        )
        self.assertNotIn("company_id", platform_billing_repository.SUBSCRIPTION_HISTORY_FIELDS)
        self.assertNotIn("price", platform_billing_repository.SUBSCRIPTION_HISTORY_FIELDS)
        subscriptions.eq.assert_any_call("company_id", 2)
        subscriptions.eq.assert_any_call("status", "past_due")
        subscriptions.order.assert_any_call("created_at", desc=True)
        subscriptions.order.assert_any_call("id", desc=True)
        subscriptions.range.assert_called_once_with(3, 3)
        plans.select.assert_called_once_with(platform_billing_repository.SUBSCRIPTION_HISTORY_PLAN_FIELDS)
        plans.in_.assert_called_once_with("id", [3, 4])
        plans.eq.assert_not_called()
        self.assertEqual(count, 7)
        self.assertEqual(rows, [{
            "id": 8,
            "status": "past_due",
            "plan": {"code": "pro", "name": "Pro"},
            "pending_plan": {"code": "advanced", "name": "Advanced"},
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
            "created_at": "2026-07-02T00:00:00+00:00",
            "updated_at": "2026-07-02T00:00:00+00:00",
        }])

    def test_subscription_history_batches_current_and_pending_plan_lookup_once(self):
        subscriptions = fluent_query([
            {"id": 3, "plan_id": 9, "pending_plan_id": 10},
            {"id": 2, "plan_id": 9, "pending_plan_id": None},
            {"id": 1, "plan_id": True, "pending_plan_id": -1},
        ], count=3)
        plans = fluent_query([
            {"id": 9, "code": "legacy", "name": "Legacy"},
            {"id": 10, "code": "next", "name": "Next"},
        ])
        with patch.object(platform_billing_repository.supabase, "table", side_effect=[subscriptions, plans]) as table:
            rows, count = platform_billing_repository.list_subscription_history_for_platform_admin(
                company_id=2, limit=25, offset=0,
            )
        self.assertEqual(count, 3)
        self.assertEqual(table.call_count, 2)
        plans.in_.assert_called_once_with("id", [9, 10])
        self.assertEqual(rows[0]["plan"], {"code": "legacy", "name": "Legacy"})
        self.assertEqual(rows[0]["pending_plan"], {"code": "next", "name": "Next"})

    def test_subscription_history_without_plan_ids_does_not_query_plans(self):
        subscriptions = fluent_query([{"id": 1, "plan_id": None, "pending_plan_id": None}], count=1)
        with patch.object(platform_billing_repository.supabase, "table", return_value=subscriptions) as table:
            rows, count = platform_billing_repository.list_subscription_history_for_platform_admin(
                company_id=2, limit=25, offset=0,
            )
        self.assertEqual(table.call_count, 1)
        self.assertEqual(count, 1)
        self.assertIsNone(rows[0]["plan"])
        self.assertIsNone(rows[0]["pending_plan"])

    def test_subscription_history_rejects_invalid_repository_arguments(self):
        for kwargs in (
            {"company_id": 0, "limit": 25, "offset": 0},
            {"company_id": 2, "limit": 0, "offset": 0},
            {"company_id": 2, "limit": True, "offset": 0},
            {"company_id": 2, "limit": 25, "offset": -1},
            {"company_id": 2, "limit": 25, "offset": True},
            {"company_id": 2, "limit": 25, "offset": 0, "status": "paused"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                platform_billing_repository.list_subscription_history_for_platform_admin(**kwargs)

    def test_ai_credit_transactions_use_exact_projection_count_scope_and_ordering(self):
        rows = [{
            "id": 9,
            "transaction_type": "usage_debit",
            "included_delta_micro_myr": -5,
            "topup_delta_micro_myr": 0,
            "included_balance_after_micro_myr": 95,
            "topup_balance_after_micro_myr": 20,
            "customer_charge_micro_myr": None,
            "uncovered_charge_micro_myr": 0,
            "period_start": None,
            "period_end": None,
            "created_at": "2026-07-29T00:00:00+00:00",
            "company_id": 2,
            "provider_cost_micro_usd": 7,
            "fx_rate_micro_myr_per_usd": 8,
            "markup_basis_points": 9,
            "description": "secret",
            "payment_reference": "payment",
            "idempotency_key": "idem",
            "ai_usage_log_id": 10,
            "subscription_id": 11,
            "reversal_of_transaction_id": 12,
        }]
        query = fluent_query(rows, count=6)
        with patch.object(platform_billing_repository.supabase, "table", return_value=query) as table:
            transactions, count = platform_billing_repository.list_ai_credit_transactions_for_platform_admin(
                company_id=2, limit=1, offset=3, transaction_type="usage_debit",
            )
        table.assert_called_once_with("ai_credit_transactions")
        query.select.assert_called_once_with(
            platform_billing_repository.AI_CREDIT_TRANSACTION_HISTORY_FIELDS,
            count="exact",
        )
        self.assertNotIn("*", platform_billing_repository.AI_CREDIT_TRANSACTION_HISTORY_FIELDS)
        for prohibited in (
            "company_id", "provider_cost_micro_usd", "fx_rate_micro_myr_per_usd",
            "markup_basis_points", "description", "payment_reference",
            "idempotency_key", "ai_usage_log_id", "subscription_id",
            "reversal_of_transaction_id",
        ):
            self.assertNotIn(prohibited, platform_billing_repository.AI_CREDIT_TRANSACTION_HISTORY_FIELDS)
            self.assertNotIn(prohibited, transactions[0])
        query.eq.assert_any_call("company_id", 2)
        query.eq.assert_any_call("transaction_type", "usage_debit")
        query.order.assert_any_call("created_at", desc=True)
        query.order.assert_any_call("id", desc=True)
        query.range.assert_called_once_with(3, 3)
        self.assertEqual(count, 6)
        self.assertEqual(transactions, [{
            "id": 9,
            "transaction_type": "usage_debit",
            "included_delta_micro_myr": -5,
            "topup_delta_micro_myr": 0,
            "included_balance_after_micro_myr": 95,
            "topup_balance_after_micro_myr": 20,
            "customer_charge_micro_myr": None,
            "uncovered_charge_micro_myr": 0,
            "period_start": None,
            "period_end": None,
            "created_at": "2026-07-29T00:00:00+00:00",
        }])

    def test_ai_credit_transactions_accept_all_checked_transaction_types_and_reject_invalid_args(self):
        allowed = sorted(platform_billing_repository.AI_CREDIT_TRANSACTION_TYPES)
        for transaction_type in allowed:
            with self.subTest(transaction_type=transaction_type):
                query = fluent_query([], count=0)
                with patch.object(platform_billing_repository.supabase, "table", return_value=query):
                    rows, count = platform_billing_repository.list_ai_credit_transactions_for_platform_admin(
                        company_id=2, limit=25, offset=0, transaction_type=transaction_type,
                    )
                self.assertEqual((rows, count), ([], 0))
                query.eq.assert_any_call("transaction_type", transaction_type)

        for kwargs in (
            {"company_id": 0, "limit": 25, "offset": 0},
            {"company_id": 2, "limit": 0, "offset": 0},
            {"company_id": 2, "limit": True, "offset": 0},
            {"company_id": 2, "limit": 25, "offset": -1},
            {"company_id": 2, "limit": 25, "offset": True},
            {"company_id": 2, "limit": 25, "offset": 0, "transaction_type": "provider_cost"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                platform_billing_repository.list_ai_credit_transactions_for_platform_admin(**kwargs)

    def test_latest_subscription_overview_scan_bound_raises_instead_of_partial_counts(self):
        first_page = fluent_query([
            {"id": 4, "company_id": 4, "plan_id": 2, "status": "active", "created_at": "2026-07-29T00:00:00+00:00"},
            {"id": 3, "company_id": 3, "plan_id": 2, "status": "active", "created_at": "2026-07-28T00:00:00+00:00"},
        ])
        second_page = fluent_query([
            {"id": 2, "company_id": 2, "plan_id": 2, "status": "active", "created_at": "2026-07-27T00:00:00+00:00"},
            {"id": 1, "company_id": 1, "plan_id": 2, "status": "active", "created_at": "2026-07-26T00:00:00+00:00"},
        ])
        with patch.object(platform_billing_repository, "SUBSCRIPTION_SCAN_PAGE_SIZE", 2), patch.object(
            platform_billing_repository, "SUBSCRIPTION_SCAN_MAX_ROWS", 3
        ), patch.object(
            platform_billing_repository.supabase, "table", side_effect=[first_page, second_page]
        ) as table:
            with self.assertRaises(RuntimeError):
                platform_billing_repository.get_latest_subscription_overview_for_platform_admin()
        self.assertEqual(table.call_args_list[0].args[0], "company_subscriptions")
        self.assertEqual(table.call_args_list[1].args[0], "company_subscriptions")
        first_page.range.assert_called_once_with(0, 1)
        second_page.range.assert_called_once_with(2, 3)

    def test_latest_subscription_created_at_tie_breaks_by_id_desc(self):
        subscriptions = fluent_query([
            {"id": 6, "company_id": 4, "plan_id": 2, "status": "expired", "created_at": "2026-07-29T00:00:00+00:00"},
            {"id": 5, "company_id": 4, "plan_id": 3, "status": "active", "created_at": "2026-07-29T00:00:00+00:00"},
        ])
        plans = fluent_query([{"id": 2, "code": "essential", "name": "Essential"}])
        with patch.object(platform_billing_repository.supabase, "table", side_effect=[subscriptions, plans]):
            result = platform_billing_repository.get_latest_subscription_overview_for_platform_admin()
        self.assertEqual(result["by_status"]["expired"], 1)
        self.assertEqual(result["by_status"]["active"], 0)

    def test_attention_subscription_list_is_limited_to_ten(self):
        rows = [
            {
                "id": idx, "company_id": idx, "plan_id": 2, "status": "past_due",
                "status_updated_at": f"2026-07-{idx:02d}T00:00:00+00:00",
                "created_at": f"2026-07-{idx:02d}T00:00:00+00:00",
            }
            for idx in range(1, 13)
        ]
        rows = list(reversed(rows))
        subscriptions = fluent_query(rows)
        plans = fluent_query([{"id": 2, "code": "essential", "name": "Essential"}])
        with patch.object(platform_billing_repository.supabase, "table", side_effect=[subscriptions, plans]):
            result = platform_billing_repository.get_latest_subscription_overview_for_platform_admin()
        self.assertEqual(len(result["attention_subscriptions"]), 10)
        self.assertEqual(result["attention_subscriptions"][0]["company_id"], 12)
        self.assertEqual(result["attention_subscriptions"][-1]["company_id"], 3)

    def test_platform_repositories_never_select_star(self):
        for module in (
            platform_admin_repository,
            platform_company_repository,
            platform_billing_repository,
            platform_company_user_repository,
            platform_chatbot_repository,
        ):
            source = inspect.getsource(module)
            self.assertNotIn('.select("*")', source)
            self.assertNotIn(".select('*')", source)

    def test_company_user_and_chatbot_list_projections_are_exact_and_safe(self):
        self.assertEqual(
            platform_company_user_repository.LIST_FIELDS,
            "id,full_name,email,role,status,created_at,updated_at",
        )
        for excluded in (
            "password_hash",
            "phone",
            "is_verified",
            "company_id",
            "token",
            "otp",
        ):
            with self.subTest(repository="users", excluded=excluded):
                self.assertNotIn(excluded, platform_company_user_repository.LIST_FIELDS)

        self.assertEqual(
            platform_chatbot_repository.LIST_FIELDS,
            "id,bot_name,is_active,status,language,tone,ai_provider,model_name,created_at,updated_at",
        )
        for excluded in (
            "deleted_at",
            "bot_description",
            "welcome_message",
            "fallback_message",
            "temperature",
            "prompt",
            "credential",
            "webhook",
            "conversation",
            "knowledge",
        ):
            with self.subTest(repository="chatbots", excluded=excluded):
                self.assertNotIn(excluded, platform_chatbot_repository.LIST_FIELDS)

    def test_company_user_list_uses_safe_projection_company_scope_and_search(self):
        query = fluent_query([{"id": 4}], count=1)
        with patch.object(platform_company_user_repository.supabase, "table", return_value=query):
            rows, count = platform_company_user_repository.list_company_users_for_platform_admin(
                company_id=9, limit=25, offset=0, search='User_%',
                sort_by="email", sort_order="asc",
            )
        query.select.assert_called_once_with(platform_company_user_repository.LIST_FIELDS, count="exact")
        query.eq.assert_called_once_with("company_id", 9)
        expression = query.or_.call_args.args[0]
        self.assertIn("email.ilike", expression)
        self.assertIn("full_name.ilike", expression)
        self.assertIn(r"\%", expression)
        self.assertIn(r"\_", expression)
        query.range.assert_called_once_with(0, 24)
        self.assertEqual(query.order.call_args_list[0].args[0], "email")
        self.assertEqual(query.order.call_args_list[1].args[0], "id")
        self.assertEqual((rows, count), ([{"id": 4}], 1))

    def test_company_chatbot_list_uses_safe_projection_and_current_null_semantics(self):
        query = fluent_query([{"id": 29}], count=1)
        with patch.object(platform_chatbot_repository.supabase, "table", return_value=query):
            rows, count = platform_chatbot_repository.list_company_chatbots_for_platform_admin(
                company_id=9, limit=10, offset=5, search="Support",
                state="current", sort_by="created_at", sort_order="desc",
            )
        query.select.assert_called_once_with(platform_chatbot_repository.LIST_FIELDS, count="exact")
        query.eq.assert_called_once_with("company_id", 9)
        query.is_.assert_called_once_with("deleted_at", "null")
        query.or_.assert_any_call("bot_name.ilike.\"*Support*\"")
        query.or_.assert_any_call("status.is.null,status.neq.archived")
        query.range.assert_called_once_with(5, 14)
        self.assertEqual(query.order.call_args_list[1].args[0], "id")
        self.assertEqual((rows, count), ([{"id": 29}], 1))

    def test_company_chatbot_archived_and_all_state_filters(self):
        archived_query = fluent_query([], count=0)
        all_query = fluent_query([], count=0)
        with patch.object(
            platform_chatbot_repository.supabase, "table",
            side_effect=[archived_query, all_query],
        ):
            platform_chatbot_repository.list_company_chatbots_for_platform_admin(
                company_id=9, limit=25, offset=0, state="archived"
            )
            platform_chatbot_repository.list_company_chatbots_for_platform_admin(
                company_id=9, limit=25, offset=0, state="all"
            )
        archived_query.eq.assert_any_call("status", "archived")
        all_eq_calls = [call.args for call in all_query.eq.call_args_list]
        self.assertEqual(all_eq_calls, [("company_id", 9)])
        all_query.is_.assert_not_called()

    def test_repository_errors_propagate(self):
        query = fluent_query()
        query.execute.side_effect = RuntimeError("db down")
        with patch.object(platform_company_repository.supabase, "table", return_value=query):
            with self.assertRaises(RuntimeError):
                platform_company_repository.get_company_for_platform_admin(1)

    def test_missing_balance_does_not_initialize_credit_or_call_rpc(self):
        query = fluent_query([])
        with patch.object(
            platform_billing_repository.supabase, "table", return_value=query
        ), patch.object(platform_billing_repository.supabase, "rpc") as rpc:
            result = platform_billing_repository.get_ai_credit_balance_for_platform_admin(4)
        self.assertIsNone(result)
        rpc.assert_not_called()
        query.insert.assert_not_called()
        query.update.assert_not_called()

    def test_platform_read_path_has_no_credit_initialization_call(self):
        source = inspect.getsource(platform_billing_repository) + inspect.getsource(
            platform_admin_service
        )
        self.assertNotIn("ensure_company_ai_credit", source)
        self.assertNotIn(".rpc(", source)

    def test_tenant_repositories_expose_no_platform_bypass_mode(self):
        forbidden_fragments = ("bypass", "unscoped", "platform_mode", "platform_admin")
        tenant_modules = (
            company_repository,
            company_subscription_repository,
            ai_credit_repository,
            billing_usage_repository,
        )
        for module in tenant_modules:
            for name, function in inspect.getmembers(module, inspect.isfunction):
                if function.__module__ != module.__name__:
                    continue
                parameter_names = inspect.signature(function).parameters
                for parameter_name in parameter_names:
                    with self.subTest(module=module.__name__, function=name, parameter=parameter_name):
                        self.assertFalse(
                            any(fragment in parameter_name for fragment in forbidden_fragments)
                        )


if __name__ == "__main__":
    unittest.main()
