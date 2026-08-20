import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "PLATFORM_ADMIN_BILLING_PHASE_7_CONTRACT.md"
AUDIT_POLICY = ROOT / "docs" / "PLATFORM_ADMIN_AUDIT_POLICY.md"
FEATURE_STATUS = ROOT / "docs" / "FEATURE_STATUS.md"
ROADMAP = ROOT / "docs" / "DEVELOPMENT_ROADMAP.md"
INSPECTION_SQL = ROOT / "tmp" / "platform_admin_phase7_billing_inspection.sql"


def _flat(text):
    return re.sub(r"\s+", " ", text.lower())


class PlatformAdminBillingDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = CONTRACT.read_text(encoding="utf-8")
        cls.contract_flat = _flat(cls.contract)
        cls.audit_flat = _flat(AUDIT_POLICY.read_text(encoding="utf-8"))
        cls.feature_flat = _flat(FEATURE_STATUS.read_text(encoding="utf-8"))
        cls.roadmap_flat = _flat(ROADMAP.read_text(encoding="utf-8"))

    def test_contract_records_final_phase_seven_status_and_runtime_evidence(self):
        for phrase in [
            "read-only platform-admin surface",
            "migration 038 is applied and verified only in the approved main shared-testing supabase",
            "migration 043 was not required and was not created",
            "fake/team data",
            "not staging verification",
            "does not establish production readiness",
            "prototype/shared-testing environment",
            "not the future real production environment",
            "`get /api/platform-admin/billing/overview` returned 200",
            "`get /api/platform-admin/billing/companies?limit=25&offset=0` returned 200",
            "final superadmin prototype runtime verification reconfirmed",
            "25 companies out of 27 total",
            "`subscription_status=active`, `plan=pro`, and `attention=true` filters each returned 200",
            "platform billing & subscriptions frontend rendered",
            "no financial mutation controls are present",
            "latest dedicated billing browser group: 5 passed",
            "latest full platform admin browser suite: 70 passed",
            "latest frontend source-contract suite: 54 passed, 14 subtests passed",
            "153 tests and 271 subtests",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)

    def test_contract_records_responsive_accessibility_and_navigation_hardening(self):
        for phrase in [
            "explicit labels for subscription status, plan code, and attention",
            "stable `htmlfor`/id relationships",
            "desktop billing tables remain available",
            "tablet layouts keep the normal panel/table flow",
            "mobile layouts at 767px and below keep billing information visible",
            "compact mobile-card representations",
            "shared table hiding for unrelated pages was not weakened",
            "tenant billing directory mobile cards use only safe api fields",
            "`platform-admin-company.html?company_id=<id>`",
            "actual mobile view company navigation",
            "untrusted `innerhtml` was not introduced",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)

    def test_contract_records_migration_rpc_security_and_scope(self):
        for phrase in [
            "`public.get_platform_admin_billing_overview()`",
            "`public.get_platform_admin_billing_companies(integer, integer, text, text, boolean)`",
            "`public.get_platform_admin_monitoring_overview()`",
            "security invoker",
            "search_path=pg_catalog",
            "have `execute` granted only to `service_role`",
            "migration 038 contains no dynamic sql, no writes, no table grant weakening, and no rls weakening",
            "phase 7 billing read actions and resource types in platform-admin activity",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)

    def test_contract_records_null_subscription_and_performance_contracts(self):
        for phrase in [
            "`subscription_status = null`",
            "`current_plan = null`",
            "`current_period_start = null`",
            "`current_period_end = null`",
            "`pending_plan_change = false`",
            "`cancellation_scheduled = false`",
            "do not invent a synthetic subscription status",
            "one bounded billing-overview rpc",
            "one bounded billing-company-directory rpc",
            "no python 10,000-row directory scan",
            "no per-company n+1 billing-directory aggregation",
            "postgresql-side filtering, counting, and pagination",
            "stable `company_id asc` ordering",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)

    def test_contract_records_deferred_financial_mutations_and_privacy_exclusions(self):
        for phrase in [
            "manual ai-credit adjustment",
            "payment reconciliation mutation",
            "refund",
            "subscription correction or override",
            "manual plan change",
            "direct balance editing",
            "payment retry mutation",
            "manual credit reversal",
            "billing impersonation or remediation controls",
            "direct balance editing is not appropriate for the current milestone",
            "payment references",
            "checkout urls",
            "gateway identifiers",
            "idempotency keys",
            "raw gateway or callback payloads",
            "raw reconciliation errors",
            "raw prompts or responses",
            "raw audit metadata",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)

    def test_audit_policy_records_phase_seven_read_actions(self):
        for phrase in [
            "phase 7 read-only billing/subscription oversight actions",
            "`platform_admin.billing.overview.read`",
            "`platform_admin.billing.company_list`",
            "`platform_billing_overview`",
            "`platform_billing_companies`",
            "`subscription_status_filter_applied`",
            "`plan_filter_applied`",
            "`attention_filter_applied`",
            "phase 7 billing audit metadata must not include financial values",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.audit_flat)
        self.assertIn(
            "`http_method` | `get` for approved investigation actions; `post` or `patch` only",
            self.audit_flat,
        )

    def test_roadmap_and_feature_status_record_final_phase_seven_without_overclaiming(self):
        for docs_flat in [self.feature_flat, self.roadmap_flat]:
            for phrase in [
                "platform-admin billing & subscription oversight phase 7 is implemented for the current read-only milestone",
                "current read-only milestone",
                "read-only",
                "platform billing & subscriptions",
                "migration 038 is applied and verified only in the approved main shared-testing supabase",
                "migration 043 was not required and was not created",
                "current superadmin prototype milestone is runtime-verified complete",
                "not the future real production environment",
                "`public.get_platform_admin_billing_overview()`",
                "`public.get_platform_admin_billing_companies(integer, integer, text, text, boolean)`",
                "`public.get_platform_admin_monitoring_overview()`",
                "companies without subscriptions",
                "pagination",
                "postgresql",
                "manual ai-credit adjustment",
                "payment reconciliation mutation",
                "direct balance editing",
                "remain deferred",
                "mobile billing",
                "subscription status, plan code, and attention",
                "`platform-admin-company.html?company_id=<id>`",
                "not staging verification",
                "does not establish production readiness",
            ]:
                with self.subTest(phrase=phrase):
                    self.assertIn(phrase, docs_flat)

    def test_no_stale_phase_seven_claims_or_temp_artifact_remain(self):
        combined = " ".join(
            [self.contract_flat, self.audit_flat, self.feature_flat, self.roadmap_flat]
        )
        for phrase in [
            "migration 038 is drafted",
            "migration 038 is unapplied",
            "migration 038 is unverified",
            "no migration 038 required",
            "no sql migration required",
            "phase 7 is staging verified",
            "phase 7 is production ready",
            "financial mutations are implemented",
            "manual ai-credit adjustment is implemented",
            "payment reconciliation mutation is implemented",
            "billing impersonation is implemented",
        ]:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, combined)
        self.assertFalse(INSPECTION_SQL.exists())


if __name__ == "__main__":
    unittest.main()
