import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flask import Flask

from app.database import platform_admin_repository
from app.routes.platform_admin_routes import platform_admin_bp
from app.services import platform_admin_service


def query(data=None, *, count=0):
    mock = MagicMock()
    for method in ("select", "eq", "in_", "order", "range", "limit"):
        getattr(mock, method).return_value = mock
    mock.execute.return_value = SimpleNamespace(data=data or [], count=count)
    return mock


class PlatformAdminUserRepositoryTests(unittest.TestCase):
    def test_list_uses_safe_projection_creator_fallback_and_recent_audit_activity(self):
        mappings = query([
            {
                "id": 3,
                "user_id": 7,
                "is_active": True,
                "created_at": "2026-08-01T00:00:00+00:00",
                "updated_at": "2026-08-02T00:00:00+00:00",
                "created_by_user_id": None,
            },
            {
                "id": 4,
                "user_id": 8,
                "is_active": False,
                "created_at": "2026-08-03T00:00:00+00:00",
                "updated_at": "2026-08-04T00:00:00+00:00",
                "created_by_user_id": 7,
            },
        ], count=2)
        users = query([
            {"id": 7, "email": "operator@example.test", "full_name": "Operator", "status": "active"},
            {"id": 8, "email": "second@example.test", "full_name": "Second", "status": "inactive"},
        ])
        activity_rpc = MagicMock(return_value=MagicMock(execute=MagicMock(
            return_value=SimpleNamespace(data=[
                {
                    "platform_admin_user_id": 3,
                    "recent_platform_admin_activity_at": "2026-08-05T12:00:00+00:00",
                },
                {
                    "platform_admin_user_id": 4,
                    "recent_platform_admin_activity_at": None,
                },
            ])
        )))

        with patch.object(
            platform_admin_repository.supabase,
            "table",
            side_effect=[mappings, users],
        ) as table, patch.object(platform_admin_repository.supabase, "rpc", activity_rpc):
            rows, total = platform_admin_repository.list_platform_admin_users_for_platform_admin(
                limit=25, offset=0,
            )

        self.assertEqual(total, 2)
        self.assertEqual(table.call_args_list[0].args, ("platform_admin_users",))
        self.assertEqual(table.call_args_list[1].args, ("users",))
        self.assertEqual(len(table.call_args_list), 2)
        activity_rpc.assert_called_once_with(
            "get_latest_platform_admin_activity",
            {"p_platform_admin_user_ids": [3, 4]},
        )
        mappings.select.assert_called_once_with(
            platform_admin_repository.PLATFORM_ADMIN_USER_SAFE_FIELDS, count="exact"
        )
        users.select.assert_called_once_with(
            platform_admin_repository.PLATFORM_ADMIN_USER_IDENTITY_FIELDS
        )
        self.assertEqual(rows[0]["platform_admin_user_id"], 3)
        self.assertEqual(rows[0]["user_email"], "operator@example.test")
        self.assertIsNone(rows[0]["creator_email"])
        self.assertEqual(rows[0]["recent_platform_admin_activity_at"], "2026-08-05T12:00:00+00:00")
        self.assertEqual(rows[1]["creator_user_id"], 7)
        self.assertEqual(rows[1]["creator_full_name"], "Operator")
        self.assertNotIn("password_hash", rows[0])
        self.assertNotIn("role", rows[0])

    def test_detail_rejects_boolean_id_and_projects_safe_fields(self):
        with self.assertRaises(ValueError):
            platform_admin_repository.get_platform_admin_user_for_platform_admin(True)

        mapping = query([{
            "id": 3,
            "user_id": 7,
            "is_active": True,
            "created_at": "2026-08-01T00:00:00+00:00",
            "updated_at": "2026-08-02T00:00:00+00:00",
            "created_by_user_id": None,
        }])
        users = query([{"id": 7, "email": "operator@example.test", "full_name": "Operator", "status": "active"}])
        activity_rpc = MagicMock(return_value=MagicMock(execute=MagicMock(
            return_value=SimpleNamespace(data=[{
                "platform_admin_user_id": 3,
                "recent_platform_admin_activity_at": None,
            }])
        )))
        with patch.object(
            platform_admin_repository.supabase,
            "table",
            side_effect=[mapping, users],
        ), patch.object(platform_admin_repository.supabase, "rpc", activity_rpc):
            row = platform_admin_repository.get_platform_admin_user_for_platform_admin(3)
        self.assertEqual(row["platform_admin_user_id"], 3)
        self.assertEqual(row["user_status"], "active")
        self.assertNotIn("metadata", row)

    def test_recent_activity_batch_deduplicates_ids_and_preserves_missing_activity(self):
        activity_rpc = MagicMock(return_value=MagicMock(execute=MagicMock(
            return_value=SimpleNamespace(data=[
                {
                    "platform_admin_user_id": 1,
                    "recent_platform_admin_activity_at": "2026-08-03T00:00:00+00:00",
                },
                {
                    "platform_admin_user_id": 2,
                    "recent_platform_admin_activity_at": "2026-08-02T00:00:00+00:00",
                },
                {
                    "platform_admin_user_id": 3,
                    "recent_platform_admin_activity_at": None,
                },
            ])
        )))
        with patch.object(platform_admin_repository.supabase, "rpc", activity_rpc):
            result = platform_admin_repository._latest_activity_by_platform_admin_ids(
                [3, 1, 2, 1, None, True, -1]
            )
        activity_rpc.assert_called_once_with(
            "get_latest_platform_admin_activity",
            {"p_platform_admin_user_ids": [1, 2, 3]},
        )
        self.assertEqual(result, {
            1: "2026-08-03T00:00:00+00:00",
            2: "2026-08-02T00:00:00+00:00",
            3: None,
        })

    def test_recent_activity_batch_empty_input_skips_rpc(self):
        with patch.object(platform_admin_repository.supabase, "rpc") as rpc:
            result = platform_admin_repository._latest_activity_by_platform_admin_ids([None, True, 0])
        rpc.assert_not_called()
        self.assertEqual(result, {})

    def test_recent_activity_batch_rejects_malformed_result(self):
        malformed_cases = [
            "not-a-list",
            [{"platform_admin_user_id": 99, "recent_platform_admin_activity_at": None}],
            [{"platform_admin_user_id": 1, "recent_platform_admin_activity_at": 123}],
            [None],
        ]
        for data in malformed_cases:
            with self.subTest(data=data), patch.object(
                platform_admin_repository.supabase,
                "rpc",
                return_value=MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=data))),
            ):
                with self.assertRaises(RuntimeError):
                    platform_admin_repository._latest_activity_by_platform_admin_ids([1])

    def test_recent_activity_batch_rejects_missing_requested_mapping(self):
        data = [
            {
                "platform_admin_user_id": 1,
                "recent_platform_admin_activity_at": "2026-08-01T00:00:00+00:00",
            },
            {
                "platform_admin_user_id": 3,
                "recent_platform_admin_activity_at": None,
            },
        ]
        with patch.object(
            platform_admin_repository.supabase,
            "rpc",
            return_value=MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=data))),
        ):
            with self.assertRaises(RuntimeError):
                platform_admin_repository._latest_activity_by_platform_admin_ids([1, 2, 3])

    def test_recent_activity_batch_rejects_duplicate_mapping_rows(self):
        data = [
            {
                "platform_admin_user_id": 1,
                "recent_platform_admin_activity_at": "2026-08-01T00:00:00+00:00",
            },
            {
                "platform_admin_user_id": 1,
                "recent_platform_admin_activity_at": "2026-08-02T00:00:00+00:00",
            },
        ]
        with patch.object(
            platform_admin_repository.supabase,
            "rpc",
            return_value=MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=data))),
        ):
            with self.assertRaises(RuntimeError):
                platform_admin_repository._latest_activity_by_platform_admin_ids([1])

    def test_recent_activity_batch_rejects_invalid_timestamp_strings(self):
        for timestamp in ("", "not-a-date", "2026-08-01T00:00:00"):
            with self.subTest(timestamp=timestamp), patch.object(
                platform_admin_repository.supabase,
                "rpc",
                return_value=MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=[{
                    "platform_admin_user_id": 1,
                    "recent_platform_admin_activity_at": timestamp,
                }]))),
            ):
                with self.assertRaises(RuntimeError):
                    platform_admin_repository._latest_activity_by_platform_admin_ids([1])

    def test_recent_activity_batch_preserves_valid_timezone_timestamp(self):
        timestamp = "2026-08-01T00:00:00Z"
        with patch.object(
            platform_admin_repository.supabase,
            "rpc",
            return_value=MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=[{
                "platform_admin_user_id": 1,
                "recent_platform_admin_activity_at": timestamp,
            }]))),
        ):
            result = platform_admin_repository._latest_activity_by_platform_admin_ids([1])
        self.assertEqual(result, {1: timestamp})

    def _create_rpc_result(self):
        return {
            "platform_admin_user": {
                "id": 6,
                "user_id": 8,
                "is_active": True,
                "created_by_user_id": 7,
            },
            "audit_event": {
                "id": 100,
                "action": "platform_admin.user.create",
                "resource_type": "platform_admin_users",
                "resource_id": "6",
            },
        }

    def _active_rpc_result(self, *, is_active):
        return {
            "platform_admin_user": {
                "id": 6,
                "user_id": 8,
                "is_active": is_active,
            },
            "audit_event": {
                "id": 101,
                "action": "platform_admin.user.activate" if is_active else "platform_admin.user.deactivate",
                "resource_type": "platform_admin_users",
                "resource_id": "6",
            },
        }

    def test_create_rpc_uses_expected_function_and_validates_result(self):
        rpc = MagicMock(return_value=MagicMock(execute=MagicMock(
            return_value=SimpleNamespace(data=self._create_rpc_result())
        )))
        with patch.object(platform_admin_repository.supabase, "rpc", rpc):
            result = platform_admin_repository.create_platform_admin_user_mapping_for_platform_admin(3, 7, 8)
        rpc.assert_called_once_with(
            "create_platform_admin_user_mapping",
            {"p_actor_platform_admin_user_id": 3, "p_target_user_id": 8},
        )
        self.assertEqual(result["platform_admin_user"]["id"], 6)

    def test_create_rpc_rejects_malformed_and_mismatched_results(self):
        cases = [
            ("platform_admin_user", None),
            ("audit_event", None),
            ("platform_admin_user.id", True),
            ("platform_admin_user.id", 0),
            ("platform_admin_user.user_id", 9),
            ("platform_admin_user.is_active", False),
            ("platform_admin_user.created_by_user_id", None),
            ("platform_admin_user.created_by_user_id", True),
            ("platform_admin_user.created_by_user_id", 0),
            ("platform_admin_user.created_by_user_id", 99),
            ("audit_event.id", True),
            ("audit_event.action", "platform_admin.user.activate"),
            ("audit_event.resource_type", "users"),
            ("audit_event.resource_id", "7"),
        ]
        for dotted, value in cases:
            result = self._create_rpc_result()
            parts = dotted.split(".")
            if len(parts) == 1:
                result[parts[0]] = value
            else:
                result[parts[0]][parts[1]] = value
            rpc = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=result))))
            with self.subTest(dotted=dotted), patch.object(platform_admin_repository.supabase, "rpc", rpc):
                with self.assertRaises(RuntimeError):
                    platform_admin_repository.create_platform_admin_user_mapping_for_platform_admin(3, 7, 8)

    def test_active_rpc_uses_expected_function_and_validates_result(self):
        rpc = MagicMock(return_value=MagicMock(execute=MagicMock(
            return_value=SimpleNamespace(data=self._active_rpc_result(is_active=False))
        )))
        with patch.object(platform_admin_repository.supabase, "rpc", rpc):
            result = platform_admin_repository.set_platform_admin_user_active_for_platform_admin(3, 6, False)
        rpc.assert_called_once_with(
            "set_platform_admin_user_active",
            {
                "p_actor_platform_admin_user_id": 3,
                "p_target_platform_admin_user_id": 6,
                "p_is_active": False,
            },
        )
        self.assertFalse(result["platform_admin_user"]["is_active"])

    def test_active_rpc_rejects_malformed_and_mismatched_results(self):
        cases = [
            ("platform_admin_user", None),
            ("audit_event", None),
            ("platform_admin_user.id", 7),
            ("platform_admin_user.user_id", 0),
            ("platform_admin_user.is_active", True),
            ("audit_event.id", 0),
            ("audit_event.action", "platform_admin.user.activate"),
            ("audit_event.resource_type", "users"),
            ("audit_event.resource_id", "7"),
        ]
        for dotted, value in cases:
            result = self._active_rpc_result(is_active=False)
            parts = dotted.split(".")
            if len(parts) == 1:
                result[parts[0]] = value
            else:
                result[parts[0]][parts[1]] = value
            rpc = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=result))))
            with self.subTest(dotted=dotted), patch.object(platform_admin_repository.supabase, "rpc", rpc):
                with self.assertRaises(RuntimeError):
                    platform_admin_repository.set_platform_admin_user_active_for_platform_admin(3, 6, False)

    def test_lifecycle_methods_do_not_directly_mutate_mapping_table(self):
        create_source = inspect.getsource(
            platform_admin_repository.create_platform_admin_user_mapping_for_platform_admin
        ).casefold()
        active_source = inspect.getsource(
            platform_admin_repository.set_platform_admin_user_active_for_platform_admin
        ).casefold()
        combined = create_source + active_source
        self.assertIn('supabase.rpc(', combined)
        self.assertNotIn('.table("platform_admin_users").insert', combined)
        self.assertNotIn('.table("platform_admin_users").update', combined)
        self.assertNotIn('.table("platform_admin_users").delete', combined)


class PlatformAdminUserServiceTests(unittest.TestCase):
    def test_create_uses_actor_mapping_from_trusted_context_and_rejects_unsafe_fields(self):
        with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
            platform_admin_service.create_platform_admin_user({"user_id": 8, "company_id": 29}, {"id": 3, "user_id": 7})
        self.assertEqual(raised.exception.code, "invalid_request")

        with patch.object(
            platform_admin_service.platform_admin_repository,
            "create_platform_admin_user_mapping_for_platform_admin",
            return_value={
                "platform_admin_user": {"id": 6, "user_id": 8, "is_active": True, "created_by_user_id": 7},
                "audit_event": {"id": 100},
            },
        ) as repo, patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
        ) as audit:
            result = platform_admin_service.create_platform_admin_user(
                {"user_id": 8}, {"id": 3, "user_id": 7},
            )
        repo.assert_called_once_with(3, 7, 8)
        audit.assert_not_called()
        self.assertEqual(result["platform_admin_user"]["platform_admin_user_id"], 6)

    def test_create_and_active_errors_are_sanitized(self):
        cases = [
            ("Target user not found", 404, "target_user_not_found"),
            ("Target user must be active", 400, "target_user_inactive"),
            ("Target user must belong to a protected company", 400, "target_user_not_protected"),
            ("Platform-admin mapping already exists", 400, "platform_admin_mapping_exists"),
            ("Active platform-admin mapping is required", 403, "platform_admin_access_denied"),
            ("Supabase password_hash secret", 503, "platform_admin_data_unavailable"),
        ]
        for message, status, code in cases:
            with self.subTest(message=message), patch.object(
                platform_admin_service.platform_admin_repository,
                "create_platform_admin_user_mapping_for_platform_admin",
                side_effect=RuntimeError(message),
            ):
                with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                    platform_admin_service.create_platform_admin_user({"user_id": 8}, {"id": 3, "user_id": 7})
                self.assertEqual(raised.exception.status_code, status)
                self.assertEqual(raised.exception.code, code)
                self.assertNotIn("Supabase", raised.exception.message)
                self.assertNotIn("password_hash", raised.exception.message)

        active_cases = [
            ("Platform-admin mapping not found", 404, "platform_admin_user_not_found"),
            ("Platform-admin mapping active state is unchanged", 400, "no_change"),
            ("Self-deactivation is not allowed", 400, "self_deactivation_not_allowed"),
            ("At least one active platform-admin mapping is required", 400, "final_active_platform_admin"),
        ]
        for message, status, code in active_cases:
            with self.subTest(message=message), patch.object(
                platform_admin_service.platform_admin_repository,
                "set_platform_admin_user_active_for_platform_admin",
                side_effect=RuntimeError(message),
            ):
                with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                    platform_admin_service.set_platform_admin_user_active(6, {"is_active": False}, 3)
                self.assertEqual(raised.exception.status_code, status)
                self.assertEqual(raised.exception.code, code)

    def test_set_active_rejects_invalid_payload_and_does_not_double_audit_mutations(self):
        for payload, code in [
            ({}, "invalid_is_active"),
            ({"is_active": "false"}, "invalid_is_active"),
            ({"is_active": False, "actor_platform_admin_user_id": 3}, "invalid_request"),
        ]:
            with self.subTest(payload=payload):
                with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                    platform_admin_service.set_platform_admin_user_active(6, payload, 3)
                self.assertEqual(raised.exception.code, code)

        with patch.object(
            platform_admin_service.platform_admin_repository,
            "set_platform_admin_user_active_for_platform_admin",
            return_value={
                "platform_admin_user": {"id": 6, "user_id": 8, "is_active": False},
                "audit_event": {"id": 101},
            },
        ) as repo, patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
        ) as audit:
            result = platform_admin_service.set_platform_admin_user_active(6, {"is_active": False}, 3)
        repo.assert_called_once_with(3, 6, False)
        audit.assert_not_called()
        self.assertFalse(result["platform_admin_user"]["is_active"])


class PlatformAdminUserRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(platform_admin_bp)
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer token"}
        self.patches = [
            patch("app.decorators.auth_decorator.get_jwt_secret", return_value="secret"),
            patch("app.decorators.auth_decorator.jwt.decode", return_value={
                "user_id": 7, "company_id": 100, "role": "member", "is_platform_admin": False,
            }),
            patch("app.database.user_repository.get_user_by_id", return_value={
                "id": 7, "company_id": 100, "email": "internal@example.test", "status": "active", "role": "member",
            }),
            patch(
                "app.decorators.platform_admin_decorator.get_active_platform_admin_by_user_id",
                return_value={"id": 3, "user_id": 7, "is_active": True},
            ),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_routes_call_bounded_services_with_server_side_actor_context(self):
        with patch.object(
            platform_admin_service,
            "list_platform_admin_users",
            return_value={"platform_admin_users": [], "pagination": {"total": 0}},
        ) as list_service:
            response = self.client.get("/api/platform-admin/platform-admin-users", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        list_service.assert_called_once_with(3, limit=None, offset=None, is_active=None)

        with patch.object(
            platform_admin_service,
            "get_platform_admin_user",
            return_value={"platform_admin_user": {"platform_admin_user_id": 6}},
        ) as get_service:
            response = self.client.get("/api/platform-admin/platform-admin-users/6", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        get_service.assert_called_once_with(6, 3)

        with patch.object(
            platform_admin_service,
            "create_platform_admin_user",
            return_value={"platform_admin_user": {"platform_admin_user_id": 6}},
        ) as create_service:
            response = self.client.post(
                "/api/platform-admin/platform-admin-users",
                headers=self.headers,
                json={"user_id": 8},
            )
        self.assertEqual(response.status_code, 200)
        create_service.assert_called_once_with({"user_id": 8}, {"id": 3, "user_id": 7, "is_active": True})

        with patch.object(
            platform_admin_service,
            "set_platform_admin_user_active",
            return_value={"platform_admin_user": {"platform_admin_user_id": 6, "is_active": False}},
        ) as active_service:
            response = self.client.patch(
                "/api/platform-admin/platform-admin-users/6/active",
                headers=self.headers,
                json={"is_active": False},
            )
        self.assertEqual(response.status_code, 200)
        active_service.assert_called_once_with(6, {"is_active": False}, 3)

    def test_route_rejections_are_stable_and_sanitized(self):
        cases = [
            ("post", "/api/platform-admin/platform-admin-users", {"user_id": True}, 400, "invalid_user_id"),
            ("post", "/api/platform-admin/platform-admin-users", {"user_id": 8, "role": "admin"}, 400, "invalid_request"),
            ("patch", "/api/platform-admin/platform-admin-users/6/active", {}, 400, "invalid_is_active"),
            ("patch", "/api/platform-admin/platform-admin-users/6/active", {"is_active": "false"}, 400, "invalid_is_active"),
        ]
        for method, path, payload, status, code in cases:
            with self.subTest(path=path, payload=payload):
                response = getattr(self.client, method)(path, headers=self.headers, json=payload)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json["code"], code)

        with patch.object(
            platform_admin_service.platform_admin_repository,
            "create_platform_admin_user_mapping_for_platform_admin",
            side_effect=RuntimeError("Target user must belong to a protected company raw provider detail"),
        ):
            response = self.client.post(
                "/api/platform-admin/platform-admin-users",
                headers=self.headers,
                json={"user_id": 8},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["code"], "target_user_not_protected")
        self.assertNotIn("provider", response.get_data(as_text=True).lower())


if __name__ == "__main__":
    unittest.main()
