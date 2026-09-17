import io
import inspect
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from flask import Flask, g

from app import create_app
from app.database import platform_admin_repository, platform_company_repository
from app.routes import (
    billing_routes,
    bot_routes,
    broadcast_routes,
    chat_routes,
    crm_routes,
    knowledge_routes,
    profile_routes,
    telegram_routes,
    user_routes,
    wasender_routes,
    whatsapp_routes,
    widget_routes,
)
from app.services import platform_admin_service
from app.services import knowledge_service
from app.services.company_status_service import (
    CompanyOperationalStatusError,
    ensure_company_operational,
)
from app.utils import telegram_utils, whatsapp_utils
from app.services import ai_router, wasender_service


AUTH_USER = {
    "id": 1,
    "company_id": 42,
    "email": "admin@example.test",
    "full_name": "Admin",
    "role": "admin",
    "status": "active",
}


class PlatformCompanyLifecycleRepositoryTests(unittest.TestCase):
    def _rpc_result(self, *, action="platform_admin.company.suspend", old_status="active", new_status="inactive"):
        return {
            "company": {
                "id": 42,
                "old_status": old_status,
                "new_status": new_status,
                "updated_at": "2026-08-08T00:00:00+00:00",
            },
            "audit_event": {
                "id": 77,
                "action": action,
                "resource_type": "company",
                "resource_id": "42",
            },
        }

    def test_suspend_rpc_uses_expected_function_and_validates_result(self):
        rpc = MagicMock(return_value=MagicMock(execute=MagicMock(
            return_value=SimpleNamespace(data=self._rpc_result())
        )))
        with patch.object(platform_company_repository.supabase, "rpc", rpc):
            result = platform_company_repository.suspend_platform_company_for_platform_admin(3, 42)
        rpc.assert_called_once_with(
            "suspend_platform_company",
            {"p_actor_platform_admin_user_id": 3, "p_company_id": 42},
        )
        self.assertEqual(result["company"]["new_status"], "inactive")

    def test_restore_rpc_uses_expected_function_and_validates_result(self):
        rpc = MagicMock(return_value=MagicMock(execute=MagicMock(
            return_value=SimpleNamespace(data=self._rpc_result(
                action="platform_admin.company.restore",
                old_status="inactive",
                new_status="active",
            ))
        )))
        with patch.object(platform_company_repository.supabase, "rpc", rpc):
            result = platform_company_repository.restore_platform_company_for_platform_admin(3, 42)
        rpc.assert_called_once_with(
            "restore_platform_company",
            {"p_actor_platform_admin_user_id": 3, "p_company_id": 42},
        )
        self.assertEqual(result["company"]["new_status"], "active")

    def test_rpc_result_validation_fails_closed_for_malformed_data(self):
        cases = [
            ("company", None),
            ("audit_event", None),
            ("company.id", 43),
            ("company.old_status", "inactive"),
            ("company.new_status", "active"),
            ("company.updated_at", None),
            ("audit_event.id", True),
            ("audit_event.id", 0),
            ("audit_event.action", "platform_admin.company.restore"),
            ("audit_event.resource_type", "companies"),
            ("audit_event.resource_id", "43"),
        ]
        for dotted, value in cases:
            result = self._rpc_result()
            parts = dotted.split(".")
            if len(parts) == 1:
                result[parts[0]] = value
            else:
                result[parts[0]][parts[1]] = value
            rpc = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=result))))
            with self.subTest(dotted=dotted), patch.object(platform_company_repository.supabase, "rpc", rpc):
                with self.assertRaises(RuntimeError):
                    platform_company_repository.suspend_platform_company_for_platform_admin(3, 42)


class PlatformCompanyLifecycleServiceTests(unittest.TestCase):
    def test_lifecycle_services_reject_browser_supplied_fields(self):
        with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
            platform_admin_service.suspend_company(42, {"status": "inactive"}, 3)
        self.assertEqual(raised.exception.code, "invalid_request")

    def test_suspend_maps_known_rpc_errors_to_stable_codes(self):
        cases = [
            (RuntimeError("Company not found"), 404, "company_not_found"),
            (RuntimeError("Company status is unchanged"), 400, "no_change"),
            (RuntimeError("Protected platform-admin company cannot be suspended"), 400, "protected_company"),
            (RuntimeError("Active platform-admin mapping is required"), 403, "platform_admin_access_denied"),
        ]
        for exc, status, code in cases:
            with self.subTest(code=code), patch.object(
                platform_company_repository,
                "suspend_platform_company_for_platform_admin",
                side_effect=exc,
            ):
                with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                    platform_admin_service.suspend_company(42, {}, 3)
                self.assertEqual(raised.exception.status_code, status)
                self.assertEqual(raised.exception.code, code)

    def test_success_returns_refreshed_authoritative_state(self):
        with patch.object(
            platform_company_repository,
            "restore_platform_company_for_platform_admin",
            return_value={
                "company": {"id": 42, "old_status": "inactive", "new_status": "active", "updated_at": "now"},
                "audit_event": {"id": 9},
            },
        ) as repo:
            result = platform_admin_service.restore_company(42, {}, 3)
        self.assertEqual(result["company"]["new_status"], "active")
        repo.assert_called_once_with(3, 42)


class CompanyOperationalStatusGuardTests(unittest.TestCase):
    def test_active_company_allowed(self):
        with patch("app.services.company_status_service.get_company_status_by_id", return_value={"id": 4, "status": "active"}):
            self.assertEqual(ensure_company_operational(4)["status"], "active")

    def test_inactive_missing_null_and_unknown_company_fail_closed(self):
        cases = [
            ({"id": 4, "status": "inactive"}, "company_suspended", 403),
            ({"id": 4, "status": None}, "company_suspended", 403),
            ({"id": 4, "status": "paused"}, "company_suspended", 403),
            (None, "company_not_found", 403),
        ]
        for row, code, status in cases:
            with self.subTest(code=code), patch(
                "app.services.company_status_service.get_company_status_by_id",
                return_value=row,
            ):
                with self.assertRaises(CompanyOperationalStatusError) as raised:
                    ensure_company_operational(4)
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(raised.exception.status_code, status)

    def test_browser_jwt_status_cannot_override_database_status(self):
        app = Flask(__name__)
        with app.test_request_context("/"):
            g.company_id = 4
            g.jwt_claims = {"company_status": "active"}
            with patch(
                "app.services.company_status_service.get_company_status_by_id",
                return_value={"id": 4, "status": "inactive"},
            ):
                with self.assertRaises(CompanyOperationalStatusError) as raised:
                    ensure_company_operational(g.company_id)
        self.assertEqual(raised.exception.code, "company_suspended")


class TenantOperationalRouteGuardTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.headers = {"Authorization": "Bearer test-token"}

    def _auth(self):
        return (
            patch(
                "app.decorators.auth_decorator.jwt.decode",
                return_value={"user_id": 1, "company_id": 42, "role": "admin"},
            ),
            patch("app.database.user_repository.get_user_by_id", return_value=AUTH_USER),
            patch(
                "app.services.company_status_service.get_company_status_by_id",
                return_value={"id": 42, "status": "inactive"},
            ),
        )

    def _active_auth(self):
        return (
            patch(
                "app.decorators.auth_decorator.jwt.decode",
                return_value={"user_id": 1, "company_id": 42, "role": "admin"},
            ),
            patch("app.database.user_repository.get_user_by_id", return_value=AUTH_USER),
            patch(
                "app.services.company_status_service.get_company_status_by_id",
                return_value={"id": 42, "status": "active"},
            ),
        )

    class _Query:
        def __init__(self, rows):
            self.rows = rows

        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def execute(self):
            return SimpleNamespace(data=self.rows)

    class _Supabase:
        def __init__(self, table_rows):
            self.table_rows = {key: list(value) for key, value in table_rows.items()}

        def table(self, name):
            rows = self.table_rows.get(name, [])
            if rows and isinstance(rows[0], list):
                return TenantOperationalRouteGuardTests._Query(rows.pop(0))
            return TenantOperationalRouteGuardTests._Query(rows)

    def test_profile_create_and_delete_are_blocked_before_repository_mutation(self):
        auth, user, status = self._auth()
        with auth, user, status, \
             patch("app.routes.profile_routes.save_profile") as save_profile, \
             patch("app.routes.profile_routes.delete_profile") as delete_profile:
            create_response = self.client.post(
                "/api/profiles?chatbot_id=9",
                headers=self.headers,
                json={"name": "sales"},
            )
            delete_response = self.client.delete(
                "/api/profiles/sales?chatbot_id=9",
                headers=self.headers,
            )
        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(create_response.get_json()["code"], "company_suspended")
        self.assertEqual(delete_response.status_code, 403)
        self.assertEqual(delete_response.get_json()["code"], "company_suspended")
        save_profile.assert_not_called()
        delete_profile.assert_not_called()

    def test_team_role_and_status_are_blocked_before_billing_or_repository_mutation(self):
        auth, user, status = self._auth()
        with auth, user, status, \
             patch("app.routes.user_routes.get_user_by_id_for_company") as get_target, \
             patch("app.routes.user_routes.count_active_admins_by_company") as count_admins, \
             patch("app.routes.user_routes.can_add_team_member") as billing_check, \
             patch("app.routes.user_routes.update_user_for_company") as update_user:
            role_response = self.client.put(
                "/api/users/7/role",
                headers=self.headers,
                json={"role": "admin"},
            )
            status_response = self.client.put(
                "/api/users/7/status",
                headers=self.headers,
                json={"status": "active"},
            )
        self.assertEqual(role_response.status_code, 403)
        self.assertEqual(role_response.get_json()["code"], "company_suspended")
        self.assertEqual(status_response.status_code, 403)
        self.assertEqual(status_response.get_json()["code"], "company_suspended")
        get_target.assert_not_called()
        count_admins.assert_not_called()
        billing_check.assert_not_called()
        update_user.assert_not_called()

    def test_widget_dashboard_routes_are_blocked_before_implicit_or_explicit_writes(self):
        auth, user, status = self._auth()
        with auth, user, status, \
             patch("app.routes.widget_routes.ensure_widget") as ensure_widget, \
             patch("app.routes.widget_routes.update_widget_settings") as update_widget, \
             patch("app.routes.widget_routes.regenerate_public_key") as regenerate_key:
            get_response = self.client.get(
                "/api/bots/9/widget",
                headers=self.headers,
            )
            put_response = self.client.put(
                "/api/bots/9/widget",
                headers=self.headers,
                json={"is_enabled": True},
            )
            post_response = self.client.post(
                "/api/bots/9/widget/regenerate-key",
                headers=self.headers,
            )
        self.assertEqual(get_response.status_code, 403)
        self.assertEqual(put_response.status_code, 403)
        self.assertEqual(post_response.status_code, 403)
        ensure_widget.assert_not_called()
        update_widget.assert_not_called()
        regenerate_key.assert_not_called()

    def test_broadcast_create_and_start_are_blocked_before_dispatch_mutation(self):
        auth, user, status = self._auth()
        with auth, user, status, \
             patch("app.routes.broadcast_routes.create_campaign") as create_campaign, \
             patch("app.routes.broadcast_routes.create_broadcast_log") as create_log, \
             patch("app.routes.broadcast_routes.update_campaign_status") as update_status, \
             patch("app.routes.broadcast_routes.threading.Thread") as worker:
            create_response = self.client.post(
                "/api/broadcast/campaign?chatbot_id=9",
                headers=self.headers,
                json={
                    "name": "Campaign",
                    "message_template": "Hello",
                    "recipients": [{"phone": "+60123456789"}],
                },
            )
            start_response = self.client.post(
                "/api/broadcast/campaign/12/start?chatbot_id=9",
                headers=self.headers,
            )
        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(create_response.get_json()["code"], "company_suspended")
        self.assertEqual(start_response.status_code, 403)
        self.assertEqual(start_response.get_json()["code"], "company_suspended")
        create_campaign.assert_not_called()
        create_log.assert_not_called()
        update_status.assert_not_called()
        worker.assert_not_called()

    def test_chatbot_mutations_are_blocked_before_billing_or_repository_mutation(self):
        auth, user, status = self._auth()
        with auth, user, status, \
             patch("app.routes.bot_routes.can_create_chatbot") as can_create, \
             patch("app.routes.bot_routes.add_bot") as add_bot, \
             patch("app.routes.bot_routes.edit_bot") as edit_bot, \
             patch("app.routes.bot_routes.remove_bot") as remove_bot, \
             patch("app.routes.bot_routes.restore_archived_bot") as restore_bot, \
             patch("app.routes.bot_routes.permanently_delete_archived_bot") as permanent_delete:
            create_response = self.client.post(
                "/api/bots",
                headers=self.headers,
                json={"bot_name": "Sales"},
            )
            edit_response = self.client.put(
                "/api/bots/9",
                headers=self.headers,
                json={"bot_name": "Support"},
            )
            archive_response = self.client.delete(
                "/api/bots/9",
                headers=self.headers,
            )
            restore_response = self.client.post(
                "/api/bots/9/restore",
                headers=self.headers,
            )
            delete_response = self.client.delete(
                "/api/bots/9/permanent",
                headers=self.headers,
                json={"confirm_bot_name": "Sales"},
            )
        for response in [create_response, edit_response, archive_response, restore_response, delete_response]:
            with self.subTest(status=response.status_code):
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.get_json()["code"], "company_suspended")
        can_create.assert_not_called()
        add_bot.assert_not_called()
        edit_bot.assert_not_called()
        remove_bot.assert_not_called()
        restore_bot.assert_not_called()
        permanent_delete.assert_not_called()

    def test_knowledge_mutations_are_blocked_before_external_or_database_side_effects(self):
        auth, user, status = self._auth()
        with auth, user, status, \
             patch("app.routes.knowledge_routes.set_active_pdf") as set_active, \
             patch("app.routes.knowledge_routes.delete_pdf_file") as delete_file, \
             patch("app.routes.knowledge_routes.discover_website_links") as discover_links, \
             patch("app.routes.knowledge_routes.scrape_pages") as scrape_pages, \
             patch("app.routes.knowledge_routes.ingest_website_sources") as ingest:
            active_response = self.client.post(
                "/api/knowledge/set-active?chatbot_id=9",
                headers=self.headers,
                json={"file_name": "guide.pdf"},
            )
            delete_response = self.client.delete(
                "/api/knowledge/files/guide.pdf?chatbot_id=9",
                headers=self.headers,
            )
            analyze_response = self.client.post(
                "/api/knowledge/scrape-analyze?chatbot_id=9",
                headers=self.headers,
                json={"url": "https://example.test"},
            )
            extract_response = self.client.post(
                "/api/knowledge/scrape-extract?chatbot_id=9",
                headers=self.headers,
                json={"urls": ["https://example.test"]},
            )
            ingest_response = self.client.post(
                "/api/knowledge/ingest?chatbot_id=9",
                headers=self.headers,
                json={"sources": ["https://example.test"]},
            )
        for response in [active_response, delete_response, analyze_response, extract_response, ingest_response]:
            with self.subTest(status=response.status_code):
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.get_json()["code"], "company_suspended")
        set_active.assert_not_called()
        delete_file.assert_not_called()
        discover_links.assert_not_called()
        scrape_pages.assert_not_called()
        ingest.assert_not_called()

    def test_knowledge_graph_existing_graph_remains_readable_for_inactive_company(self):
        auth, user, status = self._auth()
        fake_supabase = self._Supabase({
            "knowledge_graph_nodes": [
                [{"id": 1}],
                [{"name": "support", "label": "Topic", "properties": {"description": "Help"}}],
            ],
            "knowledge_graph_edges": [[]],
        })
        with auth, user, status, \
             patch("app.routes.knowledge_routes.verify_chatbot_access", return_value={"company_id": 42}), \
             patch("app.database.knowledge_file_repository.get_active_pdf_knowledge_file", return_value={"id": 5, "file_name": "guide.pdf"}), \
             patch("app.database.db.supabase", fake_supabase), \
             patch("app.routes.knowledge_routes.ensure_company_operational", side_effect=AssertionError("read-only graph should not require operational status")) as ensure_operational, \
             patch("app.services.knowledge_service.extract_and_store_graph_supabase") as extract_graph:
            response = self.client.get(
                "/api/knowledge/graph?chatbot_id=9",
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "success")
        ensure_operational.assert_not_called()
        extract_graph.assert_not_called()

    def test_knowledge_graph_missing_graph_is_blocked_before_self_healing_side_effects(self):
        auth, user, status = self._auth()
        fake_supabase = self._Supabase({
            "knowledge_graph_nodes": [[]],
        })
        with auth, user, status, \
             patch("app.routes.knowledge_routes.verify_chatbot_access", return_value={"company_id": 42}), \
             patch("app.database.knowledge_file_repository.get_active_pdf_knowledge_file", return_value={"id": 5, "file_name": "guide.pdf"}), \
             patch("app.database.db.supabase", fake_supabase), \
             patch("app.database.knowledge_chunk_repository.get_chunks_by_file_for_chatbot") as get_chunks, \
             patch("app.services.rag_service.generate_embedding") as generate_embedding, \
             patch("app.database.knowledge_chunk_repository.save_knowledge_chunk") as save_chunk, \
             patch("app.services.knowledge_service.extract_and_store_graph_supabase") as extract_graph:
            response = self.client.get(
                "/api/knowledge/graph?chatbot_id=9",
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "company_suspended")
        get_chunks.assert_not_called()
        generate_embedding.assert_not_called()
        save_chunk.assert_not_called()
        extract_graph.assert_not_called()

    def test_pdf_upload_is_blocked_before_file_or_rag_side_effects(self):
        auth, user, status = self._auth()
        with auth, user, status, \
             patch("app.views.verify_chatbot_access") as verify_access, \
             patch("app.views.can_upload_knowledge_file") as file_limit, \
             patch("app.views.can_upload_knowledge_storage") as storage_limit, \
             patch("app.views.save_uploaded_pdf") as save_pdf, \
             patch("app.views.derive_persona_for_upload") as derive_persona:
            response = self.client.post(
                "/upload-pdf?chatbot_id=9",
                headers=self.headers,
                data={"pdf_file": (io.BytesIO(b"%PDF-1.4\n"), "guide.pdf")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "company_suspended")
        verify_access.assert_not_called()
        file_limit.assert_not_called()
        storage_limit.assert_not_called()
        save_pdf.assert_not_called()
        derive_persona.assert_not_called()

    def test_test_chat_is_blocked_before_ai_router_for_inactive_company(self):
        auth, user, status = self._auth()
        with auth, user, status, \
             patch("app.routes.chat_routes.verify_chatbot_access") as verify_access, \
             patch("app.routes.chat_routes.generate_response") as generate_response:
            response = self.client.post(
                "/api/chat/test?chatbot_id=9",
                headers=self.headers,
                json={"message": "Hello"},
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "company_suspended")
        verify_access.assert_not_called()
        generate_response.assert_not_called()

    def test_test_chat_active_company_success_contract_is_unchanged(self):
        auth, user, status = self._active_auth()
        with auth, user, status, \
             patch("app.routes.chat_routes.verify_chatbot_access", return_value={"id": 9, "company_id": 42}) as verify_access, \
             patch("app.routes.chat_routes.get_or_create_conversation", return_value={"id": 100}), \
             patch("app.routes.chat_routes.generate_response", return_value="Hello back") as generate_response:
            response = self.client.post(
                "/api/chat/test?chatbot_id=9",
                headers=self.headers,
                json={"message": "Hello"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "success", "reply": "Hello back"})
        verify_access.assert_called_once_with(9)
        generate_response.assert_called_once_with(
            "Hello",
            "test_user",
            chatbot_id=9,
            source_channel="web",
            operation_type=chat_routes.OPERATION_TEST_CHAT,
            conversation_id=100,
        )

    def test_refinement_questions_are_blocked_before_sse_or_ai_generation(self):
        auth, user, status = self._auth()
        with auth, user, status, \
             patch("app.routes.knowledge_routes.verify_chatbot_access") as verify_access, \
             patch("app.services.ai_router.generate_system_response") as generate_response, \
             patch("app.services.rag_service.generate_embedding") as generate_embedding:
            response = self.client.get(
                "/api/knowledge/refinement/questions?chatbot_id=9",
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.content_type, "application/json")
        self.assertEqual(response.get_json()["code"], "company_suspended")
        verify_access.assert_not_called()
        generate_response.assert_not_called()
        generate_embedding.assert_not_called()

    def test_readme_get_existing_file_remains_readable_for_inactive_company(self):
        auth, user, status = self._auth()
        with tempfile.TemporaryDirectory() as tmpdir:
            readme_path = os.path.join(tmpdir, "bot_9_5_readme.md")
            with open(readme_path, "w", encoding="utf-8") as handle:
                handle.write("# Existing README")
            with auth, user, status, \
                 patch.object(knowledge_service, "DATA_FOLDER", tmpdir), \
                 patch("app.routes.knowledge_routes.verify_chatbot_access", return_value={"company_id": 42}), \
                 patch("app.database.knowledge_file_repository.get_active_pdf_knowledge_file", return_value={"id": 5, "file_name": "guide.pdf"}), \
                 patch("app.services.knowledge_service.generate_and_save_knowledge_readme") as generate_readme:
                response = self.client.get(
                    "/api/knowledge/readme?chatbot_id=9&file_id=5",
                    headers=self.headers,
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["content"], "# Existing README")
        generate_readme.assert_not_called()

    def test_readme_get_missing_file_is_blocked_before_generation_for_inactive_company(self):
        auth, user, status = self._auth()
        with tempfile.TemporaryDirectory() as tmpdir:
            with auth, user, status, \
                 patch.object(knowledge_service, "DATA_FOLDER", tmpdir), \
                 patch("app.routes.knowledge_routes.verify_chatbot_access", return_value={"company_id": 42}), \
                 patch("app.database.knowledge_file_repository.get_active_pdf_knowledge_file", return_value={"id": 5, "file_name": "guide.pdf"}), \
                 patch("app.services.knowledge_service.generate_and_save_knowledge_readme") as generate_readme:
                response = self.client.get(
                    "/api/knowledge/readme?chatbot_id=9&file_id=5",
                    headers=self.headers,
                )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "company_suspended")
        generate_readme.assert_not_called()

    def test_crm_mutations_are_blocked_before_feature_or_repository_mutation(self):
        auth, user, status = self._auth()
        with auth, user, status, \
             patch("app.routes.crm_routes.can_use_plan_feature") as feature_gate, \
             patch("app.routes.crm_routes.verify_chatbot_access") as verify_access, \
             patch("app.routes.crm_routes.update_crm_lead_status_notes") as update_lead, \
             patch("app.routes.crm_routes.upsert_crm_lead_by_conversation") as upsert_lead:
            update_response = self.client.patch(
                "/api/crm/leads/7",
                headers=self.headers,
                json={"chatbot_id": 9, "status": "qualified", "assigned_to": 5},
            )
            upsert_response = self.client.post(
                "/api/crm/leads/upsert",
                headers=self.headers,
                json={"chatbot_id": 9, "conversation_id": 22, "assigned_to": 5},
            )
        self.assertEqual(update_response.status_code, 403)
        self.assertEqual(update_response.get_json()["code"], "company_suspended")
        self.assertEqual(upsert_response.status_code, 403)
        self.assertEqual(upsert_response.get_json()["code"], "company_suspended")
        feature_gate.assert_not_called()
        verify_access.assert_not_called()
        update_lead.assert_not_called()
        upsert_lead.assert_not_called()

    def test_integration_config_mutations_are_blocked_before_provider_or_channel_writes(self):
        auth, user, status = self._auth()
        with auth, user, status, \
             patch("app.routes.telegram_routes.validate_telegram_bot_token") as telegram_validate, \
             patch("app.routes.telegram_routes.create_telegram_channel") as create_telegram, \
             patch("app.routes.telegram_routes.delete_telegram_webhook") as delete_telegram_hook, \
             patch("app.routes.wasender_routes.create_wasender_channel") as create_wasender, \
             patch("app.routes.wasender_routes.disconnect_wasender_channel") as disconnect_wasender, \
             patch("app.routes.whatsapp_routes.exchange_embedded_signup_code") as meta_exchange, \
             patch("app.routes.whatsapp_routes.upsert_whatsapp_channel_by_phone_number_id") as upsert_whatsapp, \
             patch("app.routes.whatsapp_routes.disconnect_whatsapp_channel_record") as disconnect_whatsapp:
            telegram_connect = self.client.post(
                "/api/telegram/connect?chatbot_id=9",
                headers=self.headers,
                json={"bot_token": "123:abc"},
            )
            telegram_disconnect = self.client.put(
                "/api/telegram/channels/4/disconnect?chatbot_id=9",
                headers=self.headers,
            )
            wasender_connect = self.client.post(
                "/api/wasender/connect?chatbot_id=9",
                headers=self.headers,
                json={"api_key": "secret", "phone_number": "+60123456789"},
            )
            wasender_disconnect = self.client.put(
                "/api/wasender/channels/4/disconnect?chatbot_id=9",
                headers=self.headers,
            )
            whatsapp_connect = self.client.post(
                "/api/whatsapp/embedded-signup/complete?chatbot_id=9",
                headers=self.headers,
                json={"code": "code", "waba_id": "waba", "phone_number_id": "phone"},
            )
            whatsapp_disconnect = self.client.put(
                "/api/whatsapp/channels/4/disconnect?chatbot_id=9",
                headers=self.headers,
            )
        for response in [
            telegram_connect,
            telegram_disconnect,
            wasender_connect,
            wasender_disconnect,
            whatsapp_connect,
            whatsapp_disconnect,
        ]:
            with self.subTest(status=response.status_code):
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.get_json()["code"], "company_suspended")
        telegram_validate.assert_not_called()
        create_telegram.assert_not_called()
        delete_telegram_hook.assert_not_called()
        create_wasender.assert_not_called()
        disconnect_wasender.assert_not_called()
        meta_exchange.assert_not_called()
        upsert_whatsapp.assert_not_called()
        disconnect_whatsapp.assert_not_called()

    def test_broadcast_worker_fails_closed_if_company_suspends_after_scheduling(self):
        auth, user, status = self._auth()
        campaign = {
            "id": 12,
            "company_id": 42,
            "chatbot_id": 9,
            "channel_type": "whatsapp",
            "message_template": "Hello",
        }
        pending_logs = [{"id": 100, "recipient_phone": "+60123456789", "status": "pending"}]
        with auth, user, status, \
             patch("app.routes.broadcast_routes.update_broadcast_log_status") as update_log, \
             patch("app.routes.broadcast_routes.update_campaign_status") as update_status:
            broadcast_routes.process_broadcast_dispatch(create_app(), campaign, pending_logs)
        update_log.assert_called_once_with(
            100,
            "failed",
            error_message="Company is suspended.",
        )
        update_status.assert_called_once_with(12, 42, "failed")
        self.assertNotIn(
            call(100, "sending"),
            update_log.call_args_list,
        )

    def test_broadcast_worker_stops_before_current_and_remaining_recipient_when_suspended_mid_dispatch(self):
        campaign = {
            "id": 12,
            "company_id": 42,
            "chatbot_id": 9,
            "channel_type": "whatsapp",
            "message_template": "Hello {{phone}}",
        }
        pending_logs = [
            {"id": 100, "recipient_phone": "+60111111111", "status": "pending"},
            {"id": 101, "recipient_phone": "+60222222222", "status": "pending"},
            {"id": 102, "recipient_phone": "+60333333333", "status": "pending"},
        ]
        status_rows = [
            {"id": 42, "status": "active"},
            {"id": 42, "status": "active"},
            {"id": 42, "status": "inactive"},
        ]
        with patch(
            "app.services.company_status_service.get_company_status_by_id",
            side_effect=status_rows,
        ), patch(
            "app.database.whatsapp_channel_repository.get_whatsapp_channels_by_chatbot",
            return_value=[{"id": 1, "is_active": True, "access_token": "token"}],
        ), patch(
            "app.utils.whatsapp_utils.send_message",
            return_value=SimpleNamespace(status_code=200, text="ok"),
        ) as send_message, patch(
            # The worker re-reads the campaign between messages to see
            # whether the operator pressed stop. These tests are about
            # suspension, not cancellation, so it always answers "sending".
            "app.routes.broadcast_routes.get_campaign_by_id",
            return_value={"id": 12, "company_id": 42, "status": "sending"},
        ), patch(
            "app.routes.broadcast_routes.update_broadcast_log_status"
        ) as update_log, patch(
            "app.routes.broadcast_routes.update_campaign_status"
        ) as update_status:
            broadcast_routes.process_broadcast_dispatch(create_app(), campaign, pending_logs)

        send_message.assert_called_once()
        self.assertIn(call(100, "sending"), update_log.call_args_list)
        self.assertTrue(any(args[0] == 100 and args[1] == "sent" for args, _kwargs in update_log.call_args_list))
        self.assertIn(
            call(101, "failed", error_message="Company is suspended."),
            update_log.call_args_list,
        )
        self.assertIn(
            call(102, "failed", error_message="Company is suspended."),
            update_log.call_args_list,
        )
        self.assertNotIn(call(101, "sending"), update_log.call_args_list)
        self.assertNotIn(call(102, "sending"), update_log.call_args_list)
        update_status.assert_called_with(12, 42, "failed")


class SystemAiCompanyStatusTests(unittest.TestCase):
    def _active_bot(self, company_id=42):
        return {
            "id": 9,
            "company_id": company_id,
            "ai_provider": "deepseek",
            "model_name": "deepseek-chat",
        }

    def test_generate_system_response_checks_company_before_provider_credit_or_usage(self):
        cases = [
            {"id": 42, "status": "inactive"},
            {"id": 42, "status": None},
            {"id": 42, "status": "paused"},
            None,
        ]
        for company_row in cases:
            with self.subTest(company_row=company_row), \
                 patch.object(
                     ai_router,
                     "get_bot_by_id",
                     return_value=self._active_bot(),
                 ), \
                 patch(
                     "app.services.company_status_service.get_company_status_by_id",
                     return_value=company_row,
                 ), \
                 patch.object(ai_router, "_get_system_provider_for_enforcement") as provider_gate, \
                 patch.object(ai_router, "_check_ai_credit_before_provider") as credit_check, \
                 patch.object(ai_router, "_call_deepseek_direct") as deepseek_call, \
                 patch.object(ai_router, "_make_usage_log") as usage_log:
                with self.assertRaises((CompanyOperationalStatusError, RuntimeError)):
                    ai_router.generate_system_response("Summarize", 9)
                provider_gate.assert_not_called()
                credit_check.assert_not_called()
                deepseek_call.assert_not_called()
                usage_log.assert_not_called()

    def test_generate_system_response_does_not_fallback_through_request_context_without_bot_company(self):
        app = Flask(__name__)
        with app.test_request_context("/"):
            g.company_id = 42
            with patch.object(ai_router, "get_bot_by_id", return_value=None), \
                 patch.object(ai_router, "_call_deepseek_direct") as deepseek_call:
                with self.assertRaises(RuntimeError):
                    ai_router.generate_system_response("Summarize", 9)
        deepseek_call.assert_not_called()

    def test_generate_system_response_passes_bot_company_id_to_provider_enforcement(self):
        with patch.object(ai_router, "get_bot_by_id", return_value=self._active_bot(42)), \
             patch(
                 "app.services.company_status_service.get_company_status_by_id",
                 return_value={"id": 42, "status": "active"},
             ), \
             patch.object(
                 ai_router,
                 "_get_system_provider_for_enforcement",
                 return_value=("deepseek", "deepseek-chat"),
             ) as provider_gate, \
             patch.object(
                 ai_router,
                 "_call_deepseek_direct",
                 return_value=ai_router._make_result_from_text("Done", "deepseek", "deepseek-chat"),
             ), \
             patch.object(ai_router, "_check_ai_credit_before_provider"), \
            patch.object(ai_router, "_make_usage_log"):
            self.assertEqual(ai_router.generate_system_response("Summarize", 9), "Done")
        provider_gate.assert_called_once()
        self.assertEqual(provider_gate.call_args.args[2], 42)

    def test_system_provider_enforcement_uses_authoritative_company_without_request_context(self):
        policy = SimpleNamespace(allowed=True, api_route=ai_router.ROUTE_DIRECT_DEEPSEEK, denial_reason=None)
        with patch("app.services.ai_access_policy.resolve_ai_access", return_value=policy) as resolve, \
             patch.object(ai_router, "_validate_deepseek_pricing_config"):
            provider, model = ai_router._get_system_provider_for_enforcement(
                ai_router.TRIAL_PROVIDER,
                "ignored-model",
                42,
            )
        resolve.assert_called_once_with(42)
        self.assertEqual(provider, ai_router.TRIAL_PROVIDER)
        self.assertEqual(model, ai_router.TRIAL_MODEL)

    def test_denied_system_ai_policy_prevents_provider_call(self):
        policy = SimpleNamespace(
            allowed=False,
            api_route=ai_router.ROUTE_DIRECT_DEEPSEEK,
            denial_reason="AI is not available.",
        )
        with patch.object(ai_router, "get_bot_by_id", return_value=self._active_bot(42)), \
             patch(
                 "app.services.company_status_service.get_company_status_by_id",
                 return_value={"id": 42, "status": "active"},
             ), \
             patch("app.services.ai_access_policy.resolve_ai_access", return_value=policy), \
             patch.object(ai_router, "_call_deepseek_direct") as deepseek_call, \
             patch.object(ai_router, "_check_ai_credit_before_provider") as credit_check, \
             patch.object(ai_router, "_make_usage_log") as usage_log:
            with self.assertRaises(ai_router.BillingLimitError):
                ai_router.generate_system_response("Summarize", 9)
        deepseek_call.assert_not_called()
        credit_check.assert_not_called()
        usage_log.assert_not_called()

    def test_missing_system_ai_company_id_fails_before_provider_credit_or_usage(self):
        with patch.object(ai_router, "get_bot_by_id", return_value=self._active_bot(None)), \
             patch.object(ai_router, "_get_system_provider_for_enforcement") as provider_gate, \
             patch.object(ai_router, "_call_deepseek_direct") as deepseek_call, \
             patch.object(ai_router, "_check_ai_credit_before_provider") as credit_check, \
             patch.object(ai_router, "_make_usage_log") as usage_log:
            with self.assertRaises(CompanyOperationalStatusError):
                ai_router.generate_system_response("Summarize", 9)
        provider_gate.assert_not_called()
        deepseek_call.assert_not_called()
        credit_check.assert_not_called()
        usage_log.assert_not_called()

    def test_request_context_company_cannot_override_bot_company_for_system_ai(self):
        app = Flask(__name__)
        policy = SimpleNamespace(allowed=True, api_route=ai_router.ROUTE_DIRECT_DEEPSEEK, denial_reason=None)
        with app.test_request_context("/"):
            g.company_id = 99
            with patch.object(ai_router, "get_bot_by_id", return_value=self._active_bot(42)), \
                 patch(
                     "app.services.company_status_service.get_company_status_by_id",
                     return_value={"id": 42, "status": "active"},
                 ) as status_lookup, \
                 patch("app.services.ai_access_policy.resolve_ai_access", return_value=policy) as resolve, \
                 patch.object(ai_router, "_validate_deepseek_pricing_config"), \
                 patch.object(
                     ai_router,
                     "_call_deepseek_direct",
                     return_value=ai_router._make_result_from_text("Done", "deepseek", "deepseek-chat"),
                 ), \
                 patch.object(ai_router, "_check_ai_credit_before_provider"), \
                 patch.object(ai_router, "_make_usage_log"):
                self.assertEqual(ai_router.generate_system_response("Summarize", 9), "Done")
        status_lookup.assert_called_once_with(42)
        resolve.assert_called_once_with(42)


class CompanyOperationalStatusEnforcementSourceTests(unittest.TestCase):
    def test_high_impact_entry_points_use_company_operational_guard(self):
        guarded_sources = [
            inspect.getsource(ai_router.generate_response),
            inspect.getsource(ai_router.generate_system_response),
            inspect.getsource(widget_routes._load_widget_or_error),
            inspect.getsource(telegram_utils.process_telegram_update),
            inspect.getsource(wasender_service.process_wasender_webhook),
            inspect.getsource(whatsapp_utils.process_whatsapp_message),
        ]
        for source in guarded_sources:
            with self.subTest(source=source[:80]):
                self.assertIn("ensure_company_operational", source)

    def test_billing_mutation_routes_require_company_operational_guard(self):
        guarded_routes = [
            billing_routes.toyyibpay_checkout,
            billing_routes.subscription_checkout,
            billing_routes.retry_subscription_order,
            billing_routes.cancel_subscription,
            billing_routes.undo_cancel_subscription,
            billing_routes.schedule_downgrade,
            billing_routes.clear_downgrade,
        ]
        for route in guarded_routes:
            with self.subTest(route=route.__name__):
                source = inspect.getsource(route)
                self.assertIn("company_operational_required", source)

    def test_phase5_operational_mutation_inventory_is_guarded(self):
        guarded_routes = [
            bot_routes.create_new_bot,
            bot_routes.update_existing_bot,
            bot_routes.delete_existing_bot,
            bot_routes.restore_existing_bot,
            bot_routes.permanently_delete_existing_bot,
            bot_routes.generate_bot_welcome_menu,
            profile_routes.update_workspace,
            user_routes.update_current_user,
            user_routes.change_password,
            profile_routes.create_profile,
            profile_routes.remove_profile,
            user_routes.update_member_role,
            user_routes.update_member_status,
            widget_routes.get_bot_widget,
            widget_routes.put_bot_widget,
            widget_routes.post_regenerate_widget_key,
            broadcast_routes.save_campaign,
            broadcast_routes.start_campaign,
            billing_routes.toyyibpay_checkout,
            billing_routes.subscription_checkout,
            billing_routes.retry_subscription_order,
            billing_routes.cancel_subscription,
            billing_routes.undo_cancel_subscription,
            billing_routes.schedule_downgrade,
            billing_routes.clear_downgrade,
            chat_routes.test_chat,
            knowledge_routes.set_current_active_pdf,
            knowledge_routes.toggle_supporting_knowledge_source,
            knowledge_routes.delete_uploaded_pdf,
            knowledge_routes.scrape_website_knowledge,
            knowledge_routes.scrape_analyze_website,
            knowledge_routes.scrape_batch_website,
            knowledge_routes.scrape_extract_website,
            knowledge_routes.scrape_embed_website,
            knowledge_routes.ingest_knowledge_sources,
            knowledge_routes.submit_refinement_answers,
            knowledge_routes.save_graph_node,
            knowledge_routes.delete_graph_node_route,
            knowledge_routes.save_graph_edge,
            knowledge_routes.delete_graph_edge_route,
            crm_routes.update_crm_lead,
            crm_routes.upsert_crm_lead,
            telegram_routes.connect_telegram,
            telegram_routes.disconnect_telegram_channel,
            telegram_routes.reconnect_telegram_channel,
            wasender_routes.connect_wasender,
            wasender_routes.disconnect_wasender,
            whatsapp_routes.complete_embedded_signup,
            whatsapp_routes.disconnect_whatsapp_channel,
        ]
        for route in guarded_routes:
            with self.subTest(route=route.__name__):
                self.assertIn(
                    "company_operational_required",
                    inspect.getsource(route),
                )

    def test_outbound_messaging_boundary_is_authoritatively_guarded_at_application_entry_points(self):
        guarded_sources = {
            "broadcast_worker": inspect.getsource(broadcast_routes.process_broadcast_dispatch),
            "telegram_inbound": inspect.getsource(telegram_utils.process_telegram_update),
            "wasender_inbound": inspect.getsource(wasender_service.process_wasender_webhook),
            "whatsapp_inbound": inspect.getsource(whatsapp_utils.process_whatsapp_message),
            "widget_public": inspect.getsource(widget_routes._load_widget_or_error),
        }
        for name, source in guarded_sources.items():
            with self.subTest(name=name):
                self.assertIn("ensure_company_operational", source)
        self.assertIn("send_wasender_text_message", inspect.getsource(broadcast_routes.process_broadcast_dispatch))
        self.assertIn("send_telegram_message", inspect.getsource(telegram_utils._process_claimed_telegram_update))
        self.assertIn("send_message", inspect.getsource(whatsapp_utils._process_claimed_whatsapp_message))

    def test_suspended_company_tests_explicitly_override_autouse_active_baseline(self):
        source = inspect.getsource(TenantOperationalRouteGuardTests._auth)
        self.assertIn('"status": "inactive"', source)
        self.assertIn("get_company_status_by_id", source)


class PlatformCompanyLifecycleAuditSchemaTests(unittest.TestCase):
    def test_suspend_and_restore_audit_metadata_is_allowlisted(self):
        for action, old_status, new_status, endpoint in [
            (
                "platform_admin.company.suspend",
                "active",
                "inactive",
                "/api/platform-admin/companies/<company_id>/suspend",
            ),
            (
                "platform_admin.company.restore",
                "inactive",
                "active",
                "/api/platform-admin/companies/<company_id>/restore",
            ),
        ]:
            with self.subTest(action=action):
                platform_admin_repository.validate_audit_event(
                    3,
                    action,
                    "company",
                    "42",
                    {
                        "outcome": "success",
                        "endpoint": endpoint,
                        "http_method": "POST",
                        "company_id": 42,
                        "old_status": old_status,
                        "new_status": new_status,
                    },
                )

    def test_audit_metadata_rejects_wrong_status_and_secrets(self):
        with self.assertRaises(ValueError):
            platform_admin_repository.validate_audit_event(
                3,
                "platform_admin.company.suspend",
                "company",
                "42",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>/suspend",
                    "http_method": "POST",
                    "company_id": 42,
                    "old_status": "inactive",
                    "new_status": "inactive",
                },
            )
        with self.assertRaises(ValueError):
            platform_admin_repository.validate_audit_event(
                3,
                "platform_admin.company.restore",
                "company",
                "42",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>/restore",
                    "http_method": "POST",
                    "company_id": 42,
                    "old_status": "inactive",
                    "new_status": "active",
                    "secret_reason": "nope",
                },
            )
