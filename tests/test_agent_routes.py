import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import sys
import unittest
from unittest.mock import patch, MagicMock
import types

# Mock broken imports before any app import
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

MOCK_RESOLVED = {
    "id": 10,
    "conversation_id": 100,
    "chatbot_id": 1,
    "company_id": 42,
    "intent": "handoff_request",
    "status": "resolved",
}

MOCK_CONVERSATION_WHATSAPP = {
    "id": 100,
    "chatbot_id": 1,
    "source_channel": "whatsapp", "source_channel_id": 1, "source_provider_id": "123",
    "customer_phone": "+60123456789",
    "platform_user_id": None,
}

MOCK_CONVERSATION_TELEGRAM = {
    "id": 101,
    "chatbot_id": 1,
    "source_channel": "telegram", "source_channel_id": 1, "source_provider_id": "123",
    "customer_phone": None,
    "platform_user_id": "123456789",
}

MOCK_CONVERSATION_WASENDER = {
    "id": 102,
    "chatbot_id": 1,
    "source_channel": "wasender", "source_channel_id": 1, "source_provider_id": "123",
    "customer_phone": "+60123456789",
    "platform_user_id": "60123456789",
}

MOCK_ESCALATIONS = [
    {
        "id": 1,
        "chatbot_id": 1,
        "conversation_id": 100,
        "intent": "handoff_request",
        "status": "detected",
        "created_at": "2026-07-06T10:00:00",
    },
    {
        "id": 2,
        "chatbot_id": 1,
        "conversation_id": 101,
        "intent": "complaint",
        "status": "detected",
        "created_at": "2026-07-06T10:05:00",
    },
]

MOCK_WHATSAPP_CHANNELS = [{"id": 1, "chatbot_id": 1, "access_token": "whatsapp-token", "phone_number_id": "123", "is_active": True, "connection_status": "connected", "verified_at": "2026-09-14"}]
MOCK_TELEGRAM_CHANNELS = [{"id": 1, "chatbot_id": 1, "telegram_bot_id": "123", "bot_token": "telegram-token", "is_active": True, "connection_status": "connected", "verified_at": "2026-09-14"}]
MOCK_WASENDER_CHANNELS = [{"id": 1, "chatbot_id": 1, "provider_user_id": "123", "api_key": "wasender-api-key", "is_active": True, "connection_status": "connected", "verified_at": "2026-09-14"}]



class TestAgentEscalationRoutes(unittest.TestCase):
    """Tests for escalation listing, resolution, and agent reply routes."""

    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def _patch_jwt_decode(self, role="admin", company_id=42):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": company_id, "user_id": 1, "role": role},
        )

    def _patch_user_repo(self, role="admin", company_id=42):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value={
                **MOCK_USER,
                "role": role,
                "company_id": company_id,
            },
        )

    def test_telegram_failed_reply_never_claims_sent_or_resolves_handoff(self):
        for delivery in (None, {"ok": False}, {}):
            with self.subTest(delivery=delivery), self._patch_jwt_decode(), self._patch_user_repo(), patch(
                "app.routes.agent_routes.verify_chatbot_access",
            ), patch(
                "app.routes.agent_routes.get_conversation_by_id_and_chatbot", return_value=MOCK_CONVERSATION_TELEGRAM,
            ), patch(
                "app.services.channel_delivery_service.get_telegram_channel_by_id", return_value=MOCK_TELEGRAM_CHANNELS[0],
            ), patch(
                "app.routes.agent_routes.send_telegram_message", return_value=delivery,
            ), patch("app.routes.agent_routes.save_message") as save, patch(
                "app.routes.agent_routes.resolve_escalation",
            ) as resolve:
                response = self.client.post(
                    "/api/conversations/101/agent-reply",
                    json={"chatbot_id": 1, "text": "Human reply", "action_id": 10},
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(response.status_code, 502)
                save.assert_not_called()
                resolve.assert_not_called()

    def test_telegram_resolution_reports_failed_notice_without_sent_transcript(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), patch(
            "app.routes.agent_routes.verify_chatbot_access", return_value={"id": 1, "company_id": 42},
        ), patch(
            "app.routes.agent_routes.resolve_escalation", return_value=(MOCK_RESOLVED, True),
        ), patch(
            "app.routes.agent_routes.is_conversation_escalated", return_value=False,
        ), patch(
            "app.routes.agent_routes.get_conversation_by_id_and_chatbot", return_value=MOCK_CONVERSATION_TELEGRAM,
        ), patch(
            "app.services.channel_delivery_service.get_telegram_channel_by_id", return_value=MOCK_TELEGRAM_CHANNELS[0],
        ), patch(
            "app.routes.agent_routes.send_telegram_message", return_value=None,
        ) as send, patch("app.routes.agent_routes.save_message") as save:
            response = self.client.post(
                "/api/agent/escalations/10/resolve", json={"chatbot_id": 1},
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"].get("notification_status"), "failed")
        send.assert_called_once()
        save.assert_not_called()

    # ------------------------------------------------------------------ #
    #  Escalation listing (GET /api/agent/escalations)
    # ------------------------------------------------------------------ #

    @patch("app.routes.agent_routes.get_pending_escalations")
    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_get_escalations_success(self, mock_verify, mock_get_esc):
        mock_verify.return_value = {"id": 1, "company_id": 42}
        mock_get_esc.return_value = MOCK_ESCALATIONS
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/agent/escalations?chatbot_id=1",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(len(data["data"]), 2)
            mock_get_esc.assert_called_once_with(1, 42)

    @patch("app.routes.agent_routes.get_pending_escalations")
    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_get_escalations_empty(self, mock_verify, mock_get_esc):
        mock_verify.return_value = {"id": 1, "company_id": 42}
        mock_get_esc.return_value = []
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/agent/escalations?chatbot_id=1",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["data"], [])

    def test_get_escalations_missing_chatbot_id(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/agent/escalations",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 400)

    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_get_escalations_access_denied(self, mock_verify):
        mock_verify.side_effect = PermissionError("Access denied")
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/agent/escalations?chatbot_id=1",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 403)

    @patch("app.routes.agent_routes.get_pending_escalations")
    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_owner_can_list_escalations(self, mock_verify, mock_get_esc):
        mock_verify.return_value = {"id": 1, "company_id": 42}
        mock_get_esc.return_value = []
        with self._patch_jwt_decode(role="member"), self._patch_user_repo(role="owner"):
            resp = self.client.get(
                "/api/agent/escalations?chatbot_id=1",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 200)

    @patch("app.routes.agent_routes.get_pending_escalations")
    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_current_database_admin_can_list_despite_stale_member_jwt(
        self,
        mock_verify,
        mock_get_esc,
    ):
        mock_verify.return_value = {"id": 1, "company_id": 42}
        mock_get_esc.return_value = []
        with self._patch_jwt_decode(role="member"), self._patch_user_repo(role="admin"):
            resp = self.client.get(
                "/api/agent/escalations?chatbot_id=1",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 200)
        mock_get_esc.assert_called_once_with(1, 42)

    @patch("app.routes.agent_routes.get_pending_escalations")
    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_database_member_can_list_escalations(
        self,
        mock_verify,
        mock_get_esc,
    ):
        mock_verify.return_value = {"id": 1, "company_id": 42}
        mock_get_esc.return_value = []
        with self._patch_jwt_decode(role="owner"), self._patch_user_repo(role="member"):
            resp = self.client.get(
                "/api/agent/escalations?chatbot_id=1",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 200)
        mock_verify.assert_called_once_with(1)
        mock_get_esc.assert_called_once_with(1, 42)

    def test_unauthenticated_user_cannot_list_escalations(self):
        resp = self.client.get("/api/agent/escalations?chatbot_id=1")
        self.assertEqual(resp.status_code, 401)

    # ------------------------------------------------------------------ #
    #  Escalation resolution (POST /api/agent/escalations/<id>/resolve)
    # ------------------------------------------------------------------ #

    @patch("app.routes.agent_routes.send_wasender_text_message")
    @patch("app.services.channel_delivery_service.get_wasender_channel_by_id")
    @patch("app.routes.agent_routes.send_telegram_message")
    @patch("app.services.channel_delivery_service.get_telegram_channel_by_id")
    @patch("app.utils.whatsapp_utils.get_text_message_input")
    @patch("app.routes.agent_routes.send_whatsapp_message")
    @patch("app.services.channel_delivery_service.get_whatsapp_channel_by_id")
    @patch("app.routes.agent_routes.save_message")
    @patch("app.routes.agent_routes.get_conversation_by_id_and_chatbot")
    @patch("app.routes.agent_routes.is_conversation_escalated", return_value=False)
    @patch("app.routes.agent_routes.resolve_escalation")
    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_resolve_escalation_whatsapp(
        self,
        mock_verify,
        mock_resolve,
        mock_is_escalated,
        mock_get_conv,
        mock_save_msg,
        mock_get_wa_channels,
        mock_send_wa,
        mock_get_text_input,
        mock_get_tg_channels,
        mock_send_tg,
        mock_get_ws_channels,
        mock_send_ws,
    ):
        mock_verify.return_value = {"id": 1, "company_id": 42}
        mock_resolve.return_value = (MOCK_RESOLVED, True)
        mock_get_conv.return_value = MOCK_CONVERSATION_WHATSAPP
        mock_get_wa_channels.return_value = MOCK_WHATSAPP_CHANNELS[0]
        mock_send_wa.return_value = MagicMock(status_code=200, json=MagicMock(return_value={"messages": [{"id": "sent"}]}))
        mock_get_text_input.return_value = '{"messaging_product": "whatsapp", "to": "+60123456789", "type": "text", "text": {"body": "..."}}'

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/agent/escalations/10/resolve",
                json={"chatbot_id": 1},
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")

            # Verify resolution flow
            mock_resolve.assert_called_once_with(10, 1, 42)
            mock_is_escalated.assert_any_call(100, 1)
            mock_is_escalated.assert_called_with(100, 1, conversation=MOCK_CONVERSATION_WHATSAPP)
            mock_get_conv.assert_called_once_with(100, 1)
            mock_save_msg.assert_called_once()
            mock_get_text_input.assert_called_once()
            mock_send_wa.assert_called_once()

    @patch("app.routes.agent_routes.send_wasender_text_message")
    @patch("app.services.channel_delivery_service.get_wasender_channel_by_id")
    @patch("app.routes.agent_routes.send_telegram_message")
    @patch("app.services.channel_delivery_service.get_telegram_channel_by_id")
    @patch("app.utils.whatsapp_utils.get_text_message_input")
    @patch("app.routes.agent_routes.send_whatsapp_message")
    @patch("app.services.channel_delivery_service.get_whatsapp_channel_by_id")
    @patch("app.routes.agent_routes.save_message")
    @patch("app.routes.agent_routes.get_conversation_by_id_and_chatbot")
    @patch("app.routes.agent_routes.is_conversation_escalated", return_value=False)
    @patch("app.routes.agent_routes.resolve_escalation")
    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_resolve_escalation_telegram(
        self,
        mock_verify,
        mock_resolve,
        mock_is_escalated,
        mock_get_conv,
        mock_save_msg,
        mock_get_wa_channels,
        mock_send_wa,
        mock_get_text_input,
        mock_get_tg_channels,
        mock_send_tg,
        mock_get_ws_channels,
        mock_send_ws,
    ):
        mock_verify.return_value = {"id": 1, "company_id": 42}
        mock_resolve.return_value = (
            {**MOCK_RESOLVED, "conversation_id": 101},
            True,
        )
        mock_get_conv.return_value = MOCK_CONVERSATION_TELEGRAM
        mock_get_tg_channels.return_value = MOCK_TELEGRAM_CHANNELS[0]
        def accepted(*_args):
            mock_save_msg.assert_not_called()
            return {"ok": True, "result": {"message_id": 1}}
        mock_send_tg.side_effect = accepted

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/agent/escalations/10/resolve",
                json={"chatbot_id": 1},
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json()["data"]["notification_status"], "sent")
            mock_save_msg.assert_called_once()
            mock_send_tg.assert_called_once()

    @patch("app.routes.agent_routes.send_wasender_text_message")
    @patch("app.services.channel_delivery_service.get_wasender_channel_by_id")
    @patch("app.routes.agent_routes.send_telegram_message")
    @patch("app.services.channel_delivery_service.get_telegram_channel_by_id")
    @patch("app.utils.whatsapp_utils.get_text_message_input")
    @patch("app.routes.agent_routes.send_whatsapp_message")
    @patch("app.services.channel_delivery_service.get_whatsapp_channel_by_id")
    @patch("app.routes.agent_routes.save_message")
    @patch("app.routes.agent_routes.get_conversation_by_id_and_chatbot")
    @patch("app.routes.agent_routes.is_conversation_escalated", return_value=False)
    @patch("app.routes.agent_routes.resolve_escalation")
    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_resolve_escalation_wasender(
        self,
        mock_verify,
        mock_resolve,
        mock_is_escalated,
        mock_get_conv,
        mock_save_msg,
        mock_get_wa_channels,
        mock_send_wa,
        mock_get_text_input,
        mock_get_tg_channels,
        mock_send_tg,
        mock_get_ws_channels,
        mock_send_ws,
    ):
        mock_verify.return_value = {"id": 1, "company_id": 42}
        mock_resolve.return_value = (
            {**MOCK_RESOLVED, "conversation_id": 102},
            True,
        )
        mock_get_conv.return_value = MOCK_CONVERSATION_WASENDER
        mock_get_ws_channels.return_value = MOCK_WASENDER_CHANNELS[0]
        mock_send_ws.return_value = {"success": True}

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/agent/escalations/10/resolve",
                json={"chatbot_id": 1},
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            mock_save_msg.assert_called_once()
            mock_send_ws.assert_called_once()

    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_resolve_escalation_not_found(self, mock_verify):
        mock_verify.return_value = {"id": 1, "company_id": 42}
        with patch(
            "app.routes.agent_routes.resolve_escalation",
            return_value=(None, False),
        ):
            with self._patch_jwt_decode(), self._patch_user_repo():
                resp = self.client.post(
                    "/api/agent/escalations/999/resolve",
                    json={"chatbot_id": 1},
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 404)

    def test_resolve_escalation_missing_chatbot_id(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/agent/escalations/10/resolve",
                json={},
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 400)

    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_resolve_escalation_access_denied(self, mock_verify):
        mock_verify.side_effect = PermissionError("Access denied")
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/agent/escalations/10/resolve",
                json={"chatbot_id": 1},
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 403)

    @patch("app.routes.agent_routes.resolve_escalation")
    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_database_member_cannot_resolve_escalation(
        self,
        mock_verify,
        mock_resolve,
    ):
        with self._patch_jwt_decode(role="owner"), self._patch_user_repo(role="member"):
            resp = self.client.post(
                "/api/agent/escalations/10/resolve",
                json={"chatbot_id": 1},
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 403)
        mock_verify.assert_not_called()
        mock_resolve.assert_not_called()

    @patch("app.routes.agent_routes.resolve_escalation")
    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_database_owner_can_resolve_escalation(
        self,
        mock_verify,
        mock_resolve,
    ):
        mock_verify.return_value = {"id": 1, "company_id": 42}
        mock_resolve.return_value = ({**MOCK_RESOLVED, "_ai_resumed": True}, False)
        with self._patch_jwt_decode(role="member"), self._patch_user_repo(role="owner"):
            resp = self.client.post(
                "/api/agent/escalations/10/resolve",
                json={"chatbot_id": 1},
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status_code, 200)
        mock_resolve.assert_called_once_with(10, 1, 42)

    def test_unauthenticated_user_cannot_resolve_escalation(self):
        resp = self.client.post(
            "/api/agent/escalations/10/resolve",
            json={"chatbot_id": 1},
        )
        self.assertEqual(resp.status_code, 401)


    # ------------------------------------------------------------------ #
    #  Agent reply (POST /api/conversations/<id>/agent-reply)
    # ------------------------------------------------------------------ #

    @patch("app.routes.agent_routes.send_wasender_text_message")
    @patch("app.services.channel_delivery_service.get_wasender_channel_by_id")
    @patch("app.routes.agent_routes.send_telegram_message")
    @patch("app.services.channel_delivery_service.get_telegram_channel_by_id")
    @patch("app.routes.agent_routes.send_whatsapp_message")
    @patch("app.services.channel_delivery_service.get_whatsapp_channel_by_id")
    @patch("app.routes.agent_routes.save_message")
    @patch("app.routes.agent_routes.get_conversation_by_id_and_chatbot")
    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_agent_reply_whatsapp_success(
        self,
        mock_verify,
        mock_get_conv,
        mock_save_msg,
        mock_get_wa_channels,
        mock_send_wa,
        mock_get_tg_channels,
        mock_send_tg,
        mock_get_ws_channels,
        mock_send_ws,
    ):
        mock_get_conv.return_value = MOCK_CONVERSATION_WHATSAPP
        mock_get_wa_channels.return_value = MOCK_WHATSAPP_CHANNELS[0]
        mock_send_wa.return_value = MagicMock(status_code=200, json=MagicMock(return_value={"messages": [{"id": "sent"}]}))

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/conversations/100/agent-reply",
                json={"chatbot_id": 1, "text": "Hello customer, how can I help?"},
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            mock_save_msg.assert_called_once()
            mock_send_wa.assert_called_once()

    @patch("app.routes.agent_routes.send_wasender_text_message")
    @patch("app.services.channel_delivery_service.get_wasender_channel_by_id")
    @patch("app.routes.agent_routes.send_telegram_message")
    @patch("app.services.channel_delivery_service.get_telegram_channel_by_id")
    @patch("app.routes.agent_routes.send_whatsapp_message")
    @patch("app.services.channel_delivery_service.get_whatsapp_channel_by_id")
    @patch("app.routes.agent_routes.save_message")
    @patch("app.routes.agent_routes.get_conversation_by_id_and_chatbot")
    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_agent_reply_telegram_success(
        self,
        mock_verify,
        mock_get_conv,
        mock_save_msg,
        mock_get_wa_channels,
        mock_send_wa,
        mock_get_tg_channels,
        mock_send_tg,
        mock_get_ws_channels,
        mock_send_ws,
    ):
        mock_get_conv.return_value = MOCK_CONVERSATION_TELEGRAM
        mock_get_tg_channels.return_value = MOCK_TELEGRAM_CHANNELS[0]
        mock_send_tg.return_value = {"ok": True, "result": {"message_id": 2}}

        with self._patch_jwt_decode(), self._patch_user_repo(), patch("app.routes.agent_routes.resolve_escalation") as resolve:
            resp = self.client.post(
                "/api/conversations/101/agent-reply",
                json={"chatbot_id": 1, "text": "Hello from Telegram side", "action_id": 10},
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            mock_save_msg.assert_called_once()
            mock_send_tg.assert_called_once()
            resolve.assert_not_called()

    @patch("app.routes.agent_routes.send_wasender_text_message")
    @patch("app.services.channel_delivery_service.get_wasender_channel_by_id")
    @patch("app.routes.agent_routes.send_telegram_message")
    @patch("app.services.channel_delivery_service.get_telegram_channel_by_id")
    @patch("app.routes.agent_routes.send_whatsapp_message")
    @patch("app.services.channel_delivery_service.get_whatsapp_channel_by_id")
    @patch("app.routes.agent_routes.save_message")
    @patch("app.routes.agent_routes.get_conversation_by_id_and_chatbot")
    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_agent_reply_wasender_success(
        self,
        mock_verify,
        mock_get_conv,
        mock_save_msg,
        mock_get_wa_channels,
        mock_send_wa,
        mock_get_tg_channels,
        mock_send_tg,
        mock_get_ws_channels,
        mock_send_ws,
    ):
        mock_get_conv.return_value = MOCK_CONVERSATION_WASENDER
        mock_get_ws_channels.return_value = MOCK_WASENDER_CHANNELS[0]
        mock_send_ws.return_value = {"success": True}

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/conversations/102/agent-reply",
                json={"chatbot_id": 1, "text": "Hello via Wasender"},
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            mock_save_msg.assert_called_once()
            mock_send_ws.assert_called_once()

    def test_agent_reply_missing_chatbot_id(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/conversations/100/agent-reply",
                json={"text": "Hello"},
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 400)

    def test_agent_reply_missing_text(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/conversations/100/agent-reply",
                json={"chatbot_id": 1},
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 400)

    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_agent_reply_conversation_not_found(self, mock_verify):
        with patch(
            "app.routes.agent_routes.get_conversation_by_id_and_chatbot",
            return_value=None,
        ):
            with self._patch_jwt_decode(), self._patch_user_repo():
                resp = self.client.post(
                    "/api/conversations/999/agent-reply",
                    json={"chatbot_id": 1, "text": "Hello"},
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 404)

    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_agent_reply_access_denied(self, mock_verify):
        mock_verify.side_effect = PermissionError("Access denied")
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/conversations/100/agent-reply",
                json={"chatbot_id": 1, "text": "Hello"},
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 403)

    @patch("app.routes.agent_routes.send_whatsapp_message")
    @patch("app.services.channel_delivery_service.get_whatsapp_channel_by_id")
    @patch("app.routes.agent_routes.save_message")
    @patch("app.routes.agent_routes.get_conversation_by_id_and_chatbot")
    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_agent_reply_dispatch_failure(
        self,
        mock_verify,
        mock_get_conv,
        mock_save_msg,
        mock_get_wa_channels,
        mock_send_wa,
    ):
        mock_get_conv.return_value = MOCK_CONVERSATION_WHATSAPP
        mock_get_wa_channels.return_value = []  # no channels ? dispatch failure
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/conversations/100/agent-reply",
                json={"chatbot_id": 1, "text": "Hello"},
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 409)
            data = resp.get_json()
            self.assertIn("original channel", data.get("message", ""))
            mock_save_msg.assert_not_called()


    # ------------------------------------------------------------------ #
    #  Resolve escalation end-of-session message not sent when
    #  conversation_not_found (silent degradation)
    # ------------------------------------------------------------------ #

    @patch("app.routes.agent_routes.save_message")
    @patch("app.routes.agent_routes.get_conversation_by_id_and_chatbot")
    @patch("app.routes.agent_routes.is_conversation_escalated", return_value=False)
    @patch("app.routes.agent_routes.resolve_escalation")
    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_resolve_escalation_no_conversation_found(
        self,
        mock_verify,
        mock_resolve,
        mock_is_escalated,
        mock_get_conv,
        mock_save_msg,
    ):
        mock_verify.return_value = {"id": 1, "company_id": 42}
        mock_resolve.return_value = (MOCK_RESOLVED, True)
        mock_get_conv.return_value = None
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/agent/escalations/10/resolve",
                json={"chatbot_id": 1},
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            mock_get_conv.assert_called_once()
            # save_message should NOT be called since conversation is None
            mock_save_msg.assert_not_called()

    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_resolve_escalation_already_resolved(self, mock_verify):
        mock_verify.return_value = {"id": 1, "company_id": 42}
        with patch(
            "app.routes.agent_routes.resolve_escalation",
            return_value=({**MOCK_RESOLVED, "_ai_resumed": True}, False),
        ), patch(
            "app.routes.agent_routes.save_message",
        ) as save_message, patch(
            "app.routes.agent_routes.get_conversation_by_id_and_chatbot",
        ) as get_conversation, patch(
            "app.routes.agent_routes.send_whatsapp_message",
        ) as send_whatsapp, patch(
            "app.routes.agent_routes.send_telegram_message",
        ) as send_telegram, patch(
            "app.routes.agent_routes.send_wasender_text_message",
        ) as send_wasender:
            with self._patch_jwt_decode(), self._patch_user_repo():
                resp = self.client.post(
                    "/api/agent/escalations/10/resolve",
                    json={"chatbot_id": 1},
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.get_json()["data"]["already_resolved"])
                save_message.assert_not_called()
                get_conversation.assert_not_called()
                send_whatsapp.assert_not_called()
                send_telegram.assert_not_called()
                send_wasender.assert_not_called()

    @patch("app.routes.agent_routes.save_message")
    @patch("app.routes.agent_routes.get_conversation_by_id_and_chatbot")
    @patch("app.routes.agent_routes.is_conversation_escalated", return_value=True)
    @patch("app.routes.agent_routes.resolve_escalation")
    @patch("app.routes.agent_routes.verify_chatbot_access")
    def test_resolving_one_action_does_not_resume_ai_when_another_escalation_remains(
        self,
        mock_verify,
        mock_resolve,
        mock_is_escalated,
        mock_get_conversation,
        mock_save_message,
    ):
        mock_verify.return_value = {"id": 1, "company_id": 42}
        mock_resolve.return_value = (MOCK_RESOLVED, True)

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/agent/escalations/10/resolve",
                json={"chatbot_id": 1},
                headers={"Authorization": "Bearer test-token"},
            )

        self.assertEqual(resp.status_code, 200)
        mock_is_escalated.assert_called_once_with(100, 1)
        mock_get_conversation.assert_not_called()
        mock_save_message.assert_not_called()
