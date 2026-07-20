import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.database import platform_admin_repository
from app.database import platform_billing_repository
from app.database import platform_company_repository
from app.database import ai_credit_repository
from app.database import billing_usage_repository
from app.database import company_repository
from app.database import company_subscription_repository
from app.services import platform_admin_service


def fluent_query(data=None, count=None):
    query = MagicMock()
    for method in ("select", "eq", "limit", "order", "range", "or_", "gte", "lt"):
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

    def test_platform_repositories_never_select_star(self):
        for module in (
            platform_admin_repository,
            platform_company_repository,
            platform_billing_repository,
        ):
            source = inspect.getsource(module)
            self.assertNotIn('.select("*")', source)
            self.assertNotIn(".select('*')", source)

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
