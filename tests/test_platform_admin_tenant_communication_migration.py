import unittest
from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "033_platform_admin_tenant_communication.sql"
)


class PlatformAdminTenantCommunicationMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.normalized = "\n".join(
            line for line in cls.sql.splitlines()
            if not line.lstrip().startswith("--")
        ).lower()

    def test_reuses_support_request_and_case_model_without_parallel_cases(self):
        self.assertIn("create table if not exists public.tenant_support_replies", self.normalized)
        self.assertIn("references public.tenant_support_requests(id)", self.normalized)
        self.assertIn("references public.platform_support_cases(id)", self.normalized)
        self.assertIn("tenant_reply_created", self.normalized)
        self.assertIn("tenant_support_reply_id bigint null", self.normalized)
        self.assertNotIn("create table if not exists public.support_threads", self.normalized)
        self.assertNotIn("create table if not exists public.platform_admin_messages", self.normalized)
        self.assertNotIn("create table if not exists public.support_case_notes", self.normalized)

    def test_public_replies_are_append_only_and_tenant_visible_only(self):
        self.assertIn("author_type in ('platform_admin')", self.normalized)
        self.assertIn("visibility_status = 'visible'", self.normalized)
        self.assertIn("redacted_body text not null", self.normalized)
        self.assertIn("check (char_length(redacted_body) between 1 and 4000)", self.normalized)
        self.assertIn("before update or delete", self.normalized)
        self.assertIn("tenant_support_replies is append-only", self.normalized)
        self.assertNotIn("redacted_note", self.normalized.split("create table if not exists public.tenant_support_replies", 1)[1].split(");", 1)[0])

    def test_rpc_atomically_writes_reply_case_event_audit_and_outbox(self):
        body = self.normalized.split(
            "create or replace function public.create_platform_support_case_reply("
        )[1].split("$function$;", 1)[0]
        self.assertIn("perform public.require_active_platform_admin_mapping", body)
        self.assertIn("from public.platform_support_cases", body)
        self.assertIn("for update", body)
        self.assertIn("from public.tenant_support_requests", body)
        self.assertIn("converted_platform_support_case_id = p_case_id", body)
        self.assertIn("insert into public.tenant_support_replies", body)
        self.assertIn("insert into public.platform_support_case_events", body)
        self.assertIn("insert into public.platform_admin_audit_events", body)
        self.assertIn("insert into public.tenant_support_reply_notifications", body)
        self.assertNotIn("exception when", body)
        self.assertNotIn("commit", body)

    def test_reply_linkage_is_enforced_by_database_constraints(self):
        self.assertIn(
            "constraint tenant_support_requests_id_converted_case_company_key",
            self.normalized,
        )
        self.assertIn(
            "unique (id, converted_platform_support_case_id, company_id)",
            self.normalized,
        )
        self.assertIn("constraint platform_support_cases_id_company_key", self.normalized)
        self.assertIn("unique (id, company_id)", self.normalized)
        self.assertIn("constraint tenant_support_replies_case_company_fkey", self.normalized)
        self.assertIn(
            "foreign key (platform_support_case_id, company_id)\n"
            "            references public.platform_support_cases(id, company_id)",
            self.normalized,
        )
        self.assertIn(
            "constraint tenant_support_replies_request_case_company_fkey",
            self.normalized,
        )
        self.assertIn(
            "foreign key (request_id, platform_support_case_id, company_id)\n"
            "            references public.tenant_support_requests(id, converted_platform_support_case_id, company_id)",
            self.normalized,
        )
        self.assertIn("constraint tenant_support_replies_id_case_key", self.normalized)
        self.assertIn("unique (id, platform_support_case_id)", self.normalized)

    def test_case_events_require_matching_reply_case_linkage(self):
        self.assertIn(
            "constraint platform_support_case_events_reply_case_fkey",
            self.normalized,
        )
        self.assertIn(
            "foreign key (tenant_support_reply_id, case_id)\n"
            "            references public.tenant_support_replies(id, platform_support_case_id)\n"
            "            on delete restrict",
            self.normalized,
        )
        self.assertIn(
            "constraint platform_support_case_events_reply_consistency_check",
            self.normalized,
        )
        self.assertIn(
            "event_type = 'tenant_reply_created'\n"
            "                    and tenant_support_reply_id is not null",
            self.normalized,
        )
        self.assertIn(
            "event_type <> 'tenant_reply_created'\n"
            "                    and tenant_support_reply_id is null",
            self.normalized,
        )
        self.assertNotIn("constraint platform_support_case_events_reply_fkey", self.normalized)
        self.assertNotIn(
            "foreign key (tenant_support_reply_id)\n"
            "            references public.tenant_support_replies(id)",
            self.normalized,
        )

    def test_notification_linkage_and_ownership_fields_are_immutable(self):
        self.assertIn(
            "constraint tenant_support_replies_id_request_case_company_key",
            self.normalized,
        )
        self.assertIn(
            "unique (id, request_id, platform_support_case_id, company_id)",
            self.normalized,
        )
        self.assertIn(
            "constraint tenant_support_reply_notifications_reply_linkage_fkey",
            self.normalized,
        )
        self.assertIn(
            "foreign key (reply_id, request_id, platform_support_case_id, company_id)\n"
            "            references public.tenant_support_replies(id, request_id, platform_support_case_id, company_id)",
            self.normalized,
        )
        self.assertIn(
            "create or replace function public.reject_tenant_support_reply_notification_ownership_change()",
            self.normalized,
        )
        for immutable_field in (
            "old.reply_id is distinct from new.reply_id",
            "old.request_id is distinct from new.request_id",
            "old.platform_support_case_id is distinct from new.platform_support_case_id",
            "old.company_id is distinct from new.company_id",
            "old.channel is distinct from new.channel",
            "old.idempotency_key is distinct from new.idempotency_key",
        ):
            self.assertIn(immutable_field, self.normalized)
        self.assertIn("before update\n    on public.tenant_support_reply_notifications", self.normalized)
        self.assertIn("tenant_support_reply_notifications ownership fields are immutable", self.normalized)
        self.assertIn("security invoker", self.normalized)
        self.assertIn("set search_path to pg_catalog", self.normalized)

    def test_notification_outbox_tracks_pending_delivery_without_provider_payload(self):
        self.assertIn("create table if not exists public.tenant_support_reply_notifications", self.normalized)
        self.assertIn("channel in ('in_app')", self.normalized)
        self.assertIn("status in ('pending', 'sent', 'failed')", self.normalized)
        self.assertIn("idempotency_key text not null", self.normalized)
        self.assertIn("ux_tenant_support_reply_notifications_idempotency", self.normalized)
        for forbidden in ("provider_payload", "email_body", "authorization", "cookie"):
            self.assertNotIn(forbidden, self.normalized)

    def test_rls_and_least_privilege_grants_are_backend_only(self):
        for table in (
            "public.tenant_support_replies",
            "public.tenant_support_reply_notifications",
        ):
            self.assertIn(f"alter table {table} enable row level security", self.normalized)
            self.assertIn(
                f"revoke all on {table}\n    from public, anon, authenticated, service_role",
                self.normalized,
            )
        self.assertIn("grant select, insert on public.tenant_support_replies\n    to service_role", self.normalized)
        self.assertIn(
            "grant select, insert, update on public.tenant_support_reply_notifications\n    to service_role",
            self.normalized,
        )
        for forbidden in (
            "grant delete",
            "grant truncate",
            "grant trigger",
            "grant references",
            "grant update on public.tenant_support_replies",
            "grant all on public.tenant_support_replies",
        ):
            self.assertNotIn(forbidden, self.normalized)
        self.assertIn(
            "revoke all on function public.create_platform_support_case_reply(bigint, bigint, text)\n    from public, anon, authenticated, service_role",
            self.normalized,
        )
        self.assertIn(
            "revoke all on function public.reject_tenant_support_reply_notification_ownership_change()\n    from public, anon, authenticated, service_role",
            self.normalized,
        )
        self.assertIn(
            "grant execute on function public.create_platform_support_case_reply(bigint, bigint, text)\n    to service_role",
            self.normalized,
        )


if __name__ == "__main__":
    unittest.main()
