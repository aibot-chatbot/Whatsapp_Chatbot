import re
import unittest
from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "034_platform_admin_user_management.sql"
)


class PlatformAdminUserManagementMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.normalized = "\n".join(
            line for line in cls.sql.splitlines()
            if not line.lstrip().startswith("--")
        ).lower()

    def _function_body(self, signature):
        return self.normalized.split(signature, 1)[1].split("$function$;", 1)[0]

    def test_protected_company_registry_is_database_authoritative_and_unseeded(self):
        self.assertIn(
            "create table if not exists public.platform_admin_protected_companies",
            self.normalized,
        )
        self.assertIn("company_id bigint primary key", self.normalized)
        self.assertIn(
            "references public.companies(id)\n"
            "        on update restrict\n"
            "        on delete restrict",
            self.normalized,
        )
        self.assertIn("created_at timestamptz not null default now()", self.normalized)
        self.assertIn("created_by_user_id bigint null", self.normalized)
        self.assertIn(
            "references public.users(id)\n"
            "        on update restrict\n"
            "        on delete set null",
            self.normalized,
        )
        self.assertNotIn("insert into public.platform_admin_protected_companies", self.normalized)
        self.assertNotIn("company_id = 29", self.normalized)
        self.assertNotIn("values (29", self.normalized)

    def test_registry_access_is_service_role_select_only_with_rls(self):
        self.assertIn(
            "alter table public.platform_admin_protected_companies enable row level security",
            self.normalized,
        )
        self.assertNotIn("force row level security", self.normalized)
        self.assertIn(
            "create policy platform_admin_protected_companies_service_select",
            self.normalized,
        )
        self.assertIn("for select\n    to service_role", self.normalized)
        self.assertNotIn("for insert\n    to service_role", self.normalized)
        self.assertNotIn("for update\n    to service_role", self.normalized)
        self.assertNotIn("for delete\n    to service_role", self.normalized)
        self.assertIn(
            "revoke all on public.platform_admin_protected_companies\n"
            "    from public, anon, authenticated, service_role",
            self.normalized,
        )
        self.assertIn(
            "grant select on public.platform_admin_protected_companies\n"
            "    to service_role",
            self.normalized,
        )
        for forbidden in (
            "grant insert on public.platform_admin_protected_companies",
            "grant update on public.platform_admin_protected_companies",
            "grant delete on public.platform_admin_protected_companies",
            "grant all on public.platform_admin_protected_companies",
        ):
            self.assertNotIn(forbidden, self.normalized)

    def test_registry_is_bootstrap_controlled_by_privileges_not_mutation_trigger(self):
        self.assertIn("created_by_user_id bigint null", self.normalized)
        self.assertIn(
            "references public.users(id)\n"
            "        on update restrict\n"
            "        on delete set null",
            self.normalized,
        )
        for forbidden in (
            "grant insert on public.platform_admin_protected_companies",
            "grant update on public.platform_admin_protected_companies",
            "grant delete on public.platform_admin_protected_companies",
            "create_platform_admin_protected_company",
            "update_platform_admin_protected_company",
            "delete_platform_admin_protected_company",
            "reject_platform_admin_protected_company_mutation",
            "platform_admin_protected_companies_reject_mutation",
            "before update or delete\n    on public.platform_admin_protected_companies",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.normalized)

    def test_create_mapping_rpc_validates_actor_target_and_protected_company(self):
        body = self._function_body(
            "create or replace function public.create_platform_admin_user_mapping("
        )
        self.assertIn("p_actor_platform_admin_user_id bigint", body)
        self.assertIn("p_target_user_id bigint", body)
        self.assertNotIn("p_company_id", body)
        self.assertNotIn("p_role", body)
        self.assertNotIn("p_created_by_user_id", body)
        self.assertNotIn("p_is_active", body)
        self.assertIn("p_actor_platform_admin_user_id is null or p_actor_platform_admin_user_id <= 0", body)
        self.assertIn("p_target_user_id is null or p_target_user_id <= 0", body)
        self.assertIn("perform public.require_active_platform_admin_mapping", body)
        self.assertIn("lock table public.platform_admin_users in share row exclusive mode", body)
        self.assertIn("from public.platform_admin_users", body)
        self.assertIn("for update", body)
        self.assertIn("from public.users", body)
        self.assertIn("where id = p_target_user_id", body)
        self.assertIn("v_target_user.status is distinct from 'active'", body)
        self.assertIn("v_target_user.company_id is null", body)
        self.assertIn("from public.platform_admin_protected_companies", body)
        self.assertIn("where company_id = v_target_user.company_id", body)
        self.assertNotIn("v_target_user.role", body)
        self.assertNotIn(".role", body)

    def test_create_mapping_rejects_duplicates_and_writes_mapping_and_audit_atomically(self):
        body = self._function_body(
            "create or replace function public.create_platform_admin_user_mapping("
        )
        self.assertIn("where user_id = p_target_user_id", body)
        self.assertIn("platform-admin mapping already exists", body)
        self.assertIn("insert into public.platform_admin_users", body)
        self.assertIn("user_id,\n        is_active,\n        created_by_user_id", body)
        self.assertIn("p_target_user_id,\n        true,\n        v_actor.user_id", body)
        self.assertIn("insert into public.platform_admin_audit_events", body)
        self.assertIn("'platform_admin.user.create'", body)
        self.assertIn("'platform_admin_users'", body)
        self.assertIn("v_new_mapping.id::text", body)
        for key in (
            "'endpoint'",
            "'http_method'",
            "'outcome'",
            "'target_platform_admin_user_id'",
            "'target_user_id'",
            "'old_is_active'",
            "'new_is_active'",
        ):
            self.assertIn(key, body)
        for forbidden in ("password", "hash", "token", "'role'", "company_name", "raw request"):
            self.assertNotIn(forbidden, body)
        self.assertNotIn("exception when", body)
        self.assertNotIn("commit", body)

    def test_set_active_rpc_enforces_self_noop_activation_and_final_admin_rules(self):
        body = self._function_body(
            "create or replace function public.set_platform_admin_user_active("
        )
        self.assertIn("p_actor_platform_admin_user_id bigint", body)
        self.assertIn("p_target_platform_admin_user_id bigint", body)
        self.assertIn("p_is_active boolean", body)
        self.assertIn("p_actor_platform_admin_user_id is null or p_actor_platform_admin_user_id <= 0", body)
        self.assertIn("p_target_platform_admin_user_id is null or p_target_platform_admin_user_id <= 0", body)
        self.assertIn("p_is_active is null", body)
        self.assertIn("p_actor_platform_admin_user_id = p_target_platform_admin_user_id", body)
        self.assertIn("p_is_active = false", body)
        self.assertIn("self-deactivation is not allowed", body)
        self.assertIn("lock table public.platform_admin_users in share row exclusive mode", body)
        self.assertIn("perform public.require_active_platform_admin_mapping", body)
        self.assertIn("platform-admin mapping not found", body)
        self.assertIn("v_target.is_active = p_is_active", body)
        self.assertIn("platform-admin mapping active state is unchanged", body)
        self.assertIn("select count(*) into v_active_count", body)
        self.assertIn("where is_active = true", body)
        self.assertIn("v_active_count <= 1", body)
        self.assertIn("at least one active platform-admin mapping is required", body)

    def test_activation_revalidates_user_status_and_protected_company(self):
        body = self._function_body(
            "create or replace function public.set_platform_admin_user_active("
        )
        activation_branch = body.split("if p_is_active = true then", 1)[1].split("else", 1)[0]
        self.assertIn("from public.users", body)
        self.assertIn("where id = v_target.user_id", body)
        self.assertIn("v_target_user.status is distinct from 'active'", activation_branch)
        self.assertIn("v_target_user.company_id is null", activation_branch)
        self.assertIn("from public.platform_admin_protected_companies", activation_branch)
        self.assertIn("where company_id = v_target_user.company_id", activation_branch)
        self.assertNotIn(".role", activation_branch)

    def test_set_active_updates_mapping_and_writes_expected_audit(self):
        body = self._function_body(
            "create or replace function public.set_platform_admin_user_active("
        )
        self.assertIn("update public.platform_admin_users", body)
        self.assertIn("is_active = p_is_active", body)
        self.assertIn("updated_at = v_now", body)
        self.assertIn("'platform_admin.user.activate'", body)
        self.assertIn("'platform_admin.user.deactivate'", body)
        self.assertIn("insert into public.platform_admin_audit_events", body)
        self.assertIn("p_target_platform_admin_user_id::text", body)
        for key in (
            "'endpoint'",
            "'http_method'",
            "'outcome'",
            "'target_platform_admin_user_id'",
            "'target_user_id'",
            "'old_is_active'",
            "'new_is_active'",
        ):
            self.assertIn(key, body)
        self.assertIn("'patch'", body)
        self.assertNotIn("exception when", body)
        self.assertNotIn("commit", body)

    def test_rpc_security_and_execute_grants_are_service_role_only(self):
        for signature in (
            "public.create_platform_admin_user_mapping(\n    p_actor_platform_admin_user_id bigint",
            "public.set_platform_admin_user_active(\n    p_actor_platform_admin_user_id bigint",
        ):
            body = self._function_body("create or replace function " + signature)
            self.assertIn("security invoker", body)
            self.assertIn("set search_path to pg_catalog", body)
            self.assertIn("public.platform_admin_users", body)
            self.assertIn("public.platform_admin_audit_events", body)
        self.assertIn(
            "revoke all on function public.create_platform_admin_user_mapping(bigint, bigint)\n"
            "    from public, anon, authenticated, service_role",
            self.normalized,
        )
        self.assertIn(
            "revoke all on function public.set_platform_admin_user_active(bigint, bigint, boolean)\n"
            "    from public, anon, authenticated, service_role",
            self.normalized,
        )
        self.assertIn(
            "grant execute on function public.create_platform_admin_user_mapping(bigint, bigint)\n"
            "    to service_role",
            self.normalized,
        )
        self.assertIn(
            "grant execute on function public.set_platform_admin_user_active(bigint, bigint, boolean)\n"
            "    to service_role",
            self.normalized,
        )
        self.assertNotIn("grant execute on function public.create_platform_admin_user_mapping(bigint, bigint)\n    to anon", self.normalized)
        self.assertNotIn("grant execute on function public.set_platform_admin_user_active(bigint, bigint, boolean)\n    to authenticated", self.normalized)

    def test_migration_preserves_existing_platform_admin_user_privilege_boundary(self):
        self.assertNotIn("grant delete on public.platform_admin_users", self.normalized)
        self.assertNotIn("grant all on public.platform_admin_users", self.normalized)
        self.assertNotIn("to anon", re.sub(r"revoke all.*?;", "", self.normalized, flags=re.S))
        self.assertNotIn("to authenticated", re.sub(r"revoke all.*?;", "", self.normalized, flags=re.S))
        self.assertNotIn("delete from public.platform_admin_users", self.normalized)
        self.assertNotIn("insert into public.platform_admin_protected_companies", self.normalized)

    def test_no_runtime_registry_mutation_rpc_or_parallel_user_admin_model(self):
        for forbidden in (
            "create_platform_admin_protected_company",
            "update_platform_admin_protected_company",
            "delete_platform_admin_protected_company",
            "invite_platform_admin_user",
            "bootstrap_platform_admin_user",
            "create table if not exists public.platform_admin_invitations",
            "create table if not exists public.platform_admin_roles",
            "alter table public.users add column platform_admin",
            "alter table public.users add column is_platform_admin",
        ):
            self.assertNotIn(forbidden, self.normalized)


if __name__ == "__main__":
    unittest.main()
