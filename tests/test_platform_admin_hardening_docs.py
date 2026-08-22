import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FEATURE_STATUS = ROOT / "docs" / "FEATURE_STATUS.md"
ROADMAP = ROOT / "docs" / "DEVELOPMENT_ROADMAP.md"
SUPPORT_CONTRACT = ROOT / "docs" / "PLATFORM_ADMIN_SUPPORT_WORKFLOW_CONTRACT.md"
BILLING_CONTRACT = ROOT / "docs" / "PLATFORM_ADMIN_BILLING_PHASE_7_CONTRACT.md"


def _flat(text):
    return re.sub(r"\s+", " ", text.lower())


class PlatformAdminHardeningDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.feature = _flat(FEATURE_STATUS.read_text(encoding="utf-8"))
        cls.roadmap = _flat(ROADMAP.read_text(encoding="utf-8"))
        cls.support = _flat(SUPPORT_CONTRACT.read_text(encoding="utf-8"))
        cls.billing = _flat(BILLING_CONTRACT.read_text(encoding="utf-8"))
        cls.combined = " ".join([cls.feature, cls.roadmap, cls.support, cls.billing])

    def test_environment_boundary_for_migrations_043_and_044_is_canonical(self):
        for docs_flat in [self.feature, self.roadmap, self.support]:
            for phrase in [
                "prototype/shared-testing",
                "not staging verification",
                "does not establish production readiness",
            ]:
                with self.subTest(phrase=phrase):
                    self.assertIn(phrase, docs_flat)
        for phrase in [
            "migration 043",
            "data/043_atomic_platform_support_case_creation.sql",
            "migration 044",
            "data/044_platform_admin_user_recent_activity_batch.sql",
            "applied and runtime verified in prototype/shared-testing only",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.combined)
        for forbidden in [
            "migration 043 was not created",
            "migration 043 was not required and was not created",
            "no migration 043",
            "migration 044 was not created",
            "migration 044 was not required",
            "staging verified for the current superadmin milestone",
            "production deployed for the current superadmin milestone",
            "production verified for the current superadmin milestone",
            "superadmin prototype milestone is production ready",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.combined)

    def test_final_hardening_status_is_documented_without_reopening_prototype_defects(self):
        for phrase in [
            "consolidated hardening verification pass",
            "310 passed tests and 779 subtests",
            "431 passed tests and 991 subtests",
            "atomic support-case creation",
            "bounded support history pagination",
            "pagination regression repairs",
            "platform-admin recent-activity batching",
            "human-readable assignee identities",
            "inactive historical assignee safety",
            "current phase 6 is sufficient for prototype/shared-testing",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.combined)

    def test_phase_four_and_platform_access_wording_remains_bounded(self):
        for phrase in [
            "bounded platform admin management",
            "broader phase 4 platform admin account-management expansion remains deferred",
            "broader lifecycle expansion remains intentionally deferred",
            "tenant roles and jwt claims do not grant platform access",
            "platform_admin_users.id",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.combined)
        self.assertNotIn("users.role grants platform", self.combined)
        self.assertNotIn("phase 4 platform admin user management expansion is fully implemented", self.combined)

    def test_phase_six_monitoring_is_closed_for_prototype_with_production_work_deferred(self):
        for phrase in [
            "platform-admin platform monitoring phase 6 is implemented locally",
            "company counts",
            "active users",
            "support workload",
            "messaging delivery/channel health",
            "billing/order attention",
            "ai request/token activity",
            "aggregate platform-admin activity",
            "operational alerts",
            "deeper monitoring/observability",
            "durable background job/run monitoring",
            "formal sla/slo/alert definitions",
            "provider/model ai failure depth",
            "centralized structured logs/metrics",
            "deferred production or optional hardening work",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.combined)

    def test_platform_admin_summary_evidence_levels_are_not_flattened_to_local_only(self):
        for phrase in [
            "original scope staging verified; later extensions have mixed local and prototype/shared-testing evidence",
            "later extensions have mixed evidence",
            "some remain local/application-tested only",
            "phase 5, phase 6, phase 7, and migration 043/044 hardening paths have prototype/shared-testing runtime verification",
            "not automatically staging verified",
            "real production remains blocked",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.combined)
        for forbidden in [
            "current 12-route stack local-only",
            "current 12-route stack verified locally",
            "extensions are application-only/local-tested unless separately staged",
            "later extensions remain application-only/local-tested unless separately staged",
            "operations-overview, operational alerts, users/chatbots, subscription-history, ai-credit transaction-history, audit-log viewer, and billing-order history extensions locally tested only",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.combined)


if __name__ == "__main__":
    unittest.main()
