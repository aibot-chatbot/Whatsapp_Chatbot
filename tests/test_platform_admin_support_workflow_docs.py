import unittest
from pathlib import Path


DOC = Path(__file__).resolve().parents[1] / "docs" / "PLATFORM_ADMIN_SUPPORT_WORKFLOW_CONTRACT.md"


class PlatformAdminSupportWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DOC.read_text(encoding="utf-8")

    def test_current_workspace_and_deferred_concepts_are_recorded(self):
        for phrase in [
            "read-only investigation hub",
            "GET /api/platform-admin/overview",
            "GET /api/platform-admin/companies",
            "Support Cases Phase 1",
            "case status",
            "priority",
            "assignment",
            "internal notes",
            "customer contact link",
            "audit trail",
            "SLA target",
            "deferred",
            "application code and migration draft are implemented locally",
            "migration remains unapplied",
            "end-to-end DB verification is pending",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_safety_and_data_model_boundaries_are_present(self):
        for phrase in [
            "impersonation",
            "password reset",
            "billing retry, reconciliation, manual credit",
            "plan changes",
            "customer message sending",
            "exports",
            "raw customer content",
            "platform_support_cases",
            "platform_support_case_events",
            "assigned_platform_admin_user_id",
            "safe references to `company_id` only",
            "raw secrets, tokens, cookies, provider payloads",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_approval_and_localhost_boundaries_are_present(self):
        for phrase in [
            "support process owner",
            "privacy review",
            "retention policy",
            "audit metadata and evidence approval",
            "customer communication policy",
            "confirmed staging environment",
            "localhost-verified only",
            "production remains blocked",
            "no migration execution",
            "production readiness",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)


if __name__ == "__main__":
    unittest.main()
