import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import sys
import unittest
from unittest.mock import patch, MagicMock
import types

# Mock standard broken imports
if "google" not in sys.modules:
    _g = types.ModuleType("google")
    _g.genai = types.ModuleType("google.genai")
    _g.genai.Client = MagicMock()
    sys.modules["google"] = _g
    sys.modules["google.genai"] = _g.genai
if "fitz" not in sys.modules:
    sys.modules["fitz"] = types.ModuleType("fitz")

with patch("app.database.db.supabase", MagicMock()):
    from app import create_app

MOCK_USER = {
    "id": 1,
    "company_id": 42,
    "full_name": "Test User",
    "email": "test@example.com",
    "role": "admin",
    "status": "active",
}

class TestBroadcastRoutes(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def _patch_jwt_decode(self):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 42, "user_id": 1, "role": "admin"},
        )

    def _patch_user_repo(self):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value=MOCK_USER,
        )

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.get_campaigns")
    def test_list_campaigns_success(self, mock_get_campaigns, mock_verify):
        mock_get_campaigns.return_value = [{"id": 10, "name": "Camp A", "status": "draft"}]

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/broadcast/campaigns?chatbot_id=1",
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["campaigns"][0]["name"], "Camp A")

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.create_campaign")
    @patch("app.routes.broadcast_routes.create_broadcast_log")
    def test_save_campaign_success(self, mock_create_log, mock_create_campaign, mock_verify):
        mock_create_campaign.return_value = {"id": 10, "name": "Camp A", "channel_type": "whatsapp", "status": "draft"}

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/broadcast/campaign?chatbot_id=1",
                json={
                    "name": "Camp A",
                    "channel_type": "whatsapp",
                    "message_template": "Hello {{phone}}",
                    "recipients": [{"phone": "+60123456789", "name": "Alice"}]
                },
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["campaign"]["name"], "Camp A")
            mock_create_log.assert_called_once()

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.get_campaign_by_id")
    @patch("app.routes.broadcast_routes.get_broadcast_logs_by_campaign")
    def test_get_campaign_logs_success(self, mock_get_logs, mock_get_campaign, mock_verify):
        mock_get_campaign.return_value = {"id": 10, "name": "Camp A"}
        mock_get_logs.return_value = [{"id": 1, "recipient_phone": "+60123456789", "status": "pending"}]

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/broadcast/campaign/10/logs?chatbot_id=1",
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["logs"][0]["recipient_phone"], "+60123456789")

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.get_campaign_by_id")
    @patch("app.routes.broadcast_routes.get_broadcast_logs_by_campaign")
    @patch("app.routes.broadcast_routes.update_campaign_status")
    @patch("app.routes.broadcast_routes.threading.Thread")
    def test_start_campaign_success(self, mock_thread, mock_update_status, mock_get_logs, mock_get_campaign, mock_verify):
        mock_get_campaign.return_value = {"id": 10, "name": "Camp A", "status": "draft", "company_id": 42}
        mock_get_logs.return_value = [{"id": 1, "recipient_phone": "+60123456789", "status": "pending"}]

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/broadcast/campaign/10/start?chatbot_id=1",
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            mock_thread.assert_called_once()
            mock_update_status.assert_called_once_with(10, 42, "sending")

if __name__ == "__main__":
    unittest.main()
