import unittest
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


class TenantSupportSubmissionContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = (ROOT / "docs" / "TENANT_SUPPORT_SUBMISSION_CONTRACT.md").read_text(
            encoding="utf-8"
        )
        cls.contract_flat = re.sub(r"\s+", " ", cls.contract)
        cls.roadmap = (ROOT / "docs" / "DEVELOPMENT_ROADMAP.md").read_text(
            encoding="utf-8"
        )
        cls.feature_status = (ROOT / "docs" / "FEATURE_STATUS.md").read_text(
            encoding="utf-8"
        )

    def test_tenant_identity_and_schema_safeguards_are_preserved(self):
        for phrase in (
            "server derives both `company_id` and requester `user_id`",
            "`company_id` and arbitrary requester `user_id`",
            "platform-admin IDs or mapping IDs",
            "status, assignment",
            "platform_support_cases` schema cannot safely support tenant-created",
            "fake or shared platform-admin mapping",
            "commit atomically",
            "Audit failure must prevent a false success response",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)

    def test_first_version_exclusions_are_preserved(self):
        for phrase in (
            "request history/detail",
            "no live chat",
            "unrestricted messaging",
            "no email notifications",
            "no attachments",
            "no billing or remediation actions",
            "no platform-admin impersonation",
            "no exports or charts",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.contract_flat)

    def test_local_backend_status_and_pending_verification_are_recorded(self):
        docs = self.contract + self.roadmap + self.feature_status
        docs_flat = re.sub(r"\s+", " ", docs).lower()
        self.assertIn("post /api/support/requests", docs_flat)
        self.assertIn("backend endpoint", docs_flat)
        self.assertIn("migration 030 is applied and verified", docs_flat)
        self.assertIn("browser/api e2e verification passed", docs_flat)
        self.assertIn("not staging verification", docs_flat)
        self.assertIn("production readiness", docs_flat)
        self.assertNotIn("no tenant support api exists", docs_flat)

    def test_verified_contract_has_no_pre_implementation_wording(self):
        for phrase in (
            "unapplied schema draft",
            "may later add a form",
            "before implementation",
            "implementation requires approval",
        ):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, self.contract_flat.lower())


if __name__ == "__main__":
    unittest.main()
