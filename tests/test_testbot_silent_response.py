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


if __name__ == "__main__":
    unittest.main()
