import unittest
from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "043_atomic_platform_support_case_creation.sql"
)


class PlatformAdminSupportCaseCreationMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.normalized = "\n".join(
            line for line in cls.sql.splitlines()
            if not line.lstrip().startswith("--")
        ).lower()
        cls.body = cls.normalized.split(
            "create or replace function public.create_platform_support_case("
        )[1].split("$function$;", 1)[0]

    def test_atomic_creation_rpc_contains_case_event_and_audit_writes(self):
        self.assertIn("create or replace function public.create_platform_support_case(", self.normalized)
        self.assertEqual(self.body.count("insert into public.platform_support_cases"), 1)
        self.assertEqual(self.body.count("insert into public.platform_support_case_events"), 1)
        self.assertEqual(self.body.count("insert into public.platform_admin_audit_events"), 1)
        self.assertNotIn("exception when", self.body)
        self.assertNotIn("commit", self.body)

    def test_rpc_preserves_initial_event_and_audit_semantics(self):
        self.assertIn("'created'", self.body)
        self.assertIn("new_status", self.body)
        self.assertIn("new_priority", self.body)
        self.assertIn("'platform_admin.support_case.create'", self.body)
        self.assertIn("'platform_support_cases'", self.body)
        self.assertIn("'/api/platform-admin/support-cases'", self.body)
        self.assertIn("'http_method', 'post'", self.body)
        self.assertIn("'company_id', p_company_id", self.body)
        self.assertNotIn("p_title", self.body.split("insert into public.platform_admin_audit_events", 1)[1])
        self.assertNotIn(
            "p_redacted_summary",
            self.body.split("insert into public.platform_admin_audit_events", 1)[1],
        )

    def test_rpc_validates_active_platform_admin_and_does_not_use_tenant_role(self):
        self.assertIn("perform public.require_active_platform_admin_mapping(p_platform_admin_user_id)", self.body)
        self.assertIn("from public.companies", self.body)
        self.assertIn("where id = p_company_id", self.body)
        self.assertIn("for key share", self.body)
        self.assertNotIn("users.role", self.body)

    def test_rpc_privileges_are_backend_only(self):
        self.assertIn(
            "revoke all on function public.create_platform_support_case(bigint, bigint, text, text, text, text)\n"
            "    from public, anon, authenticated, service_role",
            self.normalized,
        )
        self.assertIn(
            "grant execute on function public.create_platform_support_case(bigint, bigint, text, text, text, text)\n"
            "    to service_role",
            self.normalized,
        )


if __name__ == "__main__":
    unittest.main()
