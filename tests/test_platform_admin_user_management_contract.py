import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "PLATFORM_ADMIN_USER_MANAGEMENT_CONTRACT.md"
AUDIT_POLICY = ROOT / "docs" / "PLATFORM_ADMIN_AUDIT_POLICY.md"
TMP = ROOT / "tmp"
RPC_VERIFICATION_SQL = ROOT / "tmp" / "platform_admin_user_management_034_rpc_verification.sql"
MIGRATION_023 = ROOT / "data" / "023_create_platform_admin_users.sql"
MIGRATION_025 = ROOT / "data" / "025_enable_platform_admin_rls.sql"


def _strip_sql_comments(sql):
    lines = []
    for line in sql.splitlines():
        lines.append(line.split("--", 1)[0])
    return "\n".join(lines).lower()


def _strip_sql_strings(sql):
    return re.sub(r"'(?:''|[^'])*'", "''", sql)


class PlatformAdminUserManagementContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = CONTRACT.read_text(encoding="utf-8")
        cls.contract_lower = cls.contract.lower()
        cls.contract_flat = re.sub(r"\s+", " ", cls.contract_lower)
        cls.audit_policy = AUDIT_POLICY.read_text(encoding="utf-8")
        cls.audit_policy_lower = cls.audit_policy.lower()
        cls.audit_policy_flat = re.sub(r"\s+", " ", cls.audit_policy_lower)
        cls.rpc_verification_sql = RPC_VERIFICATION_SQL.read_text(encoding="utf-8")
        cls.rpc_verification_sql_lower = cls.rpc_verification_sql.lower()
        cls.rpc_verification_sql_without_comments = _strip_sql_comments(
            cls.rpc_verification_sql
        )
        cls.migration_023 = MIGRATION_023.read_text(encoding="utf-8")
        cls.migration_025 = MIGRATION_025.read_text(encoding="utf-8")

    def test_contract_records_existing_platform_admin_user_schema(self):
        for phrase in [
            "id`, `user_id`, `is_active`, `created_at`, `updated_at`, and nullable `created_by_user_id`",
            "platform_admin_users.user_id` is unique",
            "references `users(id)` with",
            "on update restrict on delete restrict",
            "created_by_user_id` references `users(id)`",
            "on update restrict on delete set null",
            "no timestamp trigger is installed",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.contract_flat)

    def test_authorization_boundary_rejects_tenant_role_authority(self):
        for phrase in [
            "platform access is granted only by an active row in",
            "users.role` value never grants",
            "all future phase 4 routes must use the existing platform-admin blueprint guard",
            "browser-supplied actor ids",
            "service-role credentials remain a backend-only capability",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.contract_flat)

    def test_read_model_uses_safe_existing_fields_only(self):
        for phrase in [
            "platform_admin_user_id",
            "user_email",
            "user_full_name",
            "user_status",
            "creator_email",
            "creator_full_name",
            "do not expose password hashes",
            "tenant role authority",
            "raw audit metadata",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.contract_lower)
        self.assertIn("no reliable `last_login` or `last_seen` field", self.contract_lower)
        self.assertIn("`users.updated_at` must not be presented as login evidence", self.contract_flat)

    def test_create_invite_and_activity_decisions_are_bounded(self):
        for phrase in [
            "adding an existing active internal application user",
            "approved protected internal company",
            "ordinary tenant-company users cannot be added",
            "users.role` remains irrelevant",
            "add existing user: implemented through the bounded rpc/runtime workflow",
            "does not invent a protected company id",
            "create new user account: deferred",
            "send invitation: deferred",
            "existing invitation tables and routes are tenant company-scoped",
            "recent_platform_admin_activity_at",
            "audited platform-admin application activity",
            "does not mean login",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.contract_flat)

    def test_shared_testing_inspection_evidence_and_protected_company_gate_are_recorded(self):
        for phrase in [
            "at the initial phase 4 inspection, no platform-admin user-management route, page, rpc, or dedicated invitation workflow existed",
            "phase 4 now implements the bounded directory/detail routes, add-existing-user rpc workflow, activation/deactivation rpc workflow, and dedicated frontend page",
            "a dedicated platform-admin invitation workflow remains deferred",
            "this contract records the approved and implemented boundary",
            "at the initial phase 4 inspection, the implemented database schema did not contain an authoritative protected/internal/platform/system company designation",
            "migration 034 subsequently introduced the dedicated `platform_admin_protected_companies` registry",
            "approved main shared-testing supabase with fake/team data",
            "not staging verification",
            "platform_admin_users` has exactly the expected existing columns",
            "owned by `postgres`",
            "rls is enabled and not forced",
            "only service-role policies exist",
            "direct table and sequence privileges remain service-role-only",
            "update/delete rejection trigger",
            "require_active_platform_admin_mapping(bigint)",
            "security invoker",
            "search_path=pg_catalog",
            "no existing platform-admin create, activate, deactivate, invite, or bootstrap management rpc exists",
            "active platform-admin mappings: 1",
            "inactive platform-admin mappings: 0",
            "total platform-admin mappings: 1",
            "null creator mappings: 1",
            "missing creator rows: 0",
            "linked creator rows: 0",
            "created_by_user_id` correctly references `users(id)`",
            "the existing mapping belongs to `company_id = 29`",
            "missing_user_count = 0",
            "null_company_count = 0",
            "missing_company_count = 0",
            "companies` exposes no authoritative protected/internal/platform/system designation",
            "only matching company fields were `id` and `business_type`",
            "no company constraint establishes an internal or protected company",
            "users.company_id` references `companies(id)`",
            "protected internal-company inspection and resolution",
            "company_id = 29` was not treated as protected merely because",
            "migration 034 introduced the authoritative registry",
            "registered as the protected internal company for main shared-testing only",
            "successful shared-testing create-mapping e2e remains pending",
            "future deactivation of that mapping must be rejected",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.contract_flat)

    def test_protected_company_design_decision_compares_three_approaches(self):
        for phrase in [
            "dedicated platform-admin protected-company registry",
            "initial inspection did not find an implemented schema object",
            "the alternatives below were evaluated as design rationale",
            "the dedicated registry approach was selected and migration 034 implemented it",
            "company 29 was registered only for the approved main shared-testing supabase",
            "no portable company id is hardcoded",
            "explicit protected/internal marker on `companies`",
            "environment/configuration-only company id",
            "database enforcement",
            "tenant promotion risk",
            "company deletion behavior",
            "bootstrap/recovery",
            "auditability",
            "portability",
            "hardcoded id risk",
            "decision implemented: dedicated database-authoritative protected-company registry",
            "do not hardcode `company_id = 29`",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.contract_flat)

    def test_mutation_design_requires_migration_034_and_atomic_final_admin_protection(self):
        for phrase in [
            "migration 034 is applied and structurally verified only",
            "database-authoritative protected-company registry",
            "python count-then-update sequence is not sufficient",
            "lock table public.platform_admin_users in share row exclusive mode",
            "migration 034 implements mutation protections",
            "rejection when deactivation targets the final active mapping",
            "self-deactivation rejection",
            "self-deactivation is rejected by default",
            "security invoker",
            "set search_path = pg_catalog",
            "executable only by `service_role`",
            "create_platform_admin_user_mapping",
            "validate target user existence, active status, and protected-company membership",
            "reject deactivation of the current shared-testing mapping while it is the only active mapping",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.contract_flat)

    def test_audit_and_frontend_boundaries_are_documented(self):
        for phrase in [
            "platform_admin.user.list",
            "platform_admin.user.read",
            "platform_admin.user.create",
            "platform_admin.user.activate",
            "platform_admin.user.deactivate",
            "approved/implemented bounded phase 4 audit actions",
            "resource type is `platform_admin_users`",
            "http_method",
            "outcome",
            "target_platform_admin_user_id",
            "target_user_id",
            "old_is_active",
            "new_is_active",
            "platform_admin.user.list`: `resource_id` is `null`",
            "platform_admin.user.create`: `resource_id` is the newly created mapping id",
            "docs/platform_admin_audit_policy.md` extends the approved action",
            "passwords, password hashes, tokens, cookies",
            "dedicated platform-admin user-management page",
            "no generic user-management controls",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.contract_lower)

    def test_contract_does_not_regress_to_pre_implementation_language(self):
        for stale in [
            "registry as a desired control, but it is not implemented",
            "add existing user: supported design candidate for phase 4",
            "create remains blocked until that mechanism is approved",
            "future create rpcs should",
            "proposed bounded phase 4 audit actions",
            "phase 4 mutation design must include",
            "recommended migration 034 requirement",
        ]:
            with self.subTest(stale=stale):
                self.assertNotIn(stale, self.contract_lower)

    def test_audit_policy_includes_phase_4_user_management_actions(self):
        for phrase in [
            "platform-admin user management phase 4 and migration 034 are applied and structurally verified only",
            "migration 035 is applied and verified only in the approved main shared-testing supabase",
            "`platform_admin.user.list` | `platform_admin_users` | `null`",
            "`platform_admin.user.read` | `platform_admin_users` | target mapping id",
            "`platform_admin.user.create` | `platform_admin_users` | newly created mapping id",
            "`platform_admin.user.activate` | `platform_admin_users` | target mapping id",
            "`platform_admin.user.deactivate` | `platform_admin_users` | target mapping id",
            "target_platform_admin_user_id",
            "target_user_id",
            "old_is_active",
            "new_is_active",
            "create records `old_is_active = null` and `new_is_active = true`",
            "must not include passwords, password hashes, tokens, tenant roles, company names",
            "migration 034 writes create, activate, and deactivate audit rows atomically",
            "migration 035 is the applied and verified corrective migration",
            "/api/platform-admin/platform-admin-users",
            "/api/platform-admin/platform-admin-users/<platform_admin_user_id>/active",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.audit_policy_flat)

    def test_only_retained_phase_4_tmp_rpc_verification_script_remains(self):
        phase4_tmp_names = sorted(
            path.name for path in TMP.glob("platform_admin_user_management*.sql")
        )
        self.assertEqual(
            phase4_tmp_names,
            ["platform_admin_user_management_034_rpc_verification.sql"],
        )

    def test_retained_rpc_verification_template_covers_pending_second_user_e2e(self):
        for phrase in [
            "template only",
            "do not run until an approved second fake/team active user",
            "protected company: 29, approved only for main shared-testing",
            "existing platform-admin user: 32",
            "<actor_platform_admin_user_id>",
            "<existing_mapped_user_id>",
            "<missing_user_id>",
            "<second_approved_active_user_id>",
            "<second_created_platform_admin_user_id>",
            "begin",
            "rollback",
            "duplicate create rejection",
            "missing target user rejection",
            "self-deactivation rejection",
            "final-active-admin rejection",
            "no-op rejection",
            "create_success_created_one_mapping_and_audit",
            "deactivate_result",
            "activate_result",
            "platform_admin.user.create",
            "platform_admin.user.activate",
            "platform_admin.user.deactivate",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.rpc_verification_sql_lower)
        for forbidden in ("password", "password_hash", "token", "jwt", "email", "full_name"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.rpc_verification_sql_without_comments)

    def test_contract_records_post_apply_bootstrap_and_rpc_verification_plan(self):
        for phrase in [
            "migration 034 has been applied and structurally verified only in the approved main shared-testing supabase",
            "migration 035 is applied and verified only in the approved main shared-testing supabase",
            "protected_company_count = 1",
            "company_29_registry_count = 1",
            "active_platform_admin_count = 1",
            "inactive_platform_admin_count = 0",
            "total_platform_admin_count = 1",
            "user 32 is already the existing platform admin",
            "create_mapping_rpc_exists = true",
            "set_active_rpc_exists = true",
            "mapping_integrity_issue_count = 0",
            "phase 4 mutation audit count after registry bootstrap is 0",
            "old shortened audit endpoint strings are absent",
            "not hardcode 29 as a portable protected company id",
            "successful `create_platform_admin_user_mapping` shared-testing e2e remains pending",
            "platform_admin_user_management_034_rpc_verification.sql",
            "target user from a non-protected company must fail",
            "missing target user must fail",
            "inactive target user must fail",
            "duplicate mapping must fail",
            "create exactly one new active mapping",
            "creator attribution must use the actor mapping's `user_id`",
            "no-op activation/deactivation must fail",
            "self-deactivation must fail",
            "deactivating the final active admin must fail",
            "activation of an ineligible user must fail",
            "valid activation/deactivation must update `updated_at` and audit exactly once",
            "after every rejected rpc, verify there are no partial mapping rows",
            "anon` cannot execute",
            "authenticated` cannot execute",
            "service_role` can execute",
            "users.role` never controls platform-admin access",
            "do not perform the full shared-testing rpc e2e package until a second approved active fake/team user exists in company 29",
            "operator has filled and reviewed the required placeholders",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.contract_flat)

    def test_repository_migrations_still_define_service_role_only_mapping_boundary(self):
        normalized_023 = re.sub(r"\s+", " ", self.migration_023.lower())
        normalized_025 = re.sub(r"\s+", " ", _strip_sql_comments(self.migration_025).lower())
        self.assertIn("users.role values owner/admin/member", normalized_023)
        self.assertIn("grant select, insert, update on public.platform_admin_users to service_role", normalized_023)
        self.assertIn("grant usage on sequence public.platform_admin_users_id_seq to service_role", normalized_023)
        self.assertIn("alter table public.platform_admin_users enable row level security", normalized_025)
        self.assertIn("for select to service_role", normalized_025)
        self.assertIn("for insert to service_role", normalized_025)
        self.assertIn("for update to service_role", normalized_025)
        self.assertNotIn("to anon", normalized_025)
        self.assertNotIn("to authenticated", normalized_025)


if __name__ == "__main__":
    unittest.main()
