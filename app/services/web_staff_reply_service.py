"""Persist staff replies for the original website visitor to fetch."""

import logging

from app.database.agent_action_repository import is_conversation_escalated
from app.database.bot_repository import get_bot_by_id
from app.database.message_repository import save_message
from app.database.web_widget_repository import get_widget_by_chatbot_id
from app.services.conversation_delivery_lock import conversation_delivery_lock
from app.services.web_widget_service import WidgetError, validate_session_id


class WebStaffReplyError(Exception):
    def __init__(self, message, *, code, status_code):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def send_web_staff_reply(conversation, *, company_id, actor_user_id, text):
    """Accept a reply without ending the human handoff or claiming receipt."""
    if not isinstance(text, str) or not text.strip() or len(text.strip()) > 2000:
        raise WebStaffReplyError(
            "Reply must contain between 1 and 2000 characters.",
            code="INVALID_REPLY", status_code=400,
        )
    if not actor_user_id or not company_id:
        raise WebStaffReplyError(
            "A verified staff identity is required.", code="STAFF_REQUIRED", status_code=403,
        )
    try:
        validate_session_id(conversation.get("platform_user_id"))
    except (WidgetError, AttributeError, TypeError):
        raise WebStaffReplyError(
            "This conversation has no website visitor who can receive replies.",
            code="WEB_VISITOR_UNAVAILABLE", status_code=409,
        ) from None
    if conversation.get("source_channel") != "web" or conversation.get("source_channel_id") is not None:
        raise WebStaffReplyError(
            "This conversation is not bound to a website visitor.",
            code="WEB_VISITOR_UNAVAILABLE", status_code=409,
        )

    conversation_id = conversation["id"]
    chatbot_id = conversation["chatbot_id"]
    try:
        with conversation_delivery_lock(conversation_id):
            bot = get_bot_by_id(chatbot_id)
            if not bot or not bot.get("is_active") or bot.get("company_id") != company_id:
                raise WebStaffReplyError(
                    "This chatbot is unavailable for website replies.",
                    code="WEB_WIDGET_DISABLED", status_code=409,
                )
            widget = get_widget_by_chatbot_id(chatbot_id, company_id)
            if not widget or not widget.get("is_enabled"):
                raise WebStaffReplyError(
                    "Website chat is disabled. Enable it before replying.",
                    code="WEB_WIDGET_DISABLED", status_code=409,
                )
            if not is_conversation_escalated(conversation_id, chatbot_id, conversation=conversation):
                raise WebStaffReplyError(
                    "This conversation is no longer waiting for a staff reply. Refresh the conversation.",
                    code="HUMAN_HANDOFF_REQUIRED", status_code=409,
                )
            message = save_message(
                conversation_id=conversation_id,
                sender_type="human",
                message_text=text.strip(),
                message_type="text",
                delivery_status="sent",
                ai_generated=False,
                actor_user_id=actor_user_id,
            )
            if not isinstance(message, dict) or not message.get("id"):
                raise RuntimeError("Missing message persistence acknowledgement")
            return {"delivery_status": "accepted", "message_id": message["id"]}
    except WebStaffReplyError:
        raise
    except Exception as error:
        logging.error("Website staff reply failed (%s)", type(error).__name__)
        raise WebStaffReplyError(
            "The reply could not be confirmed saved. Refresh the conversation before retrying.",
            code="WEB_REPLY_UNAVAILABLE", status_code=503,
        ) from None
