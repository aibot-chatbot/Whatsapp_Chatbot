import unittest
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


class PlatformAdminSqlSafetyDocsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lifecycle = (ROOT / "docs" / "PLATFORM_ADMIN_ACCESS_LIFECYCLE.md").read_text(
            encoding="utf-8"
        )
        cls.roadmap = (ROOT / "docs" / "DEVELOPMENT_ROADMAP.md").read_text(
            encoding="utf-8"
        )
        cls.feature_status = (ROOT / "docs" / "FEATURE_STATUS.md").read_text(
            encoding="utf-8"
        )
        cls.lifecycle_flat = re.sub(r"\s+", " ", cls.lifecycle)

    def test_sql_preflight_requires_environment_identity_and_stop_rule(self):
        for phrase in (
            "project name",
            "project ref",
            "environment label",
            "localhost/dev",
            "approved staging",
            "not a production URL",
            "pre-apply target screenshot",
            "shows `PRODUCTION`",
            "stop immediately",
            "row counts before apply/rollback",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.lifecycle_flat.lower())

    def test_migration_029_incident_and_future_boundary_are_recorded(self):
        for phrase in (
            "Migration 029 was accidentally applied",
            "main/PRODUCTION",
            "No support-case rows",
            "no tenant data changed",
            "no `platform_admin_users` mappings",
            "platform_support_cases",
            "platform_support_case_events",
            "their sequences",
            "must not be tested on production",
            "production remains blocked",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.lifecycle)

    def test_evidence_redaction_and_status_docs_are_preserved(self):
        for phrase in (
            "no secrets, tokens, cookies",
            "full response bodies",
            "Future SQL is limited",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.lifecycle + self.roadmap)
        self.assertIn("production remains blocked", self.feature_status)


if __name__ == "__main__":
    unittest.main()
