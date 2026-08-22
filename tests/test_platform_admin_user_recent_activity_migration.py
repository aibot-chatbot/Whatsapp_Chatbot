import unittest
from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "044_platform_admin_user_recent_activity_batch.sql"
)


class PlatformAdminUserRecentActivityMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.normalized = "\n".join(
            line for line in cls.sql.splitlines()
            if not line.lstrip().startswith("--")
        ).lower()
        cls.body = cls.normalized.split(
            "create or replace function public.get_latest_platform_admin_activity("
        )[1].split("$function$;", 1)[0]

    def test_rpc_returns_only_latest_activity_for_requested_mapping_ids(self):
        self.assertIn("returns table", self.body)
        self.assertIn("platform_admin_user_id bigint", self.body)
        self.assertIn("recent_platform_admin_activity_at timestamptz", self.body)
        self.assertIn("pg_catalog.unnest(p_platform_admin_user_ids)", self.body)
        self.assertIn("select distinct supplied.platform_admin_user_id", self.body)
        self.assertIn("left join public.platform_admin_audit_events", self.body)
        self.assertIn("events.platform_admin_user_id = requested.platform_admin_user_id", self.body)
        self.assertIn("pg_catalog.max(events.created_at)", self.body)
        self.assertIn("group by requested.platform_admin_user_id", self.body)
        self.assertNotIn("events.metadata", self.body)
        self.assertNotIn("events.action", self.body)
        self.assertNotIn("events.resource_id", self.body)

    def test_rpc_does_not_filter_by_active_state_or_tenant_role(self):
        self.assertNotIn("is_active", self.body)
        self.assertNotIn("users.role", self.body)
        self.assertNotIn("public.users", self.body)

    def test_rpc_privileges_are_backend_only(self):
        self.assertIn(
            "revoke all on function public.get_latest_platform_admin_activity(bigint[])\n"
            "    from public, anon, authenticated, service_role",
            self.normalized,
        )
        self.assertIn(
            "grant execute on function public.get_latest_platform_admin_activity(bigint[])\n"
            "    to service_role",
            self.normalized,
        )


if __name__ == "__main__":
    unittest.main()
