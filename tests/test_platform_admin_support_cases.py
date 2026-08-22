import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from flask import Flask

from app.routes.platform_admin_routes import platform_admin_bp
from app.database import platform_admin_repository
from app.database import platform_support_case_repository
from app.services import platform_admin_service


class PlatformAdminSupportCaseRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(platform_admin_bp)
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer token"}
        self.patches = [
            patch("app.decorators.auth_decorator.get_jwt_secret", return_value="secret"),
            patch("app.decorators.auth_decorator.jwt.decode", return_value={
                "user_id": 7, "company_id": 100, "role": "member",
                "is_platform_admin": False,
            }),
            patch("app.database.user_repository.get_user_by_id", return_value={
                "id": 7, "company_id": 100, "email": "internal@example.test",
                "status": "active", "role": "member",
            }),
            patch(
                "app.decorators.platform_admin_decorator.get_active_platform_admin_by_user_id",
                return_value={"id": 3, "user_id": 7, "is_active": True},
            ),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_support_case_routes_require_existing_platform_guard(self):
        for method, path in [
            (self.client.get, "/api/platform-admin/support-cases"),
            (self.client.get, "/api/platform-admin/support-case-assignees"),
            (self.client.post, "/api/platform-admin/support-cases"),
            (self.client.get, "/api/platform-admin/support-cases/1"),
            (self.client.get, "/api/platform-admin/support-cases/1/replies"),
            (self.client.post, "/api/platform-admin/support-cases/1/replies"),
            (self.client.post, "/api/platform-admin/support-cases/1/notes"),
            (self.client.patch, "/api/platform-admin/support-cases/1/assignment"),
            (self.client.patch, "/api/platform-admin/support-cases/1/status"),
            (self.client.patch, "/api/platform-admin/support-cases/1/priority"),
        ]:
            with self.subTest(path=path):
                self.assertEqual(method(path).status_code, 401)

    def test_create_route_passes_safe_json_to_service(self):
        with patch.object(
            platform_admin_service,
            "create_support_case",
            return_value={"case": {"id": 9, "company_id": 31}},
        ) as service:
            response = self.client.post(
                "/api/platform-admin/support-cases",
                headers=self.headers,
                json={
                    "company_id": 31,
                    "title": "Review tenant activation",
                    "redacted_summary": "Review the safe activation state.",
                },
            )
        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with({
            "company_id": 31,
            "title": "Review tenant activation",
            "redacted_summary": "Review the safe activation state.",
        }, 3)

    def test_list_detail_note_and_operation_routes_use_expected_methods(self):
        with patch.object(platform_admin_service, "list_support_cases", return_value={"cases": []}), \
             patch.object(platform_admin_service, "list_support_case_assignees", return_value={"assignees": []}), \
             patch.object(platform_admin_service, "get_support_case", return_value={"case": {}, "events": []}), \
             patch.object(platform_admin_service, "list_support_case_replies", return_value={"replies": []}), \
             patch.object(platform_admin_service, "create_support_case_reply", return_value={"reply": {}}), \
             patch.object(platform_admin_service, "add_support_case_note", return_value={"event": {}}), \
             patch.object(platform_admin_service, "assign_support_case", return_value={"case": {}}), \
             patch.object(platform_admin_service, "update_support_case_status", return_value={"case": {}}), \
             patch.object(platform_admin_service, "update_support_case_priority", return_value={"case": {}}):
            responses = [
                self.client.get("/api/platform-admin/support-cases", headers=self.headers),
                self.client.get("/api/platform-admin/support-case-assignees", headers=self.headers),
                self.client.get("/api/platform-admin/support-cases/1", headers=self.headers),
                self.client.get("/api/platform-admin/support-cases/1/replies", headers=self.headers),
                self.client.post(
                    "/api/platform-admin/support-cases/1/replies",
                    headers=self.headers, json={"redacted_body": "Tenant-visible update"},
                ),
                self.client.post(
                    "/api/platform-admin/support-cases/1/notes",
                    headers=self.headers, json={"redacted_note": "Internal note"},
                ),
                self.client.patch(
                    "/api/platform-admin/support-cases/1/assignment",
                    headers=self.headers, json={"assigned_platform_admin_user_id": 4},
                ),
                self.client.patch(
                    "/api/platform-admin/support-cases/1/status",
                    headers=self.headers, json={"status": "resolved"},
                ),
                self.client.patch(
                    "/api/platform-admin/support-cases/1/priority",
                    headers=self.headers, json={"priority": "high"},
                ),
            ]
        self.assertTrue(all(response.status_code == 200 for response in responses))


class PlatformAdminSupportCaseServiceTests(unittest.TestCase):
    def test_create_uses_atomic_rpc_and_safe_projection(self):
        company = {"id": 31, "company_name": "Safe Tenant", "status": "active"}
        case = {
            "id": 9, "company_id": 31, "status": "open", "priority": "normal",
            "title": "Review activation", "redacted_summary": "Safe summary",
        }
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin", return_value=company,
        ), patch.object(
            platform_admin_service.platform_support_case_repository,
            "create_support_case_for_platform_admin",
            return_value={
                "case": case,
                "event": {"id": 1, "case_id": 9, "event_type": "created"},
                "audit": {
                    "id": 2,
                    "resource_id": "9",
                    "action": "platform_admin.support_case.create",
                },
            },
        ) as rpc, patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
        ) as app_audit:
            result = platform_admin_service.create_support_case({
                "company_id": 31,
                "title": "Review activation",
                "redacted_summary": "Safe summary",
            }, 3)
        self.assertEqual(result["case"]["company"], {
            "id": 31, "company_name": "Safe Tenant", "status": "active",
        })
        self.assertNotIn("email", result["case"])
        rpc.assert_called_once_with(
            company_id=31,
            platform_admin_user_id=3,
            title="Review activation",
            redacted_summary="Safe summary",
            status="open",
            priority="normal",
        )
        app_audit.assert_not_called()

    def test_create_rpc_failure_is_controlled_without_app_side_partial_writes(self):
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 31, "company_name": "Safe Tenant", "status": "active"},
        ), patch.object(
            platform_admin_service.platform_support_case_repository,
            "create_support_case_for_platform_admin",
            side_effect=RuntimeError("event insert failed after case insert would roll back"),
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
        ) as app_audit:
            with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                platform_admin_service.create_support_case({
                    "company_id": 31,
                    "title": "Review activation",
                    "redacted_summary": "Safe summary",
                }, 3)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.code, "platform_admin_data_unavailable")
        app_audit.assert_not_called()

    def test_create_rejects_inactive_platform_admin_mapping_from_rpc(self):
        with patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 31, "company_name": "Safe Tenant", "status": "active"},
        ), patch.object(
            platform_admin_service.platform_support_case_repository,
            "create_support_case_for_platform_admin",
            side_effect=RuntimeError("Active platform-admin mapping is required"),
        ):
            with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                platform_admin_service.create_support_case({
                    "company_id": 31,
                    "title": "Review activation",
                    "redacted_summary": "Safe summary",
                }, 3)
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.code, "platform_admin_access_denied")

    def test_redaction_boundary_rejects_sensitive_case_text(self):
        with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
            platform_admin_service.create_support_case({
                "company_id": 31,
                "title": "Review secret token",
                "redacted_summary": "Safe summary",
            }, 3)
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.code, "invalid_title")

    def test_status_transition_options_are_explicit(self):
        self.assertEqual(
            platform_admin_service._safe_support_case_transition_options("open"),
            ["in_progress", "resolved", "waiting_for_tenant"],
        )
        self.assertEqual(
            platform_admin_service._safe_support_case_transition_options("closed"),
            ["in_progress"],
        )

    def test_operation_payloads_reject_unknown_fields(self):
        for service_call, payload, code in (
            (platform_admin_service.add_support_case_note, {"redacted_note": "ok", "status": "open"}, "invalid_request"),
            (platform_admin_service.create_support_case_reply, {"redacted_body": "ok", "status": "open"}, "invalid_request"),
            (platform_admin_service.assign_support_case, {"assigned_platform_admin_user_id": 4, "role": "admin"}, "invalid_request"),
            (platform_admin_service.update_support_case_status, {"status": "resolved", "priority": "high"}, "invalid_request"),
            (platform_admin_service.update_support_case_priority, {"priority": "high", "status": "open"}, "invalid_request"),
        ):
            with self.subTest(service=service_call.__name__):
                with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                    service_call(9, payload, 3)
                self.assertEqual(raised.exception.code, code)

    def test_assignment_payload_rejects_arbitrary_non_integer_ids(self):
        with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
            platform_admin_service.assign_support_case(
                9, {"assigned_platform_admin_user_id": "7"}, 3
            )
        self.assertEqual(raised.exception.code, "invalid_assignee")

    def test_assignee_list_projects_safe_identity_and_audit_metadata(self):
        with patch.object(
            platform_admin_service.platform_support_case_repository,
            "list_active_platform_admin_assignees_for_platform_admin",
            return_value=[{
                "id": 4,
                "user_id": 8,
                "is_active": True,
                "user_full_name": "Alice Tan",
                "user_email": "alice@example.test",
                "role": "owner",
                "company_id": 31,
                "password_hash": "secret",
                "audit_metadata": {"unsafe": True},
            }],
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            return_value={"id": 1},
        ) as audit:
            result = platform_admin_service.list_support_case_assignees(3)

        self.assertEqual(result["assignees"], [{
            "id": 4,
            "user_id": 8,
            "is_active": True,
            "user_full_name": "Alice Tan",
            "user_email": "alice@example.test",
        }])
        for forbidden in ("role", "company_id", "password_hash", "audit_metadata"):
            self.assertNotIn(forbidden, result["assignees"][0])
        audit.assert_called_once()
        metadata = audit.call_args.args[4]
        self.assertEqual(metadata["returned_count"], 1)
        self.assertNotIn("user_full_name", metadata)
        self.assertNotIn("user_email", metadata)

    def test_assignment_rejects_inactive_or_unknown_platform_admin_mapping(self):
        with patch.object(
            platform_admin_service.platform_support_case_repository,
            "get_active_platform_admin_assignee_for_platform_admin",
            return_value=None,
        ):
            with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                platform_admin_service.assign_support_case(
                    9, {"assigned_platform_admin_user_id": 77}, 3
                )
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.code, "invalid_assignee")

    def test_known_rpc_errors_are_mapped_to_stable_sanitized_errors(self):
        cases = [
            (
                platform_admin_service.add_support_case_note,
                "Support case not found: raw db host",
                "support_case_not_found",
                404,
                {"redacted_note": "Safe note"},
            ),
            (
                platform_admin_service.assign_support_case,
                "Active platform-admin mapping is required: raw db role",
                "invalid_assignee",
                400,
                {"assigned_platform_admin_user_id": 4},
            ),
            (
                platform_admin_service.update_support_case_status,
                "Support case transition is not allowed: raw sqlstate",
                "invalid_status",
                400,
                {"status": "resolved"},
            ),
            (
                platform_admin_service.update_support_case_priority,
                "Unsupported support case priority: raw enum",
                "invalid_priority",
                400,
                {"priority": "urgent"},
            ),
            (
                platform_admin_service.update_support_case_priority,
                "Support case priority is unchanged: raw row",
                "no_change",
                400,
                {"priority": "urgent"},
            ),
        ]
        for service_call, message, code, status_code, payload in cases:
            with self.subTest(service=service_call.__name__, code=code), patch.object(
                platform_admin_service.platform_support_case_repository,
                "get_active_platform_admin_assignee_for_platform_admin",
                return_value={"id": 4, "is_active": True},
            ), patch.object(
                platform_admin_service.platform_support_case_repository,
                "get_support_case_for_platform_admin",
                return_value={
                    "id": 9,
                    "company_id": 31,
                    "status": "open",
                    "priority": "normal" if service_call is not platform_admin_service.update_support_case_priority else "low",
                    "assigned_platform_admin_user_id": None,
                },
            ), patch.object(
                platform_admin_service.platform_admin_repository,
                "insert_platform_admin_audit_event",
                return_value={"id": 1},
            ), patch.object(
                platform_admin_service.platform_support_case_repository,
                "add_support_case_note_for_platform_admin",
                side_effect=RuntimeError(message),
            ), patch.object(
                platform_admin_service.platform_support_case_repository,
                "assign_support_case_for_platform_admin",
                side_effect=RuntimeError(message),
            ), patch.object(
                platform_admin_service.platform_support_case_repository,
                "set_support_case_status_for_platform_admin",
                side_effect=RuntimeError(message),
            ), patch.object(
                platform_admin_service.platform_support_case_repository,
                "set_support_case_priority_for_platform_admin",
                side_effect=RuntimeError(message),
            ):
                with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                    service_call(9, payload, 3)
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(raised.exception.status_code, status_code)
                self.assertNotIn("raw", raised.exception.message.lower())

    def test_no_op_priority_and_assignee_are_rejected_before_rpc(self):
        with patch.object(
            platform_admin_service.platform_support_case_repository,
            "get_support_case_for_platform_admin",
            return_value={
                "id": 9,
                "company_id": 31,
                "status": "open",
                "priority": "normal",
                "assigned_platform_admin_user_id": 4,
            },
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            return_value={"id": 1},
        ), patch.object(
            platform_admin_service.platform_support_case_repository,
            "get_active_platform_admin_assignee_for_platform_admin",
            return_value={"id": 4, "is_active": True},
        ), patch.object(
            platform_admin_service.platform_support_case_repository,
            "set_support_case_priority_for_platform_admin",
        ) as priority_rpc, patch.object(
            platform_admin_service.platform_support_case_repository,
            "assign_support_case_for_platform_admin",
        ) as assign_rpc:
            with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as priority_error:
                platform_admin_service.update_support_case_priority(9, {"priority": "normal"}, 3)
            with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as assign_error:
                platform_admin_service.assign_support_case(9, {"assigned_platform_admin_user_id": 4}, 3)
        self.assertEqual(priority_error.exception.code, "no_change")
        self.assertEqual(assign_error.exception.code, "no_change")
        priority_rpc.assert_not_called()
        assign_rpc.assert_not_called()

    def test_support_case_audit_write_methods_and_safe_metadata_are_validated(self):
        platform_admin_repository.validate_audit_event(
            3,
            "platform_admin.support_case.create",
            "platform_support_cases",
            "9",
            {
                "outcome": "success",
                "endpoint": "/api/platform-admin/support-cases",
                "http_method": "POST",
                "company_id": 31,
                "status": "open",
                "priority": "normal",
            },
        )
        with self.assertRaises(ValueError):
            platform_admin_repository.validate_audit_event(
                3,
                "platform_admin.support_case.create",
                "platform_support_cases",
                "9",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/support-cases",
                    "http_method": "GET",
                    "company_id": 31,
                },
            )

    def test_public_reply_creation_uses_rpc_and_excludes_body_from_audit_metadata(self):
        rpc_result = {
            "case": {
                "id": 9, "company_id": 31, "status": "in_progress",
                "priority": "normal", "title": "Safe", "redacted_summary": "Safe",
            },
            "event": {
                "id": 20, "case_id": 9, "event_type": "tenant_reply_created",
                "tenant_support_reply_id": 44,
            },
            "reply": {
                "id": 44, "request_id": 12, "platform_support_case_id": 9,
                "company_id": 31, "author_type": "platform_admin",
                "author_platform_admin_user_id": 3,
                "redacted_body": "Tenant-visible update",
                "visibility_status": "visible",
            },
            "notification": {
                "id": 50, "reply_id": 44, "channel": "in_app",
                "status": "pending", "failure_code": "raw-provider-error",
            },
        }
        with patch.object(
            platform_admin_service.platform_support_case_repository,
            "get_support_case_for_platform_admin",
            return_value={"id": 9, "company_id": 31, "status": "open", "priority": "normal"},
        ), patch.object(
            platform_admin_service.platform_support_case_repository,
            "create_support_case_reply_for_platform_admin",
            return_value=rpc_result,
        ) as rpc, patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 31, "company_name": "Tenant", "status": "active"},
        ):
            result = platform_admin_service.create_support_case_reply(
                9, {"redacted_body": " Tenant-visible update "}, 3
            )
        rpc.assert_called_once_with(9, 3, "Tenant-visible update")
        self.assertEqual(result["reply"]["redacted_body"], "Tenant-visible update")
        self.assertEqual(result["notification"]["status"], "pending")
        self.assertNotIn("author_platform_admin_user_id", result["reply"])
        self.assertNotIn("failure_code", result["notification"])

    def test_public_reply_validation_and_known_rpc_errors_are_sanitized(self):
        with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as empty:
            platform_admin_service.create_support_case_reply(9, {"redacted_body": "   "}, 3)
        self.assertEqual(empty.exception.code, "invalid_redacted_body")
        with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as sensitive:
            platform_admin_service.create_support_case_reply(9, {"redacted_body": "send token"}, 3)
        self.assertEqual(sensitive.exception.code, "invalid_redacted_body")

        with patch.object(
            platform_admin_service.platform_support_case_repository,
            "get_support_case_for_platform_admin",
            return_value={"id": 9, "company_id": 31, "status": "open", "priority": "normal"},
        ), patch.object(
            platform_admin_service.platform_support_case_repository,
            "create_support_case_reply_for_platform_admin",
            side_effect=RuntimeError("Converted tenant support request not found: raw db detail"),
        ):
            with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                platform_admin_service.create_support_case_reply(
                    9, {"redacted_body": "Safe tenant update"}, 3
                )
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.code, "tenant_support_request_not_found")
        self.assertNotIn("raw", raised.exception.message.lower())

    def test_public_reply_malformed_rpc_result_is_sanitized_as_unavailable(self):
        with patch.object(
            platform_admin_service.platform_support_case_repository,
            "get_support_case_for_platform_admin",
            return_value={"id": 9, "company_id": 31, "status": "open", "priority": "normal"},
        ), patch.object(
            platform_admin_service.platform_support_case_repository,
            "create_support_case_reply_for_platform_admin",
            side_effect=RuntimeError("create_platform_support_case_reply RPC returned raw mismatch"),
        ):
            with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                platform_admin_service.create_support_case_reply(
                    9, {"redacted_body": "Safe tenant update"}, 3
                )
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.code, "platform_admin_data_unavailable")
        self.assertNotIn("raw", raised.exception.message.lower())
        self.assertNotIn("rpc", raised.exception.message.lower())

    def test_public_reply_list_audits_read_and_projects_safe_fields(self):
        with patch.object(
            platform_admin_service.platform_support_case_repository,
            "get_support_case_for_platform_admin",
            return_value={"id": 9, "company_id": 31, "status": "open", "priority": "normal"},
        ), patch.object(
            platform_admin_service.tenant_support_repository,
            "get_tenant_support_request_by_converted_case_id_for_platform_admin",
            return_value={"id": 12, "company_id": 31, "status": "converted"},
        ), patch.object(
            platform_admin_service.platform_support_case_repository,
            "list_support_case_replies_for_platform_admin",
            return_value=([{
                "id": 44, "request_id": 12, "platform_support_case_id": 9,
                "company_id": 31, "author_type": "platform_admin",
                "author_platform_admin_user_id": 3,
                "redacted_body": "Visible update", "visibility_status": "visible",
            }], 1),
        ) as replies, patch.object(
            platform_admin_service.platform_support_case_repository,
            "list_support_case_reply_notifications_for_platform_admin",
            return_value=[{
                "id": 50, "reply_id": 44, "channel": "in_app",
                "status": "pending", "failure_code": "raw-provider-error",
            }],
        ) as notifications, patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            return_value={"id": 1},
        ) as audit:
            result = platform_admin_service.list_support_case_replies(9, 3)
        self.assertEqual(result["replies"][0]["redacted_body"], "Visible update")
        self.assertNotIn("author_platform_admin_user_id", result["replies"][0])
        self.assertNotIn("failure_code", result["notifications"][0])
        self.assertEqual(result["pagination"], {
            "limit": 25, "offset": 0, "returned": 1, "total": 1, "has_more": False,
        })
        replies.assert_called_once_with(9, limit=25, offset=0)
        notifications.assert_called_once_with(9, [44])
        self.assertEqual(audit.call_args.args[1], "platform_admin.support_case.reply.list")
        self.assertEqual(audit.call_args.args[4]["limit"], 25)
        self.assertEqual(audit.call_args.args[4]["offset"], 0)
        self.assertNotIn("redacted_body", audit.call_args.args[4])

    def test_support_case_detail_uses_paginated_events(self):
        with patch.object(
            platform_admin_service.platform_support_case_repository,
            "get_support_case_for_platform_admin",
            return_value={"id": 9, "company_id": 31, "status": "open", "priority": "normal"},
        ), patch.object(
            platform_admin_service.platform_support_case_repository,
            "list_support_case_events_for_platform_admin",
            return_value=([{
                "id": 20, "case_id": 9, "event_type": "created",
                "actor_platform_admin_user_id": 3,
                "new_status": "open", "new_priority": "normal",
            }], 30),
        ) as events, patch.object(
            platform_admin_service.platform_company_repository,
            "get_company_for_platform_admin",
            return_value={"id": 31, "company_name": "Tenant", "status": "active"},
        ), patch.object(
            platform_admin_service.tenant_support_repository,
            "get_tenant_support_request_by_converted_case_id_for_platform_admin",
            return_value=None,
        ), patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            return_value={"id": 1},
        ) as audit:
            result = platform_admin_service.get_support_case(
                9, 3, event_limit="1", event_offset="2"
            )
        events.assert_called_once_with(9, limit=1, offset=2)
        self.assertEqual(result["events_pagination"], {
            "limit": 1, "offset": 2, "returned": 1, "total": 30, "has_more": True,
        })
        self.assertEqual(audit.call_args.args[4]["limit"], 1)
        self.assertEqual(audit.call_args.args[4]["offset"], 2)

    def test_support_case_pagination_validation(self):
        invalid_detail = [
            {"event_limit": "0"},
            {"event_limit": "101"},
            {"event_limit": "abc"},
            {"event_offset": "-1"},
            {"event_offset": "abc"},
        ]
        for kwargs in invalid_detail:
            with self.subTest(detail=kwargs):
                with self.assertRaises(platform_admin_service.PlatformAdminServiceError):
                    platform_admin_service.get_support_case(9, 3, **kwargs)
        invalid_replies = [
            {"limit": "0"},
            {"limit": "101"},
            {"limit": "abc"},
            {"offset": "-1"},
            {"offset": "abc"},
        ]
        for kwargs in invalid_replies:
            with self.subTest(replies=kwargs):
                with self.assertRaises(platform_admin_service.PlatformAdminServiceError):
                    platform_admin_service.list_support_case_replies(9, 3, **kwargs)

    def test_support_case_reply_empty_page_and_max_limit_are_supported(self):
        with patch.object(
            platform_admin_service.platform_support_case_repository,
            "get_support_case_for_platform_admin",
            return_value={"id": 9, "company_id": 31, "status": "open", "priority": "normal"},
        ), patch.object(
            platform_admin_service.tenant_support_repository,
            "get_tenant_support_request_by_converted_case_id_for_platform_admin",
            return_value=None,
        ), patch.object(
            platform_admin_service.platform_support_case_repository,
            "list_support_case_replies_for_platform_admin",
            return_value=([], 100),
        ) as replies, patch.object(
            platform_admin_service.platform_support_case_repository,
            "list_support_case_reply_notifications_for_platform_admin",
            return_value=[],
        ) as notifications, patch.object(
            platform_admin_service.platform_admin_repository,
            "insert_platform_admin_audit_event",
            return_value={"id": 1},
        ):
            result = platform_admin_service.list_support_case_replies(
                9, 3, limit="100", offset="100"
            )
        replies.assert_called_once_with(9, limit=100, offset=100)
        notifications.assert_called_once_with(9, [])
        self.assertEqual(result["replies"], [])
        self.assertEqual(result["pagination"], {
            "limit": 100, "offset": 100, "returned": 0, "total": 100, "has_more": False,
        })


class PlatformAdminSupportCaseRepositoryTests(unittest.TestCase):
    def _reply_rpc_result(self):
        return {
            "case": {"id": 9, "company_id": 31, "status": "in_progress", "priority": "normal"},
            "event": {
                "id": 1,
                "case_id": 9,
                "event_type": "tenant_reply_created",
                "tenant_support_reply_id": 44,
            },
            "reply": {
                "id": 44,
                "request_id": 12,
                "platform_support_case_id": 9,
                "company_id": 31,
                "author_type": "platform_admin",
                "redacted_body": "Visible reply",
                "visibility_status": "visible",
            },
            "notification": {
                "id": 50,
                "reply_id": 44,
                "request_id": 12,
                "platform_support_case_id": 9,
                "company_id": 31,
                "channel": "in_app",
                "status": "pending",
                "attempt_count": 0,
            },
        }

    def test_list_uses_safe_projection_and_filters(self):
        query = MagicMock()
        for method in ("select", "eq", "order", "range"):
            getattr(query, method).return_value = query
        query.execute.return_value = SimpleNamespace(
            data=[{"id": 9, "company_id": 31, "title": "Safe"}], count=1
        )
        with patch.object(platform_support_case_repository.supabase, "table", return_value=query):
            rows, total = platform_support_case_repository.list_support_cases_for_platform_admin(
                limit=25, offset=0, company_id=31, status="open", priority="normal",
            )
        query.select.assert_called_once_with(platform_support_case_repository.CASE_FIELDS, count="exact")
        query.eq.assert_any_call("company_id", 31)
        query.eq.assert_any_call("status", "open")
        query.eq.assert_any_call("priority", "normal")
        self.assertEqual((rows, total), ([{"id": 9, "company_id": 31, "title": "Safe"}], 1))
        self.assertNotIn("*", platform_support_case_repository.CASE_FIELDS)

    def test_active_assignee_lookup_uses_platform_admin_mapping_table(self):
        query = MagicMock()
        for method in ("select", "eq", "limit"):
            getattr(query, method).return_value = query
        query.execute.return_value = SimpleNamespace(data=[{"id": 4, "is_active": True}])
        with patch.object(platform_support_case_repository.supabase, "table", return_value=query):
            row = platform_support_case_repository.get_active_platform_admin_assignee_for_platform_admin(4)
        self.assertEqual(row["id"], 4)
        self.assertEqual(query.eq.call_args_list[0].args, ("id", 4))
        self.assertEqual(query.eq.call_args_list[1].args, ("is_active", True))

    def test_active_assignee_list_batches_safe_user_identity_lookup(self):
        mapping_query = MagicMock()
        for method in ("select", "eq", "order"):
            getattr(mapping_query, method).return_value = mapping_query
        mapping_query.execute.return_value = SimpleNamespace(data=[
            {"id": 4, "user_id": 8, "is_active": True},
            {"id": 5, "user_id": 9, "is_active": True},
        ])
        user_query = MagicMock()
        for method in ("select", "in_"):
            getattr(user_query, method).return_value = user_query
        user_query.execute.return_value = SimpleNamespace(data=[
            {"id": 9, "email": "bob@example.test", "full_name": "Bob Lee", "role": "admin"},
            {"id": 8, "email": "alice@example.test", "full_name": "Alice Tan", "company_id": 31},
        ])
        with patch.object(
            platform_support_case_repository.supabase,
            "table",
            side_effect=[mapping_query, user_query],
        ) as table_call, patch.object(
            platform_support_case_repository.supabase,
            "rpc",
        ) as rpc:
            rows = platform_support_case_repository.list_active_platform_admin_assignees_for_platform_admin()

        self.assertEqual(table_call.call_args_list[0].args, ("platform_admin_users",))
        self.assertEqual(table_call.call_args_list[1].args, ("users",))
        self.assertEqual(table_call.call_count, 2)
        rpc.assert_not_called()
        mapping_query.select.assert_called_once_with("id,user_id,is_active")
        mapping_query.eq.assert_called_once_with("is_active", True)
        user_query.select.assert_called_once_with(
            platform_support_case_repository.ASSIGNEE_USER_IDENTITY_FIELDS
        )
        user_query.in_.assert_called_once_with("id", [8, 9])
        self.assertEqual(rows, [
            {
                "id": 4,
                "user_id": 8,
                "is_active": True,
                "user_full_name": "Alice Tan",
                "user_email": "alice@example.test",
            },
            {
                "id": 5,
                "user_id": 9,
                "is_active": True,
                "user_full_name": "Bob Lee",
                "user_email": "bob@example.test",
            },
        ])
        for row in rows:
            self.assertNotIn("role", row)
            self.assertNotIn("company_id", row)

    def test_active_assignee_list_handles_missing_identity_with_safe_nulls(self):
        mapping_query = MagicMock()
        for method in ("select", "eq", "order"):
            getattr(mapping_query, method).return_value = mapping_query
        mapping_query.execute.return_value = SimpleNamespace(data=[
            {"id": 4, "user_id": 8, "is_active": True},
        ])
        user_query = MagicMock()
        for method in ("select", "in_"):
            getattr(user_query, method).return_value = user_query
        user_query.execute.return_value = SimpleNamespace(data=[])
        with patch.object(
            platform_support_case_repository.supabase,
            "table",
            side_effect=[mapping_query, user_query],
        ):
            rows = platform_support_case_repository.list_active_platform_admin_assignees_for_platform_admin()

        self.assertEqual(rows, [{
            "id": 4,
            "user_id": 8,
            "is_active": True,
            "user_full_name": None,
            "user_email": None,
        }])

    def test_event_list_uses_exact_count_range_and_chronological_order(self):
        query = MagicMock()
        for method in ("select", "eq", "order", "range"):
            getattr(query, method).return_value = query
        query.execute.return_value = SimpleNamespace(data=[{"id": 20}], count=120)
        with patch.object(platform_support_case_repository.supabase, "table", return_value=query) as table_call:
            rows, total = platform_support_case_repository.list_support_case_events_for_platform_admin(
                9, limit=25, offset=50
            )
        table_call.assert_called_once_with("platform_support_case_events")
        query.select.assert_called_once_with(platform_support_case_repository.EVENT_FIELDS, count="exact")
        query.eq.assert_called_once_with("case_id", 9)
        self.assertEqual(query.order.call_args_list[0].args, ("created_at",))
        self.assertEqual(query.order.call_args_list[0].kwargs, {"desc": False})
        self.assertEqual(query.order.call_args_list[1].args, ("id",))
        self.assertEqual(query.order.call_args_list[1].kwargs, {"desc": False})
        query.range.assert_called_once_with(50, 74)
        self.assertEqual((rows, total), ([{"id": 20}], 120))

    def test_reply_list_uses_exact_count_range_and_chronological_order(self):
        query = MagicMock()
        for method in ("select", "eq", "order", "range"):
            getattr(query, method).return_value = query
        query.execute.return_value = SimpleNamespace(data=[{"id": 44}], count=101)
        with patch.object(platform_support_case_repository.supabase, "table", return_value=query) as table_call:
            rows, total = platform_support_case_repository.list_support_case_replies_for_platform_admin(
                9, limit=25, offset=25
            )
        table_call.assert_called_once_with("tenant_support_replies")
        query.select.assert_called_once_with(platform_support_case_repository.REPLY_FIELDS, count="exact")
        query.eq.assert_called_once_with("platform_support_case_id", 9)
        self.assertEqual(query.order.call_args_list[0].args, ("created_at",))
        self.assertEqual(query.order.call_args_list[0].kwargs, {"desc": False})
        self.assertEqual(query.order.call_args_list[1].args, ("id",))
        self.assertEqual(query.order.call_args_list[1].kwargs, {"desc": False})
        query.range.assert_called_once_with(25, 49)
        self.assertEqual((rows, total), ([{"id": 44}], 101))

    def test_notification_lookup_is_restricted_to_returned_reply_ids(self):
        query = MagicMock()
        for method in ("select", "eq", "in_", "order"):
            getattr(query, method).return_value = query
        query.execute.return_value = SimpleNamespace(data=[{"id": 50, "reply_id": 44}])
        with patch.object(platform_support_case_repository.supabase, "table", return_value=query):
            rows = platform_support_case_repository.list_support_case_reply_notifications_for_platform_admin(
                9, [44, 45, 44, None, True, -1]
            )
        query.eq.assert_called_once_with("platform_support_case_id", 9)
        query.in_.assert_called_once_with("reply_id", [44, 45])
        self.assertEqual(rows, [{"id": 50, "reply_id": 44}])

    def test_empty_reply_page_skips_notification_lookup(self):
        with patch.object(platform_support_case_repository.supabase, "table") as table_call:
            rows = platform_support_case_repository.list_support_case_reply_notifications_for_platform_admin(9, [])
        table_call.assert_not_called()
        self.assertEqual(rows, [])

    def test_history_pagination_rejects_invalid_bounds(self):
        invalids = [
            (platform_support_case_repository.list_support_case_events_for_platform_admin, {"limit": 0, "offset": 0}),
            (platform_support_case_repository.list_support_case_events_for_platform_admin, {"limit": 101, "offset": 0}),
            (platform_support_case_repository.list_support_case_events_for_platform_admin, {"limit": 25, "offset": -1}),
            (platform_support_case_repository.list_support_case_replies_for_platform_admin, {"limit": 0, "offset": 0}),
            (platform_support_case_repository.list_support_case_replies_for_platform_admin, {"limit": 101, "offset": 0}),
            (platform_support_case_repository.list_support_case_replies_for_platform_admin, {"limit": 25, "offset": -1}),
        ]
        for func, kwargs in invalids:
            with self.subTest(func=func.__name__, kwargs=kwargs):
                with self.assertRaises(ValueError):
                    func(9, **kwargs)

    def test_operation_rpcs_use_expected_names_and_arguments(self):
        case_response = {
            "case": {"id": 9, "case_id": 9, "status": "in_progress", "priority": "normal"},
            "event": {"id": 1, "case_id": 9},
        }
        creation_response = {
            "case": {
                "id": 9,
                "company_id": 31,
                "created_by_platform_admin_user_id": 3,
                "status": "open",
                "priority": "normal",
                "title": "Safe",
                "redacted_summary": "Safe summary",
            },
            "event": {
                "id": 1,
                "case_id": 9,
                "event_type": "created",
                "actor_platform_admin_user_id": 3,
                "new_status": "open",
                "new_priority": "normal",
            },
            "audit": {
                "id": 2,
                "platform_admin_user_id": 3,
                "action": "platform_admin.support_case.create",
                "resource_type": "platform_support_cases",
                "resource_id": "9",
                "metadata": {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/support-cases",
                    "http_method": "POST",
                    "company_id": 31,
                    "status": "open",
                    "priority": "normal",
                },
            },
        }
        rpc = MagicMock(side_effect=[
            MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=creation_response))),
            MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=case_response))),
            MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=case_response))),
            MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=case_response))),
            MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=case_response))),
            MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=self._reply_rpc_result()))),
        ])
        with patch.object(platform_support_case_repository.supabase, "rpc", rpc):
            platform_support_case_repository.create_support_case_for_platform_admin(
                company_id=31,
                platform_admin_user_id=3,
                title="Safe",
                redacted_summary="Safe summary",
                status="open",
                priority="normal",
            )
            platform_support_case_repository.assign_support_case_for_platform_admin(9, 3, 4)
            platform_support_case_repository.set_support_case_status_for_platform_admin(9, 3, "in_progress")
            platform_support_case_repository.set_support_case_priority_for_platform_admin(9, 3, "high")
            platform_support_case_repository.add_support_case_note_for_platform_admin(9, 3, "Safe note")
            platform_support_case_repository.create_support_case_reply_for_platform_admin(9, 3, "Visible reply")
        self.assertEqual([call.args[0] for call in rpc.call_args_list], [
            "create_platform_support_case",
            "assign_platform_support_case",
            "set_platform_support_case_status",
            "set_platform_support_case_priority",
            "add_platform_support_case_note",
            "create_platform_support_case_reply",
        ])
        self.assertEqual(rpc.call_args_list[0].args[1], {
            "p_company_id": 31,
            "p_platform_admin_user_id": 3,
            "p_title": "Safe",
            "p_redacted_summary": "Safe summary",
            "p_status": "open",
            "p_priority": "normal",
        })
        self.assertEqual(
            rpc.call_args_list[1].args[1]["p_assignee_platform_admin_user_id"],
            4,
        )

    def test_create_rpc_result_rejects_missing_event_or_audit(self):
        result = {
            "case": {
                "id": 9,
                "company_id": 31,
                "created_by_platform_admin_user_id": 3,
                "status": "open",
                "priority": "normal",
                "title": "Safe",
                "redacted_summary": "Safe summary",
            },
            "event": {
                "id": 1,
                "case_id": 9,
                "event_type": "created",
                "actor_platform_admin_user_id": 3,
                "new_status": "open",
                "new_priority": "normal",
            },
            "audit": {
                "id": 2,
                "platform_admin_user_id": 3,
                "action": "platform_admin.support_case.create",
                "resource_type": "platform_support_cases",
                "resource_id": "9",
                "metadata": {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/support-cases",
                    "http_method": "POST",
                    "company_id": 31,
                    "status": "open",
                    "priority": "normal",
                },
            },
        }
        for key in ("event", "audit"):
            malformed = dict(result)
            malformed.pop(key)
            rpc = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=malformed))))
            with patch.object(platform_support_case_repository.supabase, "rpc", rpc):
                with self.assertRaises(RuntimeError):
                    platform_support_case_repository.create_support_case_for_platform_admin(
                        company_id=31,
                        platform_admin_user_id=3,
                        title="Safe",
                        redacted_summary="Safe summary",
                        status="open",
                        priority="normal",
                    )

    def test_reply_rpc_result_rejects_missing_reply_and_notification(self):
        for key in ("reply", "notification"):
            result = self._reply_rpc_result()
            result.pop(key)
            rpc = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=result))))
            with patch.object(platform_support_case_repository.supabase, "rpc", rpc):
                with self.assertRaises(RuntimeError):
                    platform_support_case_repository.create_support_case_reply_for_platform_admin(
                        9, 3, "Visible reply"
                    )

    def test_reply_rpc_result_rejects_wrong_event_type_and_reply_linkage(self):
        cases = [
            ("event", "event_type", "note_added"),
            ("event", "tenant_support_reply_id", 45),
        ]
        for section, field, value in cases:
            result = self._reply_rpc_result()
            result[section][field] = value
            rpc = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=result))))
            with patch.object(platform_support_case_repository.supabase, "rpc", rpc):
                with self.assertRaises(RuntimeError):
                    platform_support_case_repository.create_support_case_reply_for_platform_admin(
                        9, 3, "Visible reply"
                    )

    def test_reply_rpc_result_rejects_mismatched_request_case_company_linkage(self):
        cases = [
            ("case", "id", 10),
            ("event", "case_id", 10),
            ("reply", "platform_support_case_id", 10),
            ("reply", "company_id", 32),
            ("notification", "request_id", 13),
            ("notification", "platform_support_case_id", 10),
            ("notification", "company_id", 32),
        ]
        for section, field, value in cases:
            result = self._reply_rpc_result()
            result[section][field] = value
            rpc = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=result))))
            with patch.object(platform_support_case_repository.supabase, "rpc", rpc):
                with self.assertRaises(RuntimeError):
                    platform_support_case_repository.create_support_case_reply_for_platform_admin(
                        9, 3, "Visible reply"
                    )

    def test_reply_rpc_result_rejects_invalid_channel_status_and_ids(self):
        cases = [
            ("notification", "channel", "email"),
            ("notification", "status", "sent"),
            ("notification", "attempt_count", True),
            ("notification", "attempt_count", -1),
            ("event", "id", True),
            ("event", "id", 0),
            ("notification", "id", True),
            ("notification", "id", 0),
            ("reply", "id", True),
            ("reply", "id", 0),
            ("case", "company_id", False),
            ("reply", "request_id", 0),
        ]
        for section, field, value in cases:
            result = self._reply_rpc_result()
            result[section][field] = value
            rpc = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=result))))
            with patch.object(platform_support_case_repository.supabase, "rpc", rpc):
                with self.assertRaises(RuntimeError):
                    platform_support_case_repository.create_support_case_reply_for_platform_admin(
                        9, 3, "Visible reply"
                    )


if __name__ == "__main__":
    unittest.main()
