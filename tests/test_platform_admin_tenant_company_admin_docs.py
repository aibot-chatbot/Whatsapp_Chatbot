import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "PLATFORM_ADMIN_TENANT_COMPANY_ADMIN_CONTRACT.md"
AUDIT_POLICY = ROOT / "docs" / "PLATFORM_ADMIN_AUDIT_POLICY.md"
FEATURE_STATUS = ROOT / "docs" / "FEATURE_STATUS.md"
ROADMAP = ROOT / "docs" / "DEVELOPMENT_ROADMAP.md"
WORKING_NOTES = ROOT / "docs" / "PLATFORM_ADMIN_TENANT_COMPANY_ADMIN_PHASE_5_WORKING_NOTES.md"
INSPECTION_SQL = ROOT / "tmp" / "platform_admin_phase5_company_status_inspection.sql"


def _flat(text):
    return re.sub(r"\s+", " ", text.lower())


class PlatformAdminTenantCompanyAdminDocsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = CONTRACT.read_text(encoding="utf-8")
        cls.contract_flat = _flat(cls.contract)
        cls.audit_policy = AUDIT_POLICY.read_text(encoding="utf-8")
        cls.audit_flat = _flat(cls.audit_policy)
        cls.feature_status_flat = _flat(FEATURE_STATUS.read_text(encoding="utf-8"))
        cls.roadmap_flat = _flat(ROADMAP.read_text(encoding="utf-8"))

    def test_phase_five_contract_records_scope_and_exclusions(self):
        for phrase in [
            "platform-admin tenant and company administration phase 5 is implemented locally",
            "migration 036 was applied and verified only in the approved main shared-testing supabase with fake/team data",
            "this is not staging verification and does not establish production readiness",
            "impersonation",
            "company deletion",
            "tenant role administration",
            "password reset",
            "manual credit adjustment",
            "arbitrary subscription or billing mutation",
            "suspension reason fields",
            "users.role` never grants platform-admin authority",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)

    def test_suspension_semantics_and_exceptions_are_documented(self):
        for phrase in [
            "`active`: normal tenant operational activity is allowed",
            "`inactive`: platform-admin administrative suspension",
            "authentication may still establish identity",
            "not by claiming that `token_required` globally rejects every suspended-company read",
            "tenant support submission and support history/detail",
            "approved read-only billing history and receipts",
            "legitimate financial reconciliation and accounting callbacks",
            "workspace and profile mutations",
            "team role and status mutations",
            "telegram, wasender, and meta whatsapp inbound processing",
            "ai chat generation and system/background ai generation",
            "billing checkout, top-up, retry, cancellation, undo-cancellation, downgrade",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)

    def test_runtime_enforcement_contract_is_authoritative(self):
        for phrase in [
            "ensure_company_operational",
            "company_operational_required",
            "server-loaded chatbot, channel, or bot records",
            "system/background ai derives `company_id` from the chatbot record",
            "resolve_ai_access(company_id)` always runs even outside flask request context",
            "flask `g` values cannot override the bot-derived company id",
            "before each recipient send",
            "unsent pending recipients are marked failed with a sanitized reason",
            "normal runtime code calls the migration 036 rpcs",
            "it does not directly update `companies.status`",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)

    def test_database_and_shared_testing_evidence_are_current(self):
        for phrase in [
            "`companies.status` is `not null`",
            "default is `'active'`",
            "check constraint allows only `active` and `inactive`",
            "companies` rls remains disabled and not forced",
            "`anon`: no direct `companies` privileges",
            "`authenticated`: no direct `companies` privileges",
            "`service_role`: `select`, `insert`, and `update` only",
            "`companies_id_seq`: `service_role` `usage` only",
            "suspend_platform_company(bigint,bigint)",
            "restore_platform_company(bigint,bigint)",
            "`security invoker`",
            "`search_path=pg_catalog`",
            "service-role-only rpc execute",
            "25 total companies",
            "25 active companies after test cleanup",
            "0 inactive companies after test cleanup",
            "0 invalid or null company statuses",
            "company 23 final status is `active`",
            "company 29 remained active and protected",
            "no live tenant-runtime suspension e2e was performed",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)

    def test_audit_policy_records_phase_five_actions_and_safe_metadata(self):
        for phrase in [
            "platform-admin tenant and company administration phase 5 and migration 036 are applied and verified only",
            "`platform_admin.company.suspend`",
            "`platform_admin.company.restore`",
            "`resource_type = company`",
            "`resource_id = target company id`",
            "`endpoint`, `http_method`, `outcome`, `company_id`,",
            "`old_status`, `new_status`",
            "audit event 355",
            "audit event 356",
            "safe fixed lifecycle metadata only",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)
        for phrase in [
            "`platform_admin.company.suspend`",
            "`platform_admin.company.restore`",
            "platform-admin tenant and company administration phase 5 and migration 036 are applied and verified only",
            "phase 5 bounded tenant/company lifecycle actions",
            "`company_id`",
            "`old_status`",
            "`new_status`",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.audit_flat)

    def test_audit_policy_http_methods_include_only_approved_mutation_families(self):
        expected = (
            "`http_method` | `get` for approved investigation actions; `post` or `patch` only "
            "for the explicitly approved bounded support-case, platform-admin user-management, "
            "and company lifecycle actions"
        )
        self.assertIn(expected, self.audit_flat)
        self.assertIn("phase 5 bounded tenant/company lifecycle actions", self.audit_flat)
        self.assertNotIn(
            "post` or `patch` only for the approved bounded support-case and platform-admin user-management actions",
            self.audit_flat,
        )

    def test_status_docs_record_phase_five_without_staging_or_production_claims(self):
        for docs_flat in [self.feature_status_flat, self.roadmap_flat]:
            for phrase in [
                "platform-admin tenant and company administration phase 5 is implemented locally",
                "migration 036 is applied and verified only in the approved main shared-testing supabase with fake/team data",
                "company 23",
                "company 29",
                "no live tenant-runtime suspension e2e",
                "staging verification",
                "production readiness",
            ]:
                with self.subTest(phrase=phrase):
                    self.assertIn(phrase, docs_flat)

    def test_twelve_get_routes_are_read_only_inventory_not_complete_api(self):
        for docs_flat in [self.feature_status_flat, self.roadmap_flat]:
            for phrase in [
                "twelve-route read-only investigation stack",
                "complete platform-admin surface additionally includes",
                "bounded support-case",
                "platform-admin user-management",
                "company lifecycle",
                "those later mutation routes are not staging verified",
            ]:
                with self.subTest(phrase=phrase):
                    self.assertIn(phrase, docs_flat)
            self.assertNotIn("current platform-admin backend inventory is twelve get-only", docs_flat)
            self.assertNotIn("all platform-admin write controls remain deferred", docs_flat)
            self.assertNotIn("all platform-admin write actions remain deferred", docs_flat)
        self.assertIn("overview remediation/write controls remain deferred", self.roadmap_flat)
        self.assertIn("overview remediation/write actions remain deferred", self.feature_status_flat)

    def test_temporary_phase_five_artifacts_are_not_required(self):
        self.assertFalse(WORKING_NOTES.exists())
        self.assertFalse(INSPECTION_SQL.exists())


if __name__ == "__main__":
    unittest.main()
