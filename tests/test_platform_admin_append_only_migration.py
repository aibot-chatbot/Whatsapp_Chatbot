"""Static security checks for platform-admin append-only migration 026."""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "data" / "026_enforce_platform_admin_audit_append_only.sql"
INSPECTION = ROOT / "docs" / "platform_admin_phase_4_append_only_inspection.sql"
STAGING_VERIFICATION = (
    ROOT / "docs" / "platform_admin_phase_4_append_only_staging_verification.sql"
)


def read(path):
    return path.read_text(encoding="utf-8", errors="strict")


def without_line_comments(sql):
    return "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )


class TestAppendOnlyMigration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = read(MIGRATION)
        cls.code = without_line_comments(cls.sql)

    def test_dedicated_trigger_function_is_security_invoker(self):
        self.assertIn(
            "CREATE OR REPLACE FUNCTION public.reject_platform_admin_audit_event_mutation()",
            self.code,
        )
        self.assertIn("RETURNS trigger", self.code)
        self.assertIn("SECURITY INVOKER", self.code)
        self.assertNotIn("SECURITY DEFINER", self.code)
        self.assertIn("SET search_path TO pg_catalog", self.code)

    def test_error_is_stable_and_non_sensitive(self):
        self.assertIn("ERRCODE = '55000'", self.code)
        self.assertIn(
            "MESSAGE = 'platform_admin_audit_events is append-only'", self.code
        )
        for prohibited in ("token", "password", "credential", "supabase"):
            self.assertNotIn(prohibited, self.code.lower())

    def test_trigger_rejects_update_and_delete_for_every_row(self):
        trigger = re.search(
            r"CREATE TRIGGER platform_admin_audit_events_reject_mutation(.*?)\n\s*EXECUTE FUNCTION",
            self.code,
            flags=re.S,
        )
        self.assertIsNotNone(trigger)
        body = trigger.group(1)
        self.assertIn("BEFORE UPDATE OR DELETE", body)
        self.assertIn("ON public.platform_admin_audit_events", body)
        self.assertIn("FOR EACH ROW", body)
        self.assertNotIn("INSERT", body)

    def test_trigger_is_not_created_on_mapping_table(self):
        self.assertNotRegex(
            self.code,
            r"CREATE TRIGGER[\s\S]*?ON\s+public\.platform_admin_users",
        )

    def test_migration_is_deterministically_rerunnable(self):
        self.assertIn("CREATE OR REPLACE FUNCTION", self.code)
        self.assertIn(
            "DROP TRIGGER IF EXISTS platform_admin_audit_events_reject_mutation",
            self.code,
        )
        self.assertLess(
            self.code.index("DROP TRIGGER IF EXISTS"),
            self.code.index("CREATE TRIGGER"),
        )

    def test_function_execute_privileges_are_minimized(self):
        revoke = re.search(
            r"REVOKE ALL\s+ON FUNCTION public\.reject_platform_admin_audit_event_mutation\(\)\s+FROM ([^;]+);",
            self.code,
            flags=re.S,
        )
        self.assertIsNotNone(revoke)
        grantees = revoke.group(1)
        for role in ("PUBLIC", "anon", "authenticated", "service_role"):
            self.assertIn(role, grantees)
        self.assertNotIn("GRANT EXECUTE", self.code)

    def test_migration_does_not_broaden_table_or_rls_access(self):
        forbidden = [
            r"\bGRANT\b[\s\S]*?\bON\s+(?:TABLE\s+)?public\.platform_admin_audit_events",
            r"\bALTER TABLE\b",
            r"\bCREATE POLICY\b",
            r"\bDROP POLICY\b",
            r"\bDISABLE ROW LEVEL SECURITY\b",
            r"\bENABLE ROW LEVEL SECURITY\b",
        ]
        for pattern in forbidden:
            self.assertNotRegex(self.code, pattern)

    def test_migration_does_not_mutate_rows_or_add_retention_deletion(self):
        for pattern in (
            r"\bINSERT INTO\s+public\.platform_admin_audit_events",
            r"\bUPDATE\s+public\.platform_admin_audit_events",
            r"\bDELETE FROM\s+public\.platform_admin_audit_events",
            r"\bDROP TABLE\b",
            r"\bTRUNCATE\b",
        ):
            self.assertNotRegex(self.code, pattern)


class TestAppendOnlyInspectionSql(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = read(INSPECTION)
        cls.code = without_line_comments(cls.sql)

    def test_inspection_is_select_only(self):
        statements = [part.strip() for part in self.code.split(";") if part.strip()]
        self.assertTrue(statements)
        for statement in statements:
            self.assertTrue(statement.startswith("SELECT"), statement[:80])

    def test_inspection_covers_function_trigger_and_security_state(self):
        for marker in (
            "pg_get_functiondef",
            "function_owner",
            "security_definer",
            "raw_function_acl",
            "has_function_privilege",
            "pg_get_triggerdef",
            "enabled_state",
            "event_manipulation",
            "table_owner",
            "rls_enabled",
            "has_table_privilege",
            "pg_policies",
        ):
            self.assertIn(marker, self.code)


class TestAppendOnlyStagingVerificationSql(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = read(STAGING_VERIFICATION)
        cls.code = without_line_comments(cls.sql)

    def test_entire_verification_is_rollback_only(self):
        self.assertLess(self.code.index("BEGIN;"), self.code.index("INSERT INTO"))
        self.assertGreater(self.code.index("ROLLBACK;"), self.code.index("DELETE FROM"))
        self.assertNotIn("COMMIT;", self.code)

    def test_uses_existing_inactive_mapping_without_reactivation(self):
        self.assertIn("WHERE platform_admin.is_active = FALSE", self.code)
        self.assertNotIn("is_active = TRUE", self.code)
        self.assertNotRegex(self.code, r"UPDATE\s+public\.platform_admin_users")

    def test_service_role_trigger_path_is_exercised_inside_transaction(self):
        grant_index = self.code.index("GRANT UPDATE, DELETE")
        role_index = self.code.index("SET LOCAL ROLE service_role")
        update_index = self.code.index("UPDATE public.platform_admin_audit_events")
        rollback_index = self.code.index("ROLLBACK;")
        self.assertLess(grant_index, role_index)
        self.assertLess(role_index, update_index)
        self.assertLess(update_index, rollback_index)

    def test_insert_update_delete_and_select_are_all_tested(self):
        self.assertIn("INSERT INTO public.platform_admin_audit_events", self.code)
        self.assertIn("UPDATE public.platform_admin_audit_events", self.code)
        self.assertIn("DELETE FROM public.platform_admin_audit_events", self.code)
        self.assertIn("FROM public.platform_admin_audit_events", self.code)
        self.assertIn("SAVEPOINT before_expected_update_rejection", self.code)
        self.assertIn("SAVEPOINT before_expected_delete_rejection", self.code)

    def test_expected_trigger_errors_are_checked_exactly(self):
        self.assertGreaterEqual(self.code.count("WHEN SQLSTATE '55000'"), 2)
        self.assertGreaterEqual(
            self.code.count("platform_admin_audit_events is append-only"), 2
        )

    def test_test_row_does_not_advance_identity_and_is_checked_after_rollback(self):
        self.assertIn("-9223372036854775807", self.code)
        self.assertNotIn("nextval(", self.code.lower())
        self.assertIn("SELECT NOT EXISTS", self.code)
        self.assertGreater(
            self.code.rindex("SELECT NOT EXISTS"), self.code.index("ROLLBACK;")
        )
        self.assertIn("service_role_can_update_after_rollback", self.code)
        self.assertIn("service_role_can_delete_after_rollback", self.code)


if __name__ == "__main__":
    unittest.main()
