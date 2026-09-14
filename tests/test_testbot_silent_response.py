import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")

if "google" not in sys.modules:
    _g = types.ModuleType("google")
    _g.genai = types.ModuleType("google.genai")
    _g.genai.Client = MagicMock()
    sys.modules["google"] = _g
    sys.modules["google.genai"] = _g.genai
if "fitz" not in sys.modules:
    sys.modules["fitz"] = types.ModuleType("fitz")
if "tools" not in sys.modules:
    sys.modules["tools"] = types.ModuleType("tools")
if "_tools" not in sys.modules:
    sys.modules["_tools"] = types.ModuleType("_tools")

with patch("app.database.db.supabase", MagicMock()):
    from app import create_app


class TestTestBotSilentResponse(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
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
        conversation_patch = patch("app.routes.testbot_routes.get_or_create_conversation", return_value={"id": 100})
        conversation_patch.start()
        self.addCleanup(conversation_patch.stop)

    def tearDown(self):
        self.access_patch.stop()
        self.user_patch.stop()
        self.jwt_patch.stop()

    def post_chat(self):
        return self.client.post(
            "/api/testbot/chat?chatbot_id=7",
            json={"message": "Hello"},
            headers=self.headers,
        )

    @patch("app.routes.testbot_routes.generate_response")
    def test_silent_bot_response_returns_human_staff_message(self, mock_generate):
        mock_generate.return_value = "<SILENT_BOT_RESPONSE>"

        response = self.post_chat()
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(
            payload["data"]["reply"],
            "This conversation is currently assigned to human staff.",
        )

    @patch("app.routes.testbot_routes.generate_response")
    def test_normal_testbot_reply_remains_unchanged(self, mock_generate):
        mock_generate.return_value = "Normal reply"

        response = self.post_chat()
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["data"]["reply"], "Normal reply")

    def test_clear_resets_server_session_before_the_next_reply(self):
        """Clear must reach the server, not merely remove the visible bubbles."""
        with patch("app.routes.testbot_routes.reset_testbot_conversation", create=True) as reset:
            response = self.client.post(
                "/api/testbot/reset?chatbot_id=7", headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        reset.assert_called_once_with(7, 42, "web_testbot_session")

    def test_clear_reports_persistence_failure(self):
        with patch(
            "app.routes.testbot_routes.reset_testbot_conversation",
            create=True, side_effect=RuntimeError("reset unavailable"),
        ):
            response = self.client.post(
                "/api/testbot/reset?chatbot_id=7", headers=self.headers,
            )
        self.assertEqual(response.status_code, 500)

    def test_clear_requires_auth_and_chatbot_ownership(self):
        self.assertEqual(self.client.post("/api/testbot/reset?chatbot_id=7").status_code, 401)
        with patch(
            "app.routes.testbot_routes.verify_chatbot_access",
            side_effect=PermissionError("Access denied"),
        ), patch("app.routes.testbot_routes.reset_testbot_conversation", create=True) as reset:
            response = self.client.post(
                "/api/testbot/reset?chatbot_id=7", headers=self.headers,
            )
        self.assertEqual(response.status_code, 403)
        reset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
