"""Focused regressions for safe chatbot archive/soft-delete behavior."""

from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask, g


class _Response:
    def __init__(self, data=None, count=None):
        self.data = data or []
        self.count = count


class _Query:
    def __init__(self, response=None):
        self.response = response or _Response()
        self.table_name = None
        self.updated_payload = None
        self.delete_called = False
        self.eq_calls = []
        self.neq_calls = []
        self.is_calls = []
        self.select_args = None

    def table(self, table_name):
        self.table_name = table_name
        return self

    def select(self, *args, **kwargs):
        self.select_args = (args, kwargs)
        return self

    def update(self, payload):
        self.updated_payload = payload
        return self

    def delete(self):
        self.delete_called = True
        raise AssertionError("Bot archive flow must not call Supabase delete()")

    def eq(self, field, value):
        self.eq_calls.append((field, value))
        return self

    def neq(self, field, value):
        self.neq_calls.append((field, value))
        return self

    def is_(self, field, value):
        self.is_calls.append((field, value))
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def execute(self):
        return self.response


class _DeleteQuery:
    def __init__(self, table_name, response):
        self.table_name = table_name
        self.response = response
        self.eq_calls = []

    def delete(self):
        return self

    def eq(self, field, value):
        self.eq_calls.append((field, value))
        return self

    def execute(self):
        return self.response


class _DeleteTrackingSupabase:
    def __init__(self):
        self.queries = []

    def table(self, table_name):
        query = _DeleteQuery(table_name, _Response(data=[{"table": table_name}]))
        self.queries.append(query)
        return query


class _RpcCall:
    def __init__(self, data):
        self.response = _Response(data=data)

    def execute(self):
        return self.response


class _RpcSupabase:
    def __init__(self, data):
        self.data = data
        self.rpc_calls = []

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return _RpcCall(self.data)


class TestBotArchiveSoftDelete(unittest.TestCase):
    def test_archive_bot_updates_soft_delete_fields_without_delete(self):
        from app.database import bot_repository

        query = _Query(_Response(data=[{"id": 7, "status": "archived"}]))

        with patch.object(bot_repository, "supabase", query):
            archived = bot_repository.archive_bot(7, 42)

        self.assertEqual(archived["id"], 7)
        self.assertFalse(query.delete_called)
        self.assertEqual(query.table_name, "chatbots")
        self.assertEqual(query.updated_payload["status"], "archived")
        self.assertFalse(query.updated_payload["is_active"])
        self.assertIn("deleted_at", query.updated_payload)
        self.assertIn("updated_at", query.updated_payload)
        self.assertIn(("id", 7), query.eq_calls)
        self.assertIn(("company_id", 42), query.eq_calls)
        self.assertIn(("deleted_at", "null"), query.is_calls)
        self.assertIn(("status", "archived"), query.neq_calls)

    def test_default_bot_list_hides_archived_bots(self):
        from app.database import bot_repository

        query = _Query(_Response(data=[{"id": 1, "status": "active"}]))

        with patch.object(bot_repository, "supabase", query):
            bots = bot_repository.get_all_bots(42)

        self.assertEqual(len(bots), 1)
        self.assertIn(("company_id", 42), query.eq_calls)
        self.assertIn(("deleted_at", "null"), query.is_calls)
        self.assertIn(("status", "archived"), query.neq_calls)

    def test_archived_bot_list_filters_archived_bots(self):
        from app.database import bot_repository

        query = _Query(_Response(data=[{"id": 7, "status": "archived"}]))

        with patch.object(bot_repository, "supabase", query):
            bots = bot_repository.get_archived_bots(42)

        self.assertEqual(len(bots), 1)
        self.assertIn(("company_id", 42), query.eq_calls)
        self.assertIn(("status", "archived"), query.eq_calls)
        self.assertNotIn(("deleted_at", "null"), query.is_calls)

    def test_get_bot_by_id_rejects_archived_by_default(self):
        from app.database import bot_repository

        query = _Query(_Response(data=[]))

        with patch.object(bot_repository, "supabase", query):
            bot = bot_repository.get_bot_by_id(7, 42)

        self.assertIsNone(bot)
        self.assertIn(("deleted_at", "null"), query.is_calls)
        self.assertIn(("status", "archived"), query.neq_calls)

    def test_get_bot_by_id_can_include_archived_for_archive_operation(self):
        from app.database import bot_repository

        query = _Query(_Response(data=[{"id": 7, "status": "archived"}]))

        with patch.object(bot_repository, "supabase", query):
            bot = bot_repository.get_bot_by_id(7, 42, include_archived=True)

        self.assertEqual(bot["id"], 7)
        self.assertNotIn(("deleted_at", "null"), query.is_calls)
        self.assertNotIn(("status", "archived"), query.neq_calls)

    def test_remove_bot_uses_archive_function(self):
        from app.services import bot_service

        with patch.object(
            bot_service,
            "get_bot_by_id",
            return_value={"id": 7, "company_id": 42},
        ) as mock_get, patch.object(
            bot_service,
            "archive_bot",
            return_value={"id": 7, "status": "archived"},
        ) as mock_archive:
            result = bot_service.remove_bot(7, 42)

        self.assertEqual(result["status"], "archived")
        mock_get.assert_called_once_with(7, 42, include_archived=True)
        mock_archive.assert_called_once_with(7, 42)

    def test_restore_bot_updates_active_fields(self):
        from app.database import bot_repository

        query = _Query(_Response(data=[{"id": 7, "status": "active"}]))

        with patch.object(bot_repository, "supabase", query):
            restored = bot_repository.restore_bot(7, 42)

        self.assertEqual(restored["id"], 7)
        self.assertFalse(query.delete_called)
        self.assertEqual(query.table_name, "chatbots")
        self.assertEqual(query.updated_payload["status"], "active")
        self.assertTrue(query.updated_payload["is_active"])
        self.assertIsNone(query.updated_payload["deleted_at"])
        self.assertIn("updated_at", query.updated_payload)
        self.assertIn(("id", 7), query.eq_calls)
        self.assertIn(("company_id", 42), query.eq_calls)
        self.assertIn(("status", "archived"), query.eq_calls)

    def test_restore_archived_bot_enforces_chatbot_limit(self):
        from app.services import bot_service
        from app.services.billing_guard import BillingLimitError

        with patch.object(
            bot_service,
            "get_bot_by_id",
            return_value={"id": 7, "company_id": 42, "status": "archived"},
        ) as mock_get, patch(
            "app.services.billing_guard.can_create_chatbot",
            side_effect=BillingLimitError("Chatbot limit reached", code="chatbot_limit"),
        ) as mock_limit, patch.object(bot_service, "restore_bot") as mock_restore:
            with self.assertRaises(BillingLimitError) as ctx:
                bot_service.restore_archived_bot(7, 42)

        self.assertEqual(ctx.exception.code, "chatbot_limit")
        mock_get.assert_called_once_with(7, 42, include_archived=True)
        mock_limit.assert_called_once_with(42)
        mock_restore.assert_not_called()

    def test_restore_archived_bot_restores_after_limit_check(self):
        from app.services import bot_service

        with patch.object(
            bot_service,
            "get_bot_by_id",
            return_value={"id": 7, "company_id": 42, "status": "archived"},
        ) as mock_get, patch(
            "app.services.billing_guard.can_create_chatbot",
            return_value=True,
        ) as mock_limit, patch.object(
            bot_service,
            "restore_bot",
            return_value={"id": 7, "status": "active"},
        ) as mock_restore:
            restored = bot_service.restore_archived_bot(7, 42)

        self.assertEqual(restored["status"], "active")
        mock_get.assert_called_once_with(7, 42, include_archived=True)
        mock_limit.assert_called_once_with(42)
        mock_restore.assert_called_once_with(7, 42)

    def test_chatbot_usage_count_excludes_archived_bots(self):
        from app.database import billing_usage_repository

        query = _Query(_Response(count=1))

        with patch.object(billing_usage_repository, "supabase", query):
            count = billing_usage_repository.count_company_chatbots(42)

        self.assertEqual(count, 1)
        self.assertIn(("company_id", 42), query.eq_calls)
        self.assertIn(("deleted_at", "null"), query.is_calls)
        self.assertIn(("status", "archived"), query.neq_calls)

    def test_active_bot_ids_for_usage_exclude_archived_bots(self):
        from app.database import billing_usage_repository

        query = _Query(_Response(data=[{"id": 1}]))

        with patch.object(billing_usage_repository, "supabase", query):
            ids = billing_usage_repository.get_company_chatbot_ids(42)

        self.assertEqual(ids, [1])
        self.assertIn(("deleted_at", "null"), query.is_calls)
        self.assertIn(("status", "archived"), query.neq_calls)

    def test_verify_chatbot_access_filters_archived_bots(self):
        from app.utils import access_control

        query = _Query(_Response(data=[{"id": 7, "company_id": 42}]))
        app = Flask(__name__)

        with app.app_context(), patch("app.database.db.supabase", query):
            g.company_id = 42
            access = access_control.verify_chatbot_access(7)

        self.assertEqual(access["id"], 7)
        self.assertIn(("deleted_at", "null"), query.is_calls)
        self.assertIn(("status", "archived"), query.neq_calls)

    def test_archive_flow_does_not_touch_related_tables(self):
        from app.database import bot_repository

        query = _Query(_Response(data=[{"id": 7, "status": "archived"}]))

        with patch.object(bot_repository, "supabase", query):
            bot_repository.archive_bot(7, 42)

        self.assertEqual(query.table_name, "chatbots")
        self.assertNotIn(query.table_name, {
            "knowledge_files",
            "conversations",
            "messages",
            "wasender_channels",
            "knowledge_graph_nodes",
            "knowledge_graph_edges",
            "crm_leads",
            "agent_actions",
            "ai_usage_logs",
        })

    def test_permanent_delete_calls_rpc_with_expected_params(self):
        from app.database import bot_repository

        fake_supabase = _RpcSupabase({
            "status": "success",
            "code": "deleted",
            "deleted_counts": {"ai_usage_logs": 0},
        })

        with patch.object(bot_repository, "supabase", fake_supabase):
            result = bot_repository.permanently_delete_archived_chatbot_rpc(
                7,
                42,
                "Archived Bot",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(fake_supabase.rpc_calls, [(
            "permanently_delete_archived_chatbot",
            {
                "p_chatbot_id": 7,
                "p_company_id": 42,
                "p_confirm_bot_name": "Archived Bot",
            },
        )])

    def test_permanent_delete_migration_cleans_orphan_prone_tables_and_preserves_ai_usage(self):
        migration = Path("data/022_permanently_delete_archived_chatbot_rpc.sql").read_text(
            encoding="utf-8",
        )

        expected_deletes = [
            "DELETE FROM public.wasender_channels",
            "DELETE FROM public.telegram_channels",
            "DELETE FROM public.whatsapp_channels",
            "DELETE FROM public.knowledge_graph_edges",
            "DELETE FROM public.knowledge_graph_nodes",
            "DELETE FROM public.crm_leads",
            "DELETE FROM public.agent_actions",
            "DELETE FROM public.chatbots",
        ]
        for delete_statement in expected_deletes:
            self.assertIn(delete_statement, migration)

        self.assertLess(
            migration.index("DELETE FROM public.knowledge_graph_edges"),
            migration.index("DELETE FROM public.knowledge_graph_nodes"),
        )
        self.assertLess(
            migration.index("DELETE FROM public.agent_actions"),
            migration.index("DELETE FROM public.chatbots"),
        )
        self.assertLess(
            migration.index("DELETE FROM public.chatbots"),
            migration.rindex("RETURN jsonb_build_object"),
        )
        self.assertIn("'ai_usage_logs', 0", migration)
        self.assertIn("preserved_tables", migration)
        self.assertNotIn("DELETE FROM public.ai_usage_logs", migration)

    def test_active_bot_cannot_be_permanently_deleted(self):
        from app.services import bot_service

        with patch.object(
            bot_service,
            "permanently_delete_archived_chatbot_rpc",
            return_value={
                "status": "error",
                "code": "active_bot",
                "message": "Only archived bots can be permanently deleted",
            },
        ) as mock_rpc:
            with self.assertRaises(bot_service.PermanentBotDeleteError) as ctx:
                bot_service.permanently_delete_archived_bot(7, 42, "Active Bot")

        self.assertEqual(ctx.exception.code, "active_bot")
        self.assertIn("Only archived bots", str(ctx.exception))
        mock_rpc.assert_called_once_with(7, 42, "Active Bot")
        self.assertFalse(hasattr(bot_service, "cleanup_bot_related_records"))
        self.assertFalse(hasattr(bot_service, "permanent_delete_bot"))

    def test_wrong_confirmation_name_blocks_permanent_delete(self):
        from app.services import bot_service

        with patch.object(
            bot_service,
            "permanently_delete_archived_chatbot_rpc",
            return_value={
                "status": "error",
                "code": "confirmation_mismatch",
                "message": "Confirmation bot name does not match",
            },
        ) as mock_rpc:
            with self.assertRaises(bot_service.PermanentBotDeleteError) as ctx:
                bot_service.permanently_delete_archived_bot(7, 42, "Wrong Bot")

        self.assertEqual(ctx.exception.code, "confirmation_mismatch")
        self.assertIn("Confirmation bot name", str(ctx.exception))
        mock_rpc.assert_called_once_with(7, 42, "Wrong Bot")

    def test_archived_bot_can_be_permanently_deleted_with_exact_name(self):
        from app.services import bot_service

        with patch.object(
            bot_service,
            "permanently_delete_archived_chatbot_rpc",
            return_value={
                "status": "success",
                "code": "deleted",
                "message": "Bot permanently deleted",
                "deleted_counts": {"ai_usage_logs": 0},
            },
        ) as mock_rpc:
            result = bot_service.permanently_delete_archived_bot(7, 42, "Archived Bot")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["deleted_counts"]["ai_usage_logs"], 0)
        mock_rpc.assert_called_once_with(7, 42, "Archived Bot")

    def test_not_found_rpc_result_maps_to_lookup_error(self):
        from app.services import bot_service

        with patch.object(
            bot_service,
            "permanently_delete_archived_chatbot_rpc",
            return_value={
                "status": "error",
                "code": "not_found",
                "message": "Bot not found",
            },
        ):
            with self.assertRaises(LookupError) as ctx:
                bot_service.permanently_delete_archived_bot(7, 42, "Archived Bot")

        self.assertIn("Bot not found", str(ctx.exception))


class TestBotArchiveRoutes(unittest.TestCase):
    def setUp(self):
        from app import create_app

        app = create_app()
        app.config["TESTING"] = True
        self.app = app
        self.client = app.test_client()

    def _patch_auth(self):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 42, "user_id": 1, "role": "admin"},
        )

    def _patch_user(self):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value={
                "id": 1,
                "email": "owner@example.com",
                "status": "active",
                "role": "admin",
                "company_id": 42,
            },
        )

    @patch("app.routes.bot_routes.list_archived_bots")
    def test_archived_bots_endpoint_returns_archived_list(self, mock_list):
        mock_list.return_value = [{"id": 7, "status": "archived"}]

        with self._patch_auth(), self._patch_user():
            response = self.client.get(
                "/api/bots/archived",
                headers={"Authorization": "Bearer token"},
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["data"][0]["status"], "archived")
        mock_list.assert_called_once_with(42)

    @patch("app.routes.bot_routes.list_archived_bots")
    def test_archived_bots_endpoint_hides_raw_backend_error(self, mock_list):
        mock_list.side_effect = Exception("permission denied for table chatbots")
    def test_archived_bots_route_registered_once_as_get_endpoint(self):
        rules = [
            rule for rule in self.app.url_map.iter_rules()
            if rule.rule == "/api/bots/archived"
        ]

        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].endpoint, "bots.fetch_archived_bots")
        self.assertIn("GET", rules[0].methods)
        self.assertNotIn("POST", rules[0].methods)

    def test_archived_bots_endpoint_requires_authentication(self):
        response = self.client.get("/api/bots/archived")

        self.assertEqual(response.status_code, 401)

    @patch("app.routes.bot_routes.list_archived_bots")
    def test_archived_bots_endpoint_returns_empty_list(self, mock_list):
        mock_list.return_value = []

        with self._patch_auth(), self._patch_user():
            response = self.client.get(
                "/api/bots/archived",
                headers={"Authorization": "Bearer token"},
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(payload["message"], "Unable to load archived bots. Please try again or contact support.")
        self.assertNotIn("chatbots", payload["message"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["data"], [])
        mock_list.assert_called_once_with(42)

    @patch("app.routes.bot_routes.list_bots")
    def test_active_bots_endpoint_still_returns_active_list(self, mock_list):
        mock_list.return_value = [{"id": 8, "status": "active", "deleted_at": None}]

        with self._patch_auth(), self._patch_user():
            response = self.client.get(
                "/api/bots",
                headers={"Authorization": "Bearer token"},
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["data"][0]["status"], "active")
        mock_list.assert_called_once_with(42)

    @patch("app.routes.bot_routes.list_archived_bots")
    def test_archived_bots_endpoint_does_not_call_active_listing(self, mock_archived):
        mock_archived.return_value = [{"id": 7, "status": "archived"}]

        with self._patch_auth(), self._patch_user(), patch("app.routes.bot_routes.list_bots") as mock_active:
            response = self.client.get(
                "/api/bots/archived",
                headers={"Authorization": "Bearer token"},
            )

        self.assertEqual(response.status_code, 200)
        mock_archived.assert_called_once_with(42)
        mock_active.assert_not_called()

    @patch("app.routes.bot_routes.restore_archived_bot")
    def test_restore_endpoint_returns_restored_bot(self, mock_restore):
        mock_restore.return_value = {"id": 7, "status": "active", "deleted_at": None}

        with self._patch_auth(), self._patch_user():
            response = self.client.post(
                "/api/bots/7/restore",
                headers={"Authorization": "Bearer token"},
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["data"]["status"], "active")
        mock_restore.assert_called_once_with(7, 42)

    @patch("app.routes.bot_routes.restore_archived_bot")
    def test_restore_endpoint_returns_chatbot_limit_error(self, mock_restore):
        from app.services.billing_guard import BillingLimitError

        mock_restore.side_effect = BillingLimitError(
            "Chatbot limit reached",
            code="chatbot_limit",
        )

        with self._patch_auth(), self._patch_user():
            response = self.client.post(
                "/api/bots/7/restore",
                headers={"Authorization": "Bearer token"},
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["code"], "chatbot_limit")
        mock_restore.assert_called_once_with(7, 42)

    @patch("app.routes.bot_routes.restore_archived_bot")
    def test_restore_endpoint_hides_raw_backend_error(self, mock_restore):
        mock_restore.side_effect = Exception("permission denied for function restore_bot")

        with self._patch_auth(), self._patch_user():
            response = self.client.post(
                "/api/bots/7/restore",
                headers={"Authorization": "Bearer token"},
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(payload["message"], "Unable to restore bot. Please try again or contact support.")
        self.assertNotIn("restore_bot", payload["message"])

    @patch("app.routes.bot_routes.permanently_delete_archived_bot")
    def test_permanent_delete_endpoint_requires_exact_confirmation(self, mock_delete):
        mock_delete.return_value = [{"id": 7}]

        with self._patch_auth(), self._patch_user():
            response = self.client.delete(
                "/api/bots/7/permanent",
                headers={"Authorization": "Bearer token"},
                json={"confirm_bot_name": "Archived Bot"},
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "success")
        mock_delete.assert_called_once_with(7, 42, "Archived Bot")

    @patch("app.routes.bot_routes.permanently_delete_archived_bot")
    def test_permanent_delete_endpoint_returns_400_for_wrong_confirmation(self, mock_delete):
        from app.services.bot_service import PermanentBotDeleteError

        mock_delete.side_effect = PermanentBotDeleteError(
            "Confirmation bot name does not match",
            code="confirmation_mismatch",
        )

        with self._patch_auth(), self._patch_user():
            response = self.client.delete(
                "/api/bots/7/permanent",
                headers={"Authorization": "Bearer token"},
                json={"confirm_bot_name": "Wrong Bot"},
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["code"], "confirmation_mismatch")
        self.assertIn("Confirmation bot name", payload["message"])
        mock_delete.assert_called_once_with(7, 42, "Wrong Bot")

    @patch("app.routes.bot_routes.permanently_delete_archived_bot")
    def test_permanent_delete_endpoint_returns_403_for_active_bot(self, mock_delete):
        from app.services.bot_service import PermanentBotDeleteError

        mock_delete.side_effect = PermanentBotDeleteError(
            "Only archived bots can be permanently deleted",
            code="active_bot",
        )

        with self._patch_auth(), self._patch_user():
            response = self.client.delete(
                "/api/bots/7/permanent",
                headers={"Authorization": "Bearer token"},
                json={"confirm_bot_name": "Active Bot"},
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["code"], "active_bot")
        self.assertIn("Only archived bots", payload["message"])

    @patch("app.routes.bot_routes.permanently_delete_archived_bot")
    def test_permanent_delete_endpoint_hides_raw_permission_error(self, mock_delete):
        mock_delete.side_effect = Exception("permission denied for table agent_actions")

        with self._patch_auth(), self._patch_user():
            response = self.client.delete(
                "/api/bots/7/permanent",
                headers={"Authorization": "Bearer token"},
                json={"confirm_bot_name": "Archived Bot"},
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(
            payload["message"],
            "Unable to permanently delete bot. Please try again or contact support.",
        )
        self.assertNotIn("agent_actions", payload["message"])


if __name__ == "__main__":
    unittest.main()
