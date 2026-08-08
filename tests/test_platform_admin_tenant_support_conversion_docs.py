import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "PLATFORM_ADMIN_TENANT_SUPPORT_CONVERSION_CONTRACT.md"


class PlatformAdminTenantSupportConversionDocsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flat = re.sub(r"\s+", " ", DOC.read_text(encoding="utf-8")).lower()

    def test_design_and_transaction_boundaries(self):
        for phrase in (
            "runtime code and migration 031 are implemented and verified only in the main shared testing supabase",
            "browser/api e2e passed locally",
            "fake/team data",
            "converted_platform_support_case_id",
            "on delete restrict",
            "uniqueness",
            "python multi-write sequences are not sufficient",
            "convert_tenant_support_request",
            "set_tenant_support_request_status",
            "no partial case, event, status, link, or audit changes",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.flat)

    def test_workflows_and_actor_rules(self):
        for phrase in (
            "patch /api/platform-admin/tenant-support-requests/<request_id>",
            "post /api/platform-admin/tenant-support-requests/<request_id>/convert",
            '"status": "reviewed"',
            '"status": "closed"',
            "empty body",
            "active `platform_admin_users` mapping",
            "no fake, shared, or fabricated platform-admin actor",
            "actor_platform_admin_user_id",
            "tenant_support_audit_events` remains tenant-source only",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.flat)

    def test_audit_and_prohibited_controls(self):
        for phrase in (
            "platform_admin.tenant_support_request.review",
            "platform_admin.tenant_support_request.close",
            "platform_admin.tenant_support_request.convert",
            "old_status",
            "new_status",
            "audit evidence must exist before a successful response",
            "never record titles",
            "customer messaging",
            "tenant replies",
            "billing actions",
            "impersonation",
            "non-atomic conversion",
            "no staging or production use",
            "production remains blocked",
            "request 1 was marked reviewed and then converted",
            "converted_platform_support_case_id = 2",
            "internal platform support case 2 was created once",
            "http_method",
            "anon = false",
            "authenticated = false",
            "service_role = true",
            "security invoker",
            "search_path = pg_catalog",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.flat)


if __name__ == "__main__":
    unittest.main()
