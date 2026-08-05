import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "data" / "030_create_tenant_support_requests.sql"


class TenantSupportRequestsMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.normalized = re.sub(r"\s+", " ", cls.sql).lower()

    def test_creates_three_tenant_support_tables(self):
        for table in (
            "tenant_support_requests",
            "tenant_support_request_events",
            "tenant_support_audit_events",
        ):
            with self.subTest(table=table):
                self.assertIn(f"create table if not exists public.{table}", self.normalized)

    def test_requester_fk_and_tenant_source_are_defined(self):
        self.assertIn("requester_user_id bigint not null references public.users(id)", self.normalized)
        self.assertIn("source text not null default 'tenant'", self.normalized)
        self.assertIn("check (source = 'tenant')", self.normalized)
        self.assertNotIn("created_by_platform_admin_user_id bigint not null", self.normalized)

    def test_actor_exclusivity_checks_are_defined(self):
        self.assertIn("actor_user_id bigint null references public.users(id)", self.normalized)
        self.assertIn(
            "actor_platform_admin_user_id bigint null references public.platform_admin_users(id)",
            self.normalized,
        )
        self.assertIn("actor_type in ('tenant', 'platform_admin', 'system')", self.normalized)
        self.assertIn("actor_type = 'tenant'", self.normalized)
        self.assertIn("actor_type = 'platform_admin'", self.normalized)
        self.assertIn("actor_type = 'system'", self.normalized)

    def test_append_only_triggers_and_invoker_functions_exist(self):
        for name in (
            "tenant_support_request_events_reject_mutation",
            "tenant_support_audit_events_reject_mutation",
        ):
            with self.subTest(trigger=name):
                self.assertIn(f"create trigger {name}", self.normalized)
                self.assertIn("before update or delete", self.normalized)
        self.assertIn("security invoker", self.normalized)
        self.assertIn("set search_path to pg_catalog", self.normalized)

    def test_atomic_tenant_support_request_function_is_backend_only(self):
        self.assertIn(
            "create or replace function public.create_tenant_support_request(",
            self.normalized,
        )
        self.assertIn("returns bigint", self.normalized)
        self.assertIn("security invoker", self.normalized)
        self.assertIn("set search_path to pg_catalog", self.normalized)
        self.assertIn("insert into public.tenant_support_requests", self.normalized)
        self.assertIn("insert into public.tenant_support_request_events", self.normalized)
        self.assertIn("insert into public.tenant_support_audit_events", self.normalized)
        self.assertIn("'tenant'", self.normalized)
        self.assertIn("'new'", self.normalized)
        self.assertIn("'normal'", self.normalized)
        self.assertIn("if p_title is null", self.normalized)
        self.assertIn("if p_redacted_description is null", self.normalized)
        self.assertIn("'created'", self.normalized)
        self.assertIn("actor_user_id", self.normalized)
        self.assertIn("actor_platform_admin_user_id", self.normalized)
        self.assertIn("'tenant_support.request.create'", self.normalized)
        self.assertIn(
            "revoke all on function public.create_tenant_support_request(",
            self.normalized,
        )
        self.assertIn(
            ") from public, anon, authenticated",
            self.normalized,
        )
        self.assertIn(") to service_role", self.normalized)

    def test_rpc_does_not_mutate_platform_or_customer_tables(self):
        function_body = self.normalized.split(
            "create or replace function public.create_tenant_support_request(", 1
        )[1].split("revoke all on function", 1)[0]
        self.assertNotIn("insert into public.platform_admin_users", function_body)
        self.assertNotIn("update public.platform_admin_users", function_body)
        self.assertNotIn("delete from public.platform_admin_users", function_body)
        self.assertNotIn("insert into public.platform_support_cases", function_body)
        self.assertNotIn("update public.platform_support_cases", function_body)
        self.assertNotIn("delete from public.platform_support_cases", function_body)
        self.assertNotIn("insert into public.platform_support_case_events", function_body)
        self.assertNotIn("update public.platform_support_case_events", function_body)
        self.assertNotIn("delete from public.platform_support_case_events", function_body)
        self.assertNotIn("insert into public.users", function_body)
        self.assertNotIn("update public.users", function_body)
        self.assertNotIn("delete from public.users", function_body)
        self.assertNotIn("insert into public.companies", function_body)
        self.assertNotIn("update public.companies", function_body)
        self.assertNotIn("delete from public.companies", function_body)

    def test_rpc_audit_insert_has_no_title_or_description(self):
        function_body = self.normalized.split(
            "insert into public.tenant_support_audit_events", 1
        )[1].split("return v_request_id", 1)[0]
        self.assertNotIn("title", function_body)
        self.assertNotIn("description", function_body)

    def test_audit_table_has_no_title_or_description_columns(self):
        audit_section = self.normalized.split(
            "create table if not exists public.tenant_support_audit_events", 1
        )[1].split("create index", 1)[0]
        self.assertNotIn("title", audit_section)
        self.assertNotIn("description", audit_section)

    def test_service_role_only_access_is_defined(self):
        for table in (
            "tenant_support_requests",
            "tenant_support_request_events",
            "tenant_support_audit_events",
        ):
            with self.subTest(table=table):
                self.assertIn(f"alter table public.{table} enable row level security", self.normalized)
                self.assertIn(f"from public, anon, authenticated", self.normalized)
        self.assertIn("to service_role", self.normalized)
        self.assertNotIn("to authenticated", self.normalized)
        self.assertNotIn("to anon", self.normalized)

    def test_append_only_tables_have_no_service_role_update_or_delete(self):
        self.assertIn(
            "revoke update, delete on public.tenant_support_request_events from service_role",
            self.normalized,
        )
        self.assertIn(
            "revoke update, delete on public.tenant_support_audit_events from service_role",
            self.normalized,
        )
        self.assertNotIn(
            "grant update on public.tenant_support_request_events to service_role",
            self.normalized,
        )
        self.assertNotIn(
            "grant delete on public.tenant_support_request_events to service_role",
            self.normalized,
        )
        self.assertNotIn(
            "grant update on public.tenant_support_audit_events to service_role",
            self.normalized,
        )
        self.assertNotIn(
            "grant delete on public.tenant_support_audit_events to service_role",
            self.normalized,
        )
        self.assertNotIn(
            "grant delete on public.tenant_support_requests to service_role",
            self.normalized,
        )

    def test_existing_platform_admin_objects_are_not_modified(self):
        self.assertNotIn("insert into public.platform_admin_users", self.normalized)
        self.assertNotIn("update public.platform_admin_users", self.normalized)
        self.assertNotIn("delete from public.platform_admin_users", self.normalized)
        self.assertNotIn("alter table public.platform_support_cases", self.normalized)
        self.assertNotIn("alter table public.platform_support_case_events", self.normalized)
        self.assertNotIn("drop table public.platform_support_cases", self.normalized)
        self.assertNotIn("drop table public.platform_support_case_events", self.normalized)
        self.assertIn("design draft only", self.normalized)


if __name__ == "__main__":
    unittest.main()
