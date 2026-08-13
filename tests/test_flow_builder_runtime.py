import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")

if "google" not in sys.modules:
    google = types.ModuleType("google")
    google.genai = types.ModuleType("google.genai")
    google.genai.Client = MagicMock()
    sys.modules["google"] = google
    sys.modules["google.genai"] = google.genai
if "tools" not in sys.modules:
    sys.modules["tools"] = types.ModuleType("tools")


def _published_flow(nodes):
    return {
        "id": 99,
        "company_id": 42,
        "chatbot_id": 7,
        "status": "active",
        "published_data": {
            "drawflow": {
                "Home": {
                    "data": nodes,
                },
            },
        },
    }


class FlowExecutorRuntimeTests(unittest.TestCase):
    def test_import_path_expected_by_ai_router_exists(self):
        from app.services.flow_executor_service import process_flow_message

        self.assertTrue(callable(process_flow_message))

    @patch("app.services.flow_executor_service.insert_execution_log")
    @patch("app.services.flow_executor_service.update_conversation_flow_state")
    @patch("app.services.flow_executor_service.get_open_conversation_for_flow")
    @patch("app.services.flow_executor_service.get_active_published_flow")
    def test_active_published_flow_executes_send_message(
        self, mock_flow, mock_conversation, mock_update, mock_log
    ):
        from app.services.flow_executor_service import process_flow_message

        mock_flow.return_value = _published_flow({
            "1": {
                "name": "trigger",
                "data": {"keyword": "start"},
                "outputs": {"output_1": {"connections": [{"node": "2"}]}},
            },
            "2": {
                "name": "send_message",
                "data": {"text": "Welcome to OlympicEdu."},
                "outputs": {"output_1": {"connections": []}},
            },
        })
        mock_conversation.return_value = {"id": 500, "active_flow_id": None, "current_node_id": None}

        result = process_flow_message(42, 7, "start", "web_testbot_session", source_channel="web")

        self.assertEqual(result.status, "handled")
        self.assertEqual(result.reply, "Welcome to OlympicEdu.")
        mock_flow.assert_called_once_with(42, 7)
        mock_update.assert_any_call(500, 99, "2")
        mock_update.assert_any_call(500, None, None)
        mock_log.assert_called_once()

    @patch("app.services.flow_executor_service.update_conversation_flow_state")
    @patch("app.services.flow_executor_service.get_open_conversation_for_flow")
    @patch("app.services.flow_executor_service.get_active_published_flow")
    def test_no_matching_flow_trigger_hands_off_to_ai(self, mock_flow, mock_conversation, mock_update):
        from app.services.flow_executor_service import process_flow_message

        mock_flow.return_value = _published_flow({
            "1": {"name": "trigger", "data": {"keyword": "start"}, "outputs": {}},
        })
        mock_conversation.return_value = {"id": 500, "active_flow_id": None, "current_node_id": None}

        result = process_flow_message(42, 7, "ordinary question", "web_testbot_session", source_channel="web")

        self.assertEqual(result.status, "not_applicable")
        self.assertTrue(result.should_handoff_to_ai)
        mock_update.assert_not_called()

    @patch("app.services.flow_executor_service.insert_execution_log")
    @patch("app.services.flow_executor_service.update_conversation_flow_state")
    @patch("app.services.flow_executor_service.get_open_conversation_for_flow")
    @patch("app.services.flow_executor_service.get_active_published_flow")
    def test_flow_ai_handoff_returns_none_for_normal_rag_path(
        self, mock_flow, mock_conversation, mock_update, mock_log
    ):
        from app.services.flow_executor_service import process_flow_message

        mock_flow.return_value = _published_flow({
            "1": {
                "name": "trigger",
                "data": {"keyword": "ask"},
                "outputs": {"output_1": {"connections": [{"node": "2"}]}},
            },
            "2": {"name": "rag", "data": {}, "outputs": {}},
        })
        mock_conversation.return_value = {"id": 500, "active_flow_id": None, "current_node_id": None}

        result = process_flow_message(42, 7, "ask", "web_testbot_session", source_channel="web")

        self.assertEqual(result.status, "handoff")
        self.assertTrue(result.should_handoff_to_ai)
        mock_update.assert_any_call(500, None, None)
        mock_log.assert_called_once()

    @patch("app.services.flow_executor_service.get_active_published_flow")
    def test_invalid_flow_fails_safely(self, mock_flow):
        from app.services.flow_executor_service import process_flow_message

        mock_flow.return_value = {"id": 99, "published_data": {"drawflow": {"Home": {"data": {}}}}}

        result = process_flow_message(42, 7, "start", "web_testbot_session", source_channel="web")

        self.assertEqual(result.status, "handoff")
        self.assertTrue(result.should_handoff_to_ai)

    @patch("app.services.flow_executor_service.insert_execution_log")
    @patch("app.services.flow_executor_service.update_conversation_flow_state")
    @patch("app.services.flow_executor_service.get_open_conversation_for_flow")
    @patch("app.services.flow_executor_service.get_active_published_flow")
    def test_legacy_flow_data_remains_compatible(
        self, mock_flow, mock_conversation, mock_update, mock_log
    ):
        from app.services.flow_executor_service import process_flow_message

        flow = _published_flow({
            "1": {
                "name": "trigger",
                "data": {"keyword": "legacy"},
                "outputs": {"output_1": {"connections": [{"node": "2"}]}},
            },
            "2": {"name": "send_message", "data": {"text": "Legacy reply"}, "outputs": {}},
        })
        flow["flow_data"] = flow.pop("published_data")
        mock_flow.return_value = flow
        mock_conversation.return_value = {"id": 500, "active_flow_id": None, "current_node_id": None}

        result = process_flow_message(42, 7, "legacy", "web_testbot_session")

        self.assertEqual(result.status, "handled")
        self.assertEqual(result.reply, "Legacy reply")

    @patch("app.services.flow_executor_service.insert_execution_log")
    @patch("app.services.flow_executor_service.update_conversation_flow_state")
    @patch("app.services.flow_executor_service.get_open_conversation_for_flow")
    @patch("app.services.flow_executor_service.get_active_published_flow")
    def test_published_data_wins_over_unpublished_flow_data(
        self, mock_flow, mock_conversation, mock_update, mock_log
    ):
        from app.services.flow_executor_service import process_flow_message

        flow = _published_flow({
            "1": {
                "name": "trigger",
                "data": {"keyword": "start"},
                "outputs": {"output_1": {"connections": [{"node": "2"}]}},
            },
            "2": {"name": "send_message", "data": {"text": "Published reply"}, "outputs": {}},
        })
        flow["flow_data"] = {
            "drawflow": {
                "Home": {
                    "data": {
                        "1": {
                            "name": "trigger",
                            "data": {"keyword": "start"},
                            "outputs": {"output_1": {"connections": [{"node": "2"}]}},
                        },
                        "2": {"name": "send_message", "data": {"text": "Draft reply"}, "outputs": {}},
                    },
                },
            },
        }
        mock_flow.return_value = flow
        mock_conversation.return_value = {"id": 500, "active_flow_id": None, "current_node_id": None}

        result = process_flow_message(42, 7, "start", "web_testbot_session")

        self.assertEqual(result.status, "handled")
        self.assertEqual(result.reply, "Published reply")

    @patch("app.services.flow_executor_service.insert_execution_log")
    @patch("app.services.flow_executor_service.update_conversation_flow_state")
    @patch("app.services.flow_executor_service.get_open_conversation_for_flow")
    @patch("app.services.flow_executor_service.get_active_published_flow")
    def test_missing_conversation_state_columns_can_execute_stateless_flow(
        self, mock_flow, mock_conversation, mock_update, mock_log
    ):
        from app.services.flow_executor_service import process_flow_message

        mock_flow.return_value = _published_flow({
            "1": {
                "name": "trigger",
                "data": {"keyword": "start"},
                "outputs": {"output_1": {"connections": [{"node": "2"}]}},
            },
            "2": {"name": "send_message", "data": {"text": "Stateless reply"}, "outputs": {}},
        })
        mock_conversation.return_value = None

        result = process_flow_message(42, 7, "start", "web_testbot_session")

        self.assertEqual(result.status, "handled")
        self.assertEqual(result.reply, "Stateless reply")
        mock_update.assert_not_called()

    @patch("app.services.flow_executor_service.get_active_published_flow")
    def test_executor_failure_is_distinct_from_no_flow(self, mock_flow):
        from app.services.flow_executor_service import process_flow_message

        mock_flow.side_effect = RuntimeError("database unavailable")

        result = process_flow_message(42, 7, "start", "web_testbot_session")

        self.assertEqual(result.status, "failed")
        self.assertFalse(result.should_handoff_to_ai)


class FlowRepositoryTenantScopeTests(unittest.TestCase):
    def test_active_published_flow_lookup_scopes_by_company_and_chatbot(self):
        from app.database import flow_repository

        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.in_.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.execute.return_value = SimpleNamespace(data=[{
            "id": 99,
            "company_id": 42,
            "chatbot_id": 7,
            "status": "active",
            "published_data": {"nodes": {}},
        }])

        supabase = MagicMock()
        supabase.table.return_value = query

        with patch.object(flow_repository, "supabase", supabase):
            flow = flow_repository.get_active_published_flow(42, 7)

        self.assertEqual(flow["company_id"], 42)
        query.eq.assert_any_call("company_id", 42)
        query.eq.assert_any_call("chatbot_id", 7)

    def test_missing_v3_columns_falls_back_to_legacy_lookup(self):
        from app.database import flow_repository

        v3_query = MagicMock()
        v3_query.select.return_value = v3_query
        v3_query.eq.return_value = v3_query
        v3_query.in_.return_value = v3_query
        v3_query.order.return_value = v3_query
        v3_query.limit.return_value = v3_query
        v3_query.execute.side_effect = RuntimeError("column flows.published_at does not exist")

        legacy_query = MagicMock()
        legacy_query.select.return_value = legacy_query
        legacy_query.eq.return_value = legacy_query
        legacy_query.in_.return_value = legacy_query
        legacy_query.order.return_value = legacy_query
        legacy_query.limit.return_value = legacy_query
        legacy_query.execute.return_value = SimpleNamespace(data=[])

        supabase = MagicMock()
        supabase.table.side_effect = [v3_query, legacy_query]

        with patch.object(flow_repository, "supabase", supabase):
            flow = flow_repository.get_active_published_flow(42, 53)

        self.assertIsNone(flow)
        legacy_query.eq.assert_any_call("company_id", 42)
        legacy_query.eq.assert_any_call("chatbot_id", 53)
        legacy_query.order.assert_called_once_with("updated_at", desc=True)


class AIRouterFlowIntegrationTests(unittest.TestCase):
    @patch("app.services.ai_router.get_bot_by_id")
    @patch("app.services.company_status_service.ensure_company_operational")
    @patch("app.services.ai_router._try_process_flow_message")
    @patch("app.services.ai_router.call_provider")
    @patch("app.services.ai_router._route_for_enforcement")
    def test_no_flow_normal_provider_path_still_works(
        self, mock_route, mock_provider, mock_flow, mock_company, mock_bot
    ):
        from app.services.ai_router import generate_response

        mock_bot.return_value = {
            "ai_provider": "deepseek",
            "model_name": "deepseek-chat",
            "temperature": 0.7,
            "company_id": 42,
        }
        mock_flow.return_value = SimpleNamespace(status="no_flow", reply=None, handled=False, should_handoff_to_ai=True)
        mock_route.return_value = ("deepseek", "deepseek-chat")
        mock_provider.return_value = MagicMock(text="RAG answer", is_provider_response=False)

        self.assertEqual(generate_response("question", "customer", 7, source_channel="web"), "RAG answer")
        mock_flow.assert_called_once_with(42, 7, "question", "customer", "web")
        mock_provider.assert_called_once()

    @patch("app.services.ai_router.get_bot_by_id")
    @patch("app.services.company_status_service.ensure_company_operational")
    @patch("app.services.ai_router._try_process_flow_message")
    @patch("app.services.ai_router.call_provider")
    def test_active_flow_reply_short_circuits_provider(self, mock_provider, mock_flow, mock_company, mock_bot):
        from app.services.ai_router import generate_response

        mock_bot.return_value = {"ai_provider": "deepseek", "model_name": "deepseek-chat", "company_id": 42}
        mock_flow.return_value = SimpleNamespace(status="handled", reply="Flow reply", handled=True, should_handoff_to_ai=False)

        self.assertEqual(generate_response("start", "customer", 7), "Flow reply")
        mock_provider.assert_not_called()

    @patch("app.services.flow_executor_service.process_flow_message")
    def test_broken_executor_helper_reports_failure(self, mock_process):
        from app.services.ai_router import _try_process_flow_message

        mock_process.side_effect = RuntimeError("executor broken")

        result = _try_process_flow_message(42, 7, "question", "customer", "web")

        self.assertEqual(result.status, "failed")
        self.assertFalse(result.should_handoff_to_ai)

    @patch("app.services.ai_router.get_bot_by_id")
    @patch("app.services.company_status_service.ensure_company_operational")
    @patch("app.services.ai_router._try_process_flow_message")
    @patch("app.services.ai_router.call_provider")
    def test_flow_runtime_failure_returns_safe_error_without_provider(self, mock_provider, mock_flow, mock_company, mock_bot):
        from app.services.ai_router import generate_response

        mock_bot.return_value = {"ai_provider": "deepseek", "model_name": "deepseek-chat", "company_id": 42}
        mock_flow.return_value = SimpleNamespace(status="failed", reply=None, handled=False, should_handoff_to_ai=False)

        result = generate_response("start", "customer", 7)

        self.assertIn("trouble", result)
        mock_provider.assert_not_called()


class TestBotFlowIntegrationTests(unittest.TestCase):
    def setUp(self):
        with patch("app.database.db.supabase", MagicMock()):
            from app import create_app

            self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer test-token"}
        self.jwt_patch = patch("app.decorators.auth_decorator.jwt.decode", return_value={
            "user_id": 1,
            "company_id": 42,
            "role": "admin",
        })
        self.user_patch = patch("app.database.user_repository.get_user_by_id", return_value={
            "id": 1,
            "company_id": 42,
            "role": "admin",
            "status": "active",
        })
        self.access_patch = patch("app.routes.testbot_routes.verify_chatbot_access", return_value={
            "id": 7,
            "company_id": 42,
        })
        self.jwt_patch.start()
        self.user_patch.start()
        self.access_patch.start()

    def tearDown(self):
        self.access_patch.stop()
        self.user_patch.stop()
        self.jwt_patch.stop()

    @patch("app.routes.testbot_routes.generate_response")
    def test_testbot_uses_router_runtime_path(self, mock_generate):
        mock_generate.return_value = "Flow or RAG reply"

        response = self.client.post(
            "/api/testbot/chat?chatbot_id=7",
            json={"message": "start"},
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["reply"], "Flow or RAG reply")
        mock_generate.assert_called_once_with(
            "start",
            "web_testbot_session",
            7,
            source_channel="web",
            operation_type="test_bot",
        )


if __name__ == "__main__":
    unittest.main()
