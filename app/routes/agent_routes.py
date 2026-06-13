from flask import Blueprint, jsonify, request
import logging

from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access
from app.database.agent_action_repository import get_pending_escalations, resolve_escalation
from app.database.conversation_repository import get_conversation_by_id_and_chatbot
from app.database.message_repository import save_message

# Import dispatchers
from app.utils.whatsapp_utils import send_message as send_whatsapp_message
from app.utils.telegram_utils import send_telegram_message
from app.services.wasender_service import send_wasender_text_message
from app.database.bot_repository import get_bot_by_id
from app.database.telegram_channel_repository import get_telegram_channels_by_chatbot
from app.database.wasender_channel_repository import get_wasender_channels_by_chatbot
from app.database.whatsapp_channel_repository import get_whatsapp_channels_by_chatbot

agent_blueprint = Blueprint("agent", __name__)

@agent_blueprint.route("/api/agent/escalations", methods=["GET"])
@token_required
def get_escalations():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400

        verify_chatbot_access(chatbot_id)

        escalations = get_pending_escalations(chatbot_id)
        return jsonify({"status": "success", "data": escalations}), 200

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        logging.error(f"Error fetching escalations: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@agent_blueprint.route("/api/agent/escalations/<int:action_id>/resolve", methods=["POST"])
@token_required
def resolve_esc(action_id):
    try:
        data = request.get_json() or {}
        chatbot_id = data.get("chatbot_id")

        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400

        verify_chatbot_access(chatbot_id)
        
        resolved = resolve_escalation(action_id, chatbot_id)
        if not resolved:
            return jsonify({"status": "error", "message": "Escalation not found or already resolved."}), 404

        return jsonify({"status": "success", "message": "Escalation resolved."}), 200

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@agent_blueprint.route("/api/conversations/<int:conversation_id>/agent-reply", methods=["POST"])
@token_required
def agent_reply(conversation_id):
    try:
        data = request.get_json() or {}
        chatbot_id = data.get("chatbot_id")
        text = data.get("text")
        action_id = data.get("action_id") # Optional: resolve the action if provided

        if not chatbot_id or not text:
            return jsonify({"status": "error", "message": "chatbot_id and text are required"}), 400

        verify_chatbot_access(chatbot_id)

        conversation = get_conversation_by_id_and_chatbot(conversation_id, chatbot_id)
        if not conversation:
            return jsonify({"status": "error", "message": "Conversation not found"}), 404

        source_channel = conversation.get("source_channel")
        customer_phone = conversation.get("customer_phone")
        platform_user_id = conversation.get("platform_user_id")

        # Save agent's message to DB
        save_message(
            conversation_id=conversation_id,
            chatbot_id=chatbot_id,
            role="assistant", # Treat agent as assistant visually for now
            content=text,
            message_type="text",
            metadata={"sent_by": "human_agent"}
        )

        # Dispatch
        try:
            if source_channel == "whatsapp":
                channels = get_whatsapp_channels_by_chatbot(chatbot_id)
                if not channels:
                    raise ValueError("No active WhatsApp channel found.")
                # We simply use the global send_message which uses WABA from db
                phone = customer_phone or platform_user_id
                send_whatsapp_message({"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": text}}, channel=channels[0])
                
            elif source_channel == "telegram":
                channels = get_telegram_channels_by_chatbot(chatbot_id)
                if not channels:
                    raise ValueError("No active Telegram channel found.")
                send_telegram_message(channels[0]["bot_token"], platform_user_id, text)

            elif source_channel == "wasender":
                channels = get_wasender_channels_by_chatbot(chatbot_id)
                if not channels:
                    raise ValueError("No active WASender channel found.")
                send_wasender_text_message(channels[0]["api_key"], platform_user_id or customer_phone, text)

            else:
                raise ValueError(f"Unsupported channel: {source_channel}")

        except Exception as dispatch_e:
            logging.error(f"Failed to dispatch agent message: {dispatch_e}")
            return jsonify({"status": "error", "message": f"Message saved, but failed to send: {str(dispatch_e)}"}), 500

        # Auto-resolve escalation if action_id is provided
        if action_id:
            resolve_escalation(action_id, chatbot_id)

        return jsonify({"status": "success", "message": "Reply sent successfully."}), 200

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        logging.error(f"Agent reply error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
