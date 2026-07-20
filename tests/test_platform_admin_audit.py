import unittest
import math
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.database import platform_admin_repository
from app.services import platform_admin_service


class PlatformAdminAuditTests(unittest.TestCase):
    def test_valid_event_is_inserted(self):
        query = MagicMock()
        query.insert.return_value = query
        query.execute.return_value = SimpleNamespace(data=[{"id": 1}])
        with patch.object(platform_admin_repository.supabase, "table", return_value=query):
            event = platform_admin_repository.insert_platform_admin_audit_event(
                2, "platform_admin.company.read", "company", "9",
                {"outcome": "success", "endpoint": "/fixed", "http_method": "GET"},
            )
        self.assertEqual(event["id"], 1)

    def test_metadata_must_be_object_allowlisted_and_free_of_prohibited_keys(self):
        base = (2, "platform_admin.company.read", "company", "9")
        for invalid in (
            None,
            [],
            {"unknown": True},
            {"message": "secret"},
            {"outcome": {"nested": {"access_token": "secret"}}},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                platform_admin_repository.validate_audit_event(*base, invalid)

    def test_non_finite_json_values_are_rejected(self):
        base = (2, "platform_admin.company.read", "company", "9")
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                platform_admin_repository.validate_audit_event(
                    *base, {"limit": value}
                )

    def test_blank_and_oversized_resource_ids_are_rejected(self):
        base = (2, "platform_admin.company.read", "company")
        for resource_id in ("", "   ", "x" * 256):
            with self.subTest(resource_id=resource_id), self.assertRaises(ValueError):
                platform_admin_repository.validate_audit_event(
                    *base, resource_id, {}
                )

    def test_actor_action_resource_and_size_are_validated(self):
        for actor_id in (True, 0, -1, "2", None):
            with self.subTest(actor_id=actor_id), self.assertRaises(ValueError):
                platform_admin_repository.validate_audit_event(
                    actor_id, "platform_admin.company.read", "company", "1", {}
                )
        with self.assertRaises(ValueError):
            platform_admin_repository.validate_audit_event(1, "", "company", "1", {})
        with self.assertRaises(ValueError):
            platform_admin_repository.validate_audit_event(
                1, "platform_admin.company.read", "", "1", {}
            )
        with self.assertRaises(ValueError):
            platform_admin_repository.validate_audit_event(
                1, "platform_admin.company.read", "company", "1",
                {"endpoint": "x" * 8200},
            )

    def test_audit_happens_before_successful_service_return(self):
        calls = []
        with patch.object(
            platform_company_repository := platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            side_effect=lambda company_id: calls.append("read") or {"id": company_id},
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=lambda *args, **kwargs: calls.append("audit") or {"id": 1},
        ):
            result = platform_admin_service.get_company_detail(5, 2)
        calls.append("return")
        self.assertEqual(result["id"], 5)
        self.assertEqual(calls, ["read", "audit", "return"])

    def test_audit_failure_withholds_data(self):
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin", return_value={"id": 5, "secret": "not returned"},
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event", side_effect=RuntimeError("down"),
        ):
            with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                platform_admin_service.get_company_detail(5, 2)
        self.assertEqual(raised.exception.code, "platform_admin_audit_unavailable")

    def test_missing_company_is_audited_before_not_found_is_returned(self):
        calls = []
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            side_effect=lambda company_id: calls.append("read") or None,
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            side_effect=lambda *args, **kwargs: calls.append("audit") or {"id": 1},
        ) as audit:
            with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                platform_admin_service.get_company_detail(77, 2)
            calls.append("not_found")
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.code, "company_not_found")
        self.assertEqual(calls, ["read", "audit", "not_found"])
        self.assertEqual(audit.call_args.args[4]["outcome"], "not_found")

    def test_invalid_service_actor_ids_are_rejected_before_tenant_reads(self):
        for actor_id in (True, 0, -1, "2", None):
            with self.subTest(actor_id=actor_id), patch.object(
                platform_admin_service.platform_company_repository,
                "get_company_for_platform_admin",
            ) as company_lookup:
                with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                    platform_admin_service.get_company_detail(5, actor_id)
                self.assertEqual(raised.exception.code, "platform_admin_context_invalid")
                company_lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
