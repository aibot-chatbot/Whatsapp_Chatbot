"""Source-contract checks for platform-admin access lifecycle safeguards."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE_DOC = ROOT / "docs" / "PLATFORM_ADMIN_ACCESS_LIFECYCLE.md"


class TestPlatformAdminAccessLifecycleDocumentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = LIFECYCLE_DOC.read_text(encoding="utf-8")
        cls.lower_document = cls.document.lower()

    def test_access_authority_and_identity_safeguards_are_documented(self):
        for phrase in [
            "users.role` never grants platform access",
            "active `platform_admin_users` mapping",
            "shared accounts are prohibited",
            "prefer temporary access",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.lower_document)

    def test_bootstrap_and_revocation_boundaries_are_documented(self):
        for phrase in [
            "production remains blocked",
            "no sql should be run without a named approved executor",
            "require access denied",
            "stale-data clearing outcome",
            "docs/platform_admin_emergency_revocation.md",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.lower_document)

    def test_evidence_redaction_safeguards_are_documented(self):
        for phrase in [
            "tokens",
            "cookies",
            "secrets",
            "full response bodies",
            "sensitive customer data",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.lower_document)

    def test_management_and_write_controls_remain_non_goals(self):
        self.assertIn("a platform-admin management ui", self.lower_document)
        self.assertIn("write controls", self.lower_document)
        self.assertIn("does not create access", self.lower_document)


if __name__ == "__main__":
    unittest.main()
