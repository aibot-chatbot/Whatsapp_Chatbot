import unittest
from pathlib import Path


MIGRATION = Path(__file__).resolve().parents[1] / "data" / "029_create_platform_admin_support_cases.sql"


class PlatformAdminSupportCasesMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.code = "\n".join(
            line for line in cls.sql.splitlines()
            if not line.lstrip().startswith("--")
        ).lower()

    def test_draft_creates_only_safe_case_tables_and_fields(self):
        for marker in (
            "create table if not exists public.platform_support_cases",
            "create table if not exists public.platform_support_case_events",
            "company_id",
            "redacted_summary",
            "redacted_note",
            "old_status",
            "new_status",
            "old_priority",
            "new_priority",
        ):
            self.assertIn(marker, self.code)
        for forbidden in (
            "payment_reference",
            "checkout_url",
            "gateway_order_id",
            "provider_payload",
            "raw_customer",
            "password",
            "token",
        ):
            self.assertNotIn(forbidden, self.code)

    def test_case_events_are_database_enforced_append_only(self):
        self.assertIn(
            "references public.platform_support_cases(id) on delete restrict",
            self.code,
        )
        self.assertNotIn(
            "references public.platform_support_cases(id) on delete cascade",
            self.code,
        )
        self.assertIn("before update or delete", self.code)
        self.assertIn("on public.platform_support_case_events", self.code)
        self.assertIn("platform_support_case_events is append-only", self.code)

    def test_draft_does_not_mutate_platform_admin_mappings_or_run_transaction(self):
        self.assertNotIn("update public.platform_admin_users", self.code)
        self.assertNotIn("insert into public.platform_admin_users", self.code)
        self.assertNotIn("delete from public.platform_admin_users", self.code)
        self.assertNotIn("commit", self.code)


if __name__ == "__main__":
    unittest.main()
