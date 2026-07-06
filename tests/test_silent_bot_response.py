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


class TestSilentBotResponse(unittest.TestCase):
    """Tests for the <SILENT_BOT_RESPONSE> handling."""

    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True

    # ------------------------------------------------------------------ #
    #  chat_pipeline_service — prepare_chat_prompt escalation check
    # ------------------------------------------------------------------ #
    # The pipeline calls get_or_create_conversation (which uses
    # app.database.conversation_repository.supabase) and then
    # checks is_conversation_escalated (which uses
    # app.database.agent_action_repository.supabase).
    # We patch both supabase references plus the escalation function.

    @patch("app.database.agent_action_repository.supabase")
    @patch("app.database.conversation_repository.supabase")
    @patch("app.database.chat_history_repository.supabase")
    @patch("app.database.agent_action_repository.is_conversation_escalated")
    def test_prepare_chat_prompt_escalated_returns_silent(
        self,
        mock_is_escalated,
        mock_chat_hist_supa,
        mock_conv_supa,
        mock_action_supa,
    ):
        mock_is_escalated.return_value = True

        from app.services.chat_pipeline_service import prepare_chat_prompt

        result = prepare_chat_prompt(
            message="Hello",
            customer_id="+60123456789",
            chatbot_id=1,
            source_channel="whatsapp",
        )
        self.assertEqual(result["direct_reply"], "<SILENT_BOT_RESPONSE>")
        self.assertEqual(result["intent"], "escalated_to_human")
        self.assertIsNone(result["prompt"])

    @patch("app.database.bot_repository.supabase")
    @patch("app.database.agent_action_repository.supabase")
    @patch("app.database.conversation_repository.supabase")
    @patch("app.database.chat_history_repository.supabase")
    @patch("app.database.agent_action_repository.is_conversation_escalated")
    def test_prepare_chat_prompt_not_escalated_returns_normal(
        self,
        mock_is_escalated,
        mock_chat_hist_supa,
        mock_conv_supa,
        mock_action_supa,
        mock_bot_supa,
    ):
        mock_is_escalated.return_value = False

        from app.services.chat_pipeline_service import prepare_chat_prompt

        result = prepare_chat_prompt(
            message="Hello",
            customer_id="+60123456789",
            chatbot_id=1,
            source_channel="whatsapp",
        )
        self.assertNotEqual(result.get("direct_reply"), "<SILENT_BOT_RESPONSE>")

    # ------------------------------------------------------------------ #
    #  agent_action_repository — is_conversation_escalated
    # ------------------------------------------------------------------ #

    @patch("app.database.agent_action_repository.supabase")
    def test_is_conversation_escalated_returns_true_when_detected(self, mock_supabase):
        from app.database.agent_action_repository import is_conversation_escalated

        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.in_.return_value.limit.return_value.execute.return_value = MagicMock(data=[{"id": 1}])

        result = is_conversation_escalated(100)
        self.assertTrue(result)

    @patch("app.database.agent_action_repository.supabase")
    def test_is_conversation_escalated_returns_false_when_empty(self, mock_supabase):
        from app.database.agent_action_repository import is_conversation_escalated

        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.in_.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        result = is_conversation_escalated(999)
        self.assertFalse(result)


    # ------------------------------------------------------------------ #
    #  WhatsApp channel — process_whatsapp_message
    # ------------------------------------------------------------------ #

    @patch("app.database.processed_message_repository.supabase")
    @patch("app.utils.whatsapp_utils.update_workflow_state")
    @patch("app.utils.whatsapp_utils.save_message")
    @patch("app.utils.whatsapp_utils.get_or_create_conversation")
    @patch("app.utils.whatsapp_utils.is_processed")
    @patch("app.utils.whatsapp_utils.get_whatsapp_channel_by_phone_number_id")
    @patch("app.utils.whatsapp_utils.generate_response")
    def test_whatsapp_silent_response_does_not_send(
        self,
        mock_generate,
        mock_get_channel,
        mock_is_processed,
        mock_get_conv,
        mock_save_msg,
        mock_workflow,
        mock_processed_supa,
    ):
        mock_get_channel.return_value = {"id": 1, "chatbot_id": 1}
        mock_is_processed.return_value = False
        mock_get_conv.return_value = {"id": 100}
        mock_generate.return_value = "<SILENT_BOT_RESPONSE>"

        from app.utils.whatsapp_utils import process_whatsapp_message

        # Build minimal WhatsApp webhook payload
        body = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "12345"},
                        "contacts": [{"wa_id": "+60123456789", "profile": {"name": "Test"}}],
                        "messages": [{"id": "msg-1", "type": "text", "text": {"body": "Hello"}}],
                    }
                }]
            }]
        }

        process_whatsapp_message(body)

        # Should mark as processed and update workflow, but never send
        mock_generate.assert_called_once()
        mock_workflow.assert_any_call(1, "COMPLETED", "<SILENT_BOT_RESPONSE>", "+60123456789")

    @patch("app.database.processed_message_repository.supabase")
    @patch("app.utils.whatsapp_utils.send_message")
    @patch("app.utils.whatsapp_utils.update_workflow_state")
    @patch("app.utils.whatsapp_utils.save_message")
    @patch("app.utils.whatsapp_utils.get_or_create_conversation")
    @patch("app.utils.whatsapp_utils.is_processed")
    @patch("app.utils.whatsapp_utils.get_whatsapp_channel_by_phone_number_id")
    @patch("app.utils.whatsapp_utils.generate_response")
    def test_whatsapp_normal_response_does_send(
        self,
        mock_generate,
        mock_get_channel,
        mock_is_processed,
        mock_get_conv,
        mock_save_msg,
        mock_workflow,
        mock_send,
        mock_processed_supa,
    ):
        mock_get_channel.return_value = {"id": 1, "chatbot_id": 1, "phone_number_id": "12345", "access_token": "tok"}
        mock_is_processed.return_value = False
        mock_get_conv.return_value = {"id": 100}
        mock_generate.return_value = "Hello! How can I help you?"

        from app.utils.whatsapp_utils import process_whatsapp_message

        body = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "12345"},
                        "contacts": [{"wa_id": "+60123456789", "profile": {"name": "Test"}}],
                        "messages": [{"id": "msg-2", "type": "text", "text": {"body": "Hi"}}],
                    }
                }]
            }]
        }

        process_whatsapp_message(body)

        # Normal response — should send via send_message
        mock_generate.assert_called_once()
        mock_send.assert_called_once()
        # Verify the silent sentinel does not leak
        call_text = mock_send.call_args[0][0]
        self.assertNotIn("<SILENT_BOT_RESPONSE>", str(call_text))

    # ------------------------------------------------------------------ #
    #  Telegram channel — process_telegram_update
    # ------------------------------------------------------------------ #

    @patch("app.database.processed_telegram_update_repository.supabase")
    @patch("app.database.conversation_repository.supabase")
    @patch("app.database.message_repository.supabase")
    @patch("app.utils.telegram_utils.save_processed_telegram_update")
    @patch("app.utils.telegram_utils.send_telegram_contact_request")
    @patch("app.utils.telegram_utils.send_telegram_message")
    @patch("app.utils.telegram_utils.save_message")
    @patch("app.utils.telegram_utils.get_or_create_platform_conversation")
    @patch("app.utils.telegram_utils.is_telegram_update_processed")
    @patch("app.utils.telegram_utils.get_telegram_channel_by_secret")
    @patch("app.utils.telegram_utils.generate_response")
    def test_telegram_silent_response_does_not_send(
        self,
        mock_generate,
        mock_get_channel,
        mock_is_processed,
        mock_get_conv,
        mock_save_msg,
        mock_send_tg,
        mock_send_contact_req,
        mock_save_processed_tg,
        mock_msg_supa,
        mock_conv_supa,
        mock_processed_supa,
    ):
        mock_get_channel.return_value = {"id": 1, "chatbot_id": 1, "bot_token": "tok"}
        mock_is_processed.return_value = False
        mock_get_conv.return_value = {"id": 100, "customer_phone": "+60123456789"}
        mock_generate.return_value = "<SILENT_BOT_RESPONSE>"

        from app.utils.telegram_utils import process_telegram_update

        update = {
            "update_id": 1001,
            "message": {
                "message_id": 2001,
                "chat": {"id": 12345},
                "from": {"id": 67890, "first_name": "Test"},
                "text": "Hello",
            }
        }

        process_telegram_update(update, "test-secret")

        # Should mark as processed, but never send via Telegram
        mock_generate.assert_called_once()
        mock_save_processed_tg.assert_called_once_with(1, 1001)
        mock_send_tg.assert_not_called()

    @patch("app.database.processed_telegram_update_repository.supabase")
    @patch("app.database.conversation_repository.supabase")
    @patch("app.database.message_repository.supabase")
    @patch("app.utils.telegram_utils.save_processed_telegram_update")
    @patch("app.utils.telegram_utils.send_telegram_contact_request")
    @patch("app.utils.telegram_utils.send_telegram_message")
    @patch("app.utils.telegram_utils.save_message")
    @patch("app.utils.telegram_utils.get_or_create_platform_conversation")
    @patch("app.utils.telegram_utils.is_telegram_update_processed")
    @patch("app.utils.telegram_utils.get_telegram_channel_by_secret")
    @patch("app.utils.telegram_utils.generate_response")
    def test_telegram_normal_response_does_send(
        self,
        mock_generate,
        mock_get_channel,
        mock_is_processed,
        mock_get_conv,
        mock_save_msg,
        mock_send_tg,
        mock_send_contact_req,
        mock_save_processed_tg,
        mock_msg_supa,
        mock_conv_supa,
        mock_processed_supa,
    ):
        mock_get_channel.return_value = {"id": 1, "chatbot_id": 1, "bot_token": "tok"}
        mock_is_processed.return_value = False
        mock_get_conv.return_value = {"id": 100, "customer_phone": "+60123456789"}
        mock_generate.return_value = "Hi there! How can I help?"

        from app.utils.telegram_utils import process_telegram_update

        update = {
            "update_id": 1002,
            "message": {
                "message_id": 2002,
                "chat": {"id": 12346},
                "from": {"id": 67891, "first_name": "Test2"},
                "text": "Hi",
            }
        }

        process_telegram_update(update, "test-secret")

        # Normal response — should send
        mock_generate.assert_called_once()
        mock_send_tg.assert_called_once()
        call_text = mock_send_tg.call_args[0][2]
        self.assertNotIn("<SILENT_BOT_RESPONSE>", str(call_text))

    # ------------------------------------------------------------------ #
    #  Wasender channel — process_wasender_webhook
    # ------------------------------------------------------------------ #

    @patch("app.database.processed_wasender_message_repository.supabase")
    @patch("app.database.conversation_repository.supabase")
    @patch("app.database.message_repository.supabase")
    @patch("app.services.wasender_service.save_processed_wasender_message")
    @patch("app.services.wasender_service.send_wasender_text_message")
    @patch("app.services.wasender_service.save_message")
    @patch("app.services.wasender_service.get_or_create_conversation")
    @patch("app.services.wasender_service.is_wasender_message_processed")
    @patch("app.services.wasender_service.extract_wasender_message")
    @patch("app.services.wasender_service.get_wasender_channel_by_secret")
    @patch("app.services.wasender_service.generate_response")
    def test_wasender_silent_response_does_not_send(
        self,
        mock_generate,
        mock_get_channel,
        mock_extract,
        mock_is_processed,
        mock_get_conv,
        mock_save_msg,
        mock_send_text,
        mock_save_processed_ws,
        mock_msg_supa,
        mock_conv_supa,
        mock_processed_supa,
    ):
        mock_get_channel.return_value = {"id": 1, "chatbot_id": 1, "api_key": "test-api-key"}
        mock_extract.return_value = {
            "event": "messages.received",
            "message_id": "wsg-1",
            "from_me": False,
            "customer_phone": "+60123456789",
            "customer_name": "Test",
            "message_text": "Hello",
        }
        mock_is_processed.return_value = False
        mock_get_conv.return_value = {"id": 100}
        mock_generate.return_value = "<SILENT_BOT_RESPONSE>"

        from app.services.wasender_service import process_wasender_webhook

        process_wasender_webhook({"event": "messages.received", "data": {}}, "test-secret")

        # Should mark as processed, but never send
        mock_generate.assert_called_once()
        mock_save_processed_ws.assert_called_once_with(1, "wsg-1")
        mock_send_text.assert_not_called()
        # No interactive message function exists

    @patch("app.database.processed_wasender_message_repository.supabase")
    @patch("app.database.conversation_repository.supabase")
    @patch("app.database.message_repository.supabase")
    @patch("app.services.wasender_service.save_processed_wasender_message")
    @patch("app.services.wasender_service.send_wasender_text_message")
    @patch("app.services.wasender_service.save_message")
    @patch("app.services.wasender_service.get_or_create_conversation")
    @patch("app.services.wasender_service.is_wasender_message_processed")
    @patch("app.services.wasender_service.extract_wasender_message")
    @patch("app.services.wasender_service.get_wasender_channel_by_secret")
    @patch("app.services.wasender_service.generate_response")
    def test_wasender_normal_response_does_send(
        self,
        mock_generate,
        mock_get_channel,
        mock_extract,
        mock_is_processed,
        mock_get_conv,
        mock_save_msg,
        mock_send_text,
        mock_save_processed_ws,
        mock_msg_supa,
        mock_conv_supa,
        mock_processed_supa,
    ):
        mock_get_channel.return_value = {"id": 1, "chatbot_id": 1, "api_key": "test-api-key"}
        mock_extract.return_value = {
            "event": "messages.received",
            "message_id": "wsg-2",
            "from_me": False,
            "customer_phone": "+60123456789",
            "customer_name": "Test",
            "message_text": "Hi",
        }
        mock_is_processed.return_value = False
        mock_get_conv.return_value = {"id": 100}
        mock_generate.return_value = "Hello! How can I help?"

        from app.services.wasender_service import process_wasender_webhook

        process_wasender_webhook({"event": "messages.received", "data": {}}, "test-secret")

        # Normal response — should send via text or interactive
        mock_generate.assert_called_once()
        self.assertTrue(mock_send_text.called)
        if mock_send_text.called:
            call_text = mock_send_text.call_args[0][2]
            self.assertNotIn("<SILENT_BOT_RESPONSE>", str(call_text))




