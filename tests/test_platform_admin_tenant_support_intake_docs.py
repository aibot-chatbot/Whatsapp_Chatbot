import unittest
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "PLATFORM_ADMIN_TENANT_SUPPORT_INTAKE_VIEWER_CONTRACT.md"


class PlatformAdminTenantSupportIntakeDocsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = DOC.read_text(encoding="utf-8")
        cls.flat = re.sub(r"\s+", " ", cls.doc).lower()

    def test_endpoint_separation_and_read_only_boundary(self):
        for phrase in (
            "get /api/platform-admin/tenant-support-requests",
            "get /api/platform-admin/tenant-support-requests/<request_id>",
            "/api/platform-admin/support-cases",
            "platform_admin_required",
            "no `post`, `patch`, `put`, or `delete` route",
            "no automatic conversion",
            "no mutation of `tenant_support_requests`",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.flat)

    def test_safe_projection_and_audit_exclusions(self):
        for phrase in (
            "requester_user_id",
            "redacted_description",
            "event_type",
            "actor_type",
            "title and description must be rendered as text only",
            "must not include title, description",
            "raw tenant audit payloads remain excluded",
            "audit insertion is required before returning",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.flat)

    def test_sensitive_and_deployment_boundaries_are_preserved(self):
        for phrase in (
            "no customer messaging",
            "no email",
            "no attachments",
            "no billing action",
            "no impersonation",
            "no export or chart",
            "not staging verification or production readiness",
            "production remains blocked",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.flat)


if __name__ == "__main__":
    unittest.main()
