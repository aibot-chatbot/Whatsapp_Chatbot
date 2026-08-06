import unittest
from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "032_platform_support_case_operations.sql"
)


class PlatformAdminSupportCaseOperationsMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.normalized = "\n".join(
            line for line in cls.sql.splitlines()
            if not line.lstrip().startswith("--")
        ).lower()

    def test_extends_existing_tables_without_parallel_case_model(self):
        self.assertIn("alter table public.platform_support_case_events", self.normalized)
        self.assertIn("old_assigned_platform_admin_user_id bigint null", self.normalized)
        self.assertIn("new_assigned_platform_admin_user_id bigint null", self.normalized)
        self.assertIn("waiting_for_tenant", self.normalized)
        self.assertIn("assignment_changed", self.normalized)
        self.assertNotIn("create table public.platform_support_case_notes", self.normalized)
        self.assertNotIn("create table if not exists public.platform_support_case_notes", self.normalized)
        self.assertNotIn("create table public.platform_admin_support_cases", self.normalized)

    def test_assignment_fields_reference_platform_admin_mappings(self):
        self.assertIn(
            "foreign key (old_assigned_platform_admin_user_id)",
            self.normalized,
        )
        self.assertIn(
            "foreign key (new_assigned_platform_admin_user_id)",
            self.normalized,
        )
        self.assertIn("references public.platform_admin_users(id)", self.normalized)
        self.assertIn("from public.platform_admin_users", self.normalized)
        self.assertIn("where id = p_platform_admin_user_id", self.normalized)
        self.assertIn("and is_active = true", self.normalized)
        self.assertIn("for update", self.normalized)
        self.assertNotIn("users.role", self.normalized)

    def test_active_mapping_validation_locks_row_until_rpc_transaction_finishes(self):
        function_body = self.normalized.split(
            "create or replace function public.require_active_platform_admin_mapping("
        )[1].split("$function$;", 1)[0]
        self.assertIn("perform 1", function_body)
        self.assertIn("from public.platform_admin_users", function_body)
        self.assertIn("where id = p_platform_admin_user_id", function_body)
        self.assertIn("and is_active = true", function_body)
        self.assertIn("for update", function_body)
        self.assertIn("if not found then", function_body)

    def test_operation_rpcs_are_atomic_and_audited(self):
        for function_name in (
            "assign_platform_support_case",
            "set_platform_support_case_status",
            "set_platform_support_case_priority",
            "add_platform_support_case_note",
        ):
            self.assertIn(f"create or replace function public.{function_name}(", self.normalized)
            self.assertIn(f"grant execute on function public.{function_name}", self.normalized)
        self.assertGreaterEqual(self.normalized.count("from public.platform_support_cases"), 4)
        self.assertGreaterEqual(self.normalized.count("for update"), 5)
        self.assertGreaterEqual(self.normalized.count("insert into public.platform_support_case_events"), 4)
        self.assertGreaterEqual(self.normalized.count("insert into public.platform_admin_audit_events"), 4)
        self.assertIn("support case transition is not allowed", self.normalized)
        self.assertIn("support case status is unchanged", self.normalized)
        self.assertIn("support case priority is unchanged", self.normalized)
        self.assertIn("support case assignee is unchanged", self.normalized)

    def test_closed_at_set_on_close_and_cleared_on_reopen(self):
        self.assertIn(
            "closed_at = case when p_status = 'closed' then v_now else null end",
            self.normalized,
        )
        self.assertIn("or (v_case.status = 'resolved' and p_status in ('closed', 'in_progress'))", self.normalized)
        self.assertIn("or (v_case.status = 'closed' and p_status = 'in_progress')", self.normalized)

    def test_event_or_audit_insert_failure_rolls_back_whole_rpc(self):
        for function_name in (
            "assign_platform_support_case",
            "set_platform_support_case_status",
            "set_platform_support_case_priority",
            "add_platform_support_case_note",
        ):
            body = self.normalized.split(
                f"create or replace function public.{function_name}("
            )[1].split("$function$;", 1)[0]
            self.assertIn("update public.platform_support_cases", body)
            self.assertIn("insert into public.platform_support_case_events", body)
            self.assertIn("insert into public.platform_admin_audit_events", body)
            self.assertNotIn("exception when", body)
            self.assertNotIn("commit", body)

    def test_rpc_privileges_are_backend_only(self):
        for function_name in (
            "assign_platform_support_case(bigint, bigint, bigint)",
            "set_platform_support_case_status(bigint, bigint, text)",
            "set_platform_support_case_priority(bigint, bigint, text)",
            "add_platform_support_case_note(bigint, bigint, text)",
        ):
            self.assertIn(
                f"revoke all on function public.{function_name}\n    from public, anon, authenticated, service_role",
                self.normalized,
            )
            self.assertIn(
                f"grant execute on function public.{function_name}\n    to service_role",
                self.normalized,
            )

    def test_table_and_sequence_privileges_are_reset_to_least_privilege(self):
        for object_name in (
            "public.platform_support_cases",
            "public.platform_support_case_events",
        ):
            self.assertIn(
                f"revoke all on {object_name}\n    from public, anon, authenticated, service_role",
                self.normalized,
            )
        for sequence_name in (
            "public.platform_support_cases_id_seq",
            "public.platform_support_case_events_id_seq",
        ):
            self.assertIn(
                f"revoke all on sequence {sequence_name}\n    from public, anon, authenticated, service_role",
                self.normalized,
            )
            self.assertIn(
                f"grant usage on sequence {sequence_name}\n    to service_role",
                self.normalized,
            )
            self.assertNotIn(f"grant select on sequence {sequence_name}", self.normalized)

        self.assertIn(
            "grant select, insert, update on public.platform_support_cases\n    to service_role",
            self.normalized,
        )
        self.assertIn(
            "grant select, insert on public.platform_support_case_events\n    to service_role",
            self.normalized,
        )
        for forbidden in (
            "grant delete",
            "grant truncate",
            "grant trigger",
            "grant references",
            "grant update on public.platform_support_case_events",
            "grant all on public.platform_support_cases",
            "grant all on public.platform_support_case_events",
        ):
            self.assertNotIn(forbidden, self.normalized)

    def test_does_not_modify_platform_admin_mappings_or_tenant_data_directly(self):
        self.assertNotRegex(self.normalized, r"(?:insert into|update|delete from) public\.platform_admin_users")
        self.assertNotRegex(self.normalized, r"(?:insert into|update|delete from) public\.users")
        self.assertNotRegex(self.normalized, r"(?:insert into|update|delete from) public\.tenant_support_requests")


if __name__ == "__main__":
    unittest.main()
