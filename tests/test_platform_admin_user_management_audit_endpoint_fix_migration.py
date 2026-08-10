import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "data" / "035_fix_platform_admin_user_management_audit_endpoints.sql"
DATA = ROOT / "data"


def read(path):
    return path.read_text(encoding="utf-8")


class PlatformAdminUserManagementAuditEndpointFixMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = read(MIGRATION)
        cls.normalized = re.sub(r"\s+", " ", cls.sql.lower())

    def _function_body(self, function_name):
        match = re.search(
            rf"create or replace function public\.{function_name}\(.*?\n\$function\$;",
            self.sql,
            flags=re.S | re.I,
        )
        self.assertIsNotNone(match, f"missing {function_name}")
        return match.group(0).lower()

    def test_replaces_both_phase_4_rpcs(self):
        self.assertIn(
            "create or replace function public.create_platform_admin_user_mapping(",
            self.sql.lower(),
        )
        self.assertIn(
            "create or replace function public.set_platform_admin_user_active(",
            self.sql.lower(),
        )

    def test_correct_endpoint_metadata_is_present_and_shortened_paths_are_absent(self):
        self.assertIn("'/api/platform-admin/platform-admin-users'", self.sql)
        self.assertIn(
            "'/api/platform-admin/platform-admin-users/<platform_admin_user_id>/active'",
            self.sql,
        )
        self.assertNotIn("'/api/platform-admin/users'", self.sql)
        self.assertNotIn(
            "'/api/platform-admin/users/<platform_admin_user_id>/active'",
            self.sql,
        )

    def test_security_mode_search_path_and_execute_acl_are_preserved(self):
        for function_name in (
            "create_platform_admin_user_mapping",
            "set_platform_admin_user_active",
        ):
            body = self._function_body(function_name)
            self.assertIn("security invoker", body)
            self.assertIn("set search_path to pg_catalog", body)

        self.assertIn(
            "revoke all on function public.create_platform_admin_user_mapping(bigint, bigint) from public, anon, authenticated, service_role",
            self.normalized,
        )
        self.assertIn(
            "revoke all on function public.set_platform_admin_user_active(bigint, bigint, boolean) from public, anon, authenticated, service_role",
            self.normalized,
        )
        self.assertIn(
            "grant execute on function public.create_platform_admin_user_mapping(bigint, bigint) to service_role",
            self.normalized,
        )
        self.assertIn(
            "grant execute on function public.set_platform_admin_user_active(bigint, bigint, boolean) to service_role",
            self.normalized,
        )
        self.assertNotRegex(self.normalized, r"grant execute .* to (anon|authenticated)\b")

    def test_business_and_security_rules_remain_present(self):
        for phrase in [
            "invalid platform-admin actor id",
            "invalid target user id",
            "invalid target platform-admin user id",
            "invalid active state",
            "lock table public.platform_admin_users in share row exclusive mode",
            "require_active_platform_admin_mapping",
            "for update",
            "target user not found",
            "target user must be active",
            "target user must belong to a protected company",
            "from public.platform_admin_protected_companies",
            "platform-admin mapping already exists",
            "self-deactivation is not allowed",
            "platform-admin mapping active state is unchanged",
            "at least one active platform-admin mapping is required",
            "insert into public.platform_admin_users",
            "update public.platform_admin_users",
            "insert into public.platform_admin_audit_events",
            "platform_admin.user.create",
            "platform_admin.user.activate",
            "platform_admin.user.deactivate",
            "created_by_user_id",
            "v_actor.user_id",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)

    def test_future_migrations_do_not_reintroduce_shortened_phase_4_endpoints(self):
        wrong_endpoint_literals = {
            "'/api/platform-admin/users'",
            "'/api/platform-admin/users/<platform_admin_user_id>/active'",
        }
        offenders = []
        for path in DATA.glob("*.sql"):
            match = re.match(r"^(\d+)_", path.name)
            if not match or int(match.group(1)) < 35:
                continue
            source = read(path)
            for literal in wrong_endpoint_literals:
                if literal in source:
                    offenders.append(f"{path.name}:{literal}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
