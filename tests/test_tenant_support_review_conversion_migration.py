import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "data" / "031_tenant_support_review_conversion.sql"


class TenantSupportReviewConversionMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.normalized = re.sub(r"\s+", " ", cls.sql).lower()

    def test_schema_link_and_duplicate_protection(self):
        for phrase in (
            "add column if not exists converted_platform_support_case_id bigint null",
            "references public.platform_support_cases(id)",
            "on delete restrict",
            "create unique index if not exists ux_tenant_support_requests_converted_case",
            "where converted_platform_support_case_id is not null",
            "tenant_support_requests_converted_case_status_check",
            "converted_platform_support_case_id is null or status = 'converted'",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)

    def test_functions_are_invoker_fixed_path_and_locked(self):
        for signature in (
            "create or replace function public.set_tenant_support_request_status(",
            "create or replace function public.convert_tenant_support_request(",
        ):
            self.assertIn(signature, self.normalized)
        self.assertEqual(self.normalized.count("security invoker"), 2)
        self.assertEqual(self.normalized.count("set search_path to pg_catalog"), 2)
        self.assertEqual(self.normalized.count("from public.tenant_support_requests where id = p_request_id for update"), 2)
        self.assertEqual(self.normalized.count("from public.platform_admin_users where id = p_platform_admin_user_id and is_active = true"), 2)

    def test_status_workflow_is_bounded_and_conversion_is_atomic(self):
        for phrase in (
            "p_status not in ('reviewed', 'closed')",
            "insert into public.tenant_support_request_events",
            "actor_type, created_at",
            "'platform_admin'",
            "insert into public.platform_support_cases",
            "insert into public.platform_support_case_events",
            "status = 'converted'",
            "converted_platform_support_case_id = v_case_id",
            "'platform_admin.tenant_support_request.review'",
            "'platform_admin.tenant_support_request.close'",
            "'platform_admin.tenant_support_request.convert'",
            "insert into public.platform_admin_audit_events",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)

    def test_audit_metadata_is_safe_and_functions_return_safe_fields(self):
        for phrase in (
            "'endpoint'",
            "'http_method'",
            "'outcome'",
            "'old_status'",
            "'new_status'",
            "'converted_platform_support_case_id'",
            "'request_id'",
            "returns jsonb",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)
        audit_blocks = re.findall(
            r"insert into public\.platform_admin_audit_events.*?;", self.normalized
        )
        self.assertEqual(len(audit_blocks), 2)
        for block in audit_blocks:
            for forbidden in (
                "title", "redacted_description", "raw tenant audit",
                "customer content", "secret", "token", "cookie", "payment",
                "provider payload", "full request body",
            ):
                self.assertNotIn(forbidden, block)

    def test_audit_actions_require_future_runtime_allowlist_update(self):
        for action in (
            "platform_admin.tenant_support_request.review",
            "platform_admin.tenant_support_request.close",
            "platform_admin.tenant_support_request.convert",
        ):
            self.assertIn(f"'{action}'", self.normalized)
        self.assertIn("future runtime must add the three tenant-support actions", self.normalized)

    def test_privileges_and_no_mapping_mutation(self):
        for phrase in (
            "revoke all on function public.set_tenant_support_request_status(",
            "revoke all on function public.convert_tenant_support_request(",
            "from public, anon, authenticated, service_role",
            "grant execute on function public.set_tenant_support_request_status(",
            "grant execute on function public.convert_tenant_support_request(",
            ") to service_role",
            "migration draft only",
            "do not apply",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)
        self.assertNotRegex(self.normalized, r"(?:insert into|update|delete from) public\.platform_admin_users")
        self.assertNotIn("alter table public.platform_support_cases", self.normalized)
        self.assertNotIn("alter table public.platform_support_case_events", self.normalized)
        self.assertNotIn("tenant_support_audit_events", self.normalized)


if __name__ == "__main__":
    unittest.main()
