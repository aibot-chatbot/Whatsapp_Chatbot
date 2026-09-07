import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "PLATFORM_ADMIN_MONITORING_PHASE_6_CONTRACT.md"
AUDIT_POLICY = ROOT / "docs" / "PLATFORM_ADMIN_AUDIT_POLICY.md"
FEATURE_STATUS = ROOT / "docs" / "FEATURE_STATUS.md"
ROADMAP = ROOT / "docs" / "DEVELOPMENT_ROADMAP.md"
INSPECTION_SQL = ROOT / "tmp" / "platform_admin_phase6_monitoring_inspection.sql"


def _flat(text):
    return re.sub(r"\s+", " ", text.lower())


class PlatformAdminMonitoringDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = CONTRACT.read_text(encoding="utf-8")
        cls.contract_flat = _flat(cls.contract)
        cls.audit_flat = _flat(AUDIT_POLICY.read_text(encoding="utf-8"))
        cls.feature_flat = _flat(FEATURE_STATUS.read_text(encoding="utf-8"))
        cls.roadmap_flat = _flat(ROADMAP.read_text(encoding="utf-8"))

    def test_contract_records_phase_six_read_only_scope(self):
        for phrase in [
            "read-only extension of `get /api/platform-admin/overview`",
            "without adding new platform-admin mutation routes",
            "platform authority continues to come only from active `platform_admin_users`",
            "tenant `users.role` never grants platform-admin access",
            "migration 037 is applied and verified only in that main shared-testing environment",
            "not staging verification",
            "does not establish production readiness",
            "prototype/shared-testing environment",
            "not the future real production environment",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)

    def test_contract_records_implemented_metrics_and_alerts(self):
        for phrase in [
            "platform summary",
            "support operations",
            "messaging & integrations",
            "billing attention",
            "ai usage & credits",
            "platform-admin activity",
            "`support_backlog`",
            "`billing_orders_pending`",
            "`billing_reconciliation_required`",
            "`ai_credit_depleted`",
            "`messaging_retry_backlog`",
            "`integration_channel_attention`",
            "existing subscription alerts remain",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)

    def test_contract_records_performance_retry_and_channel_semantics(self):
        for phrase in [
            "one bounded read-only postgresql rpc",
            "`public.get_platform_admin_monitoring_overview()`",
            "unsupported postgrest aggregate select syntax",
            "`status,count:id.count()` with http 400",
            "existing company/subscription overview reads remain separate",
            "per-domain exact-count loops",
            "unsupported aggregate values fail closed",
            "`sender_type = bot`",
            "`ai_generated = true`",
            "`delivery_status = failed`",
            "`retry_count` is null or below the retry limit",
            "`next_retry_at` is null or currently due",
            "channel attention counts distinct configured channels",
            "counted once",
            "provider with zero configured channels is a healthy empty monitoring state",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)

    def test_contract_records_security_exclusions_and_omitted_metrics(self):
        for phrase in [
            "message text",
            "customer phone numbers",
            "prompts",
            "raw provider errors",
            "provider payloads",
            "webhook payloads",
            "api keys or tokens",
            "payment references",
            "raw audit metadata",
            "support sla or overdue metrics",
            "no authoritative deadline field exists",
            "ai low-balance metric",
            "no approved low-balance threshold exists",
            "generic background job health",
            "no durable authoritative job telemetry exists",
            "provider cost monitoring",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)

    def test_shared_testing_evidence_is_recorded_as_evidence_not_expectation(self):
        for phrase in [
            "25 active companies",
            "14 active users",
            "88 sent and 77 received messages",
            "retry backlog 0",
            "452 completed ai requests",
            "zero depleted balances",
            "four pending billing orders",
            "zero reconciliation-required orders",
            "verification evidence only, not permanent business expectations",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)

    def test_whatsapp_compatibility_fix_is_documented_as_regression_repair(self):
        for phrase in [
            "phase 5 broadcast regression test",
            "`get_interactive_button_message_input()` was restored",
            "maximum three buttons",
            "titles truncated to 20 characters",
            "compatibility repair, not a phase 6 monitoring feature",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)

    def test_status_docs_and_audit_policy_are_current(self):
        for docs_flat in [self.feature_flat, self.roadmap_flat]:
            for phrase in [
                "platform-admin platform monitoring phase 6 is implemented locally",
                "read-only extension of `get /api/platform-admin/overview`",
                "no new platform-admin mutation routes",
                "migration 037 was introduced",
                "`public.get_platform_admin_monitoring_overview()` rpc",
                "executable only by service_role",
                "no writes",
                "no dynamic sql",
                "filtered to current approved audit actions and resource types",
                "returned 200 for `/api/platform-admin/me`",
            "platform operations dashboard rendered",
            "final superadmin prototype runtime verification",
            "approved main shared-testing supabase with fake/team data",
                "not staging verification",
                "does not establish production readiness",
                "full platform admin browser suite",
            ]:
                with self.subTest(phrase=phrase):
                    self.assertIn(phrase, docs_flat)
            for phrase in [
                "support backlog",
                "pending and reconciliation-required billing orders",
                "depleted ai-credit balances",
                "retry backlog",
                "integration channel attention",
                "ai low-balance alerts remain deferred because no threshold is approved",
                "generic background job monitoring remains deferred because no durable telemetry exists",
                "provider-cost monitoring",
                "overview remediation/write",
            ]:
                with self.subTest(phrase=phrase):
                    self.assertIn(phrase, docs_flat)
        for phrase in [
            "phase 6 read-only platform monitoring overview aggregates",
            "reuses `platform_admin.operations.overview.read`",
            "adds no mutation audit actions",
            "migration 037 adds one bounded read-only `public.get_platform_admin_monitoring_overview()` rpc",
            "rpc execute service-role-only",
            "historical audit rows were not deleted or modified",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.audit_flat)

    def test_no_stale_phase_six_claims_or_temp_artifact_remain(self):
        combined = " ".join([self.contract_flat, self.feature_flat, self.roadmap_flat, self.audit_flat])
        for phrase in [
            "no migration 037 is required",
            "no sql migration was required",
            "no sql migration was required or applied",
            "22 supabase table executions",
            "phase 6 is staging verified",
            "phase 6 is production ready",
            "browser e2e passed",
            "support overdue metric is implemented",
            "low-balance alert is implemented",
            "generic job health is implemented",
            "ai-credit alerts, billing-order attention alerts",
            "ai-credit alerts remain deferred",
            "billing-order attention alerts remain deferred",
            "| cross-company dashboard | deferred |",
        ]:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, combined)
        self.assertFalse(INSPECTION_SQL.exists())

    def test_cross_company_dashboard_limitation_is_qualified(self):
        dashboard_row = re.search(
            r"\| cross-company dashboard \| (?P<scope>[^|]+)\|",
            self.feature_flat,
        )
        self.assertIsNotNone(dashboard_row)
        scope = dashboard_row.group("scope")
        for phrase in [
            "bounded read-only operational aggregates",
            "operations/billing overview apis",
            "charts",
            "local application",
            "generic/unrestricted cross-company analytics",
            "arbitrary global drilldowns",
            "unrestricted exports",
            "unrestricted tenant browsing",
            "generic remediation/write controls remain deferred",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, scope)


if __name__ == "__main__":
    unittest.main()
