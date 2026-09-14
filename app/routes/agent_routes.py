from flask import Blueprint, jsonify, request
import logging

from app.decorators.auth_decorator import token_required
from app.utils.access_control import role_required, verify_chatbot_access
from app.database.agent_action_repository import (
    get_pending_escalations,
    is_conversation_escalated,
    resolve_escalation,
)
from app.database.conversation_repository import get_conversation_by_id_and_chatbot
from app.database.message_repository import save_message

# Import dispatchers
from app.utils.whatsapp_utils import send_message as send_whatsapp_message
from app.utils.telegram_utils import send_telegram_message
from app.services.wasender_service import send_wasender_text_message
from app.services.channel_delivery_service import ChannelDeliveryError, get_bound_channel, delivery_accepted
from app.services.conversation_delivery_lock import conversation_delivery_lock

agent_blueprint = Blueprint("agent", __name__)

@agent_blueprint.route("/api/agent/escalations", methods=["GET"])
@token_required
def get_escalations():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400

        access = verify_chatbot_access(chatbot_id)

        filters = {}
        conversation_id = request.args.get("conversation_id", type=int)
        if conversation_id:
            filters["conversation_id"] = conversation_id
        escalations = get_pending_escalations(
            chatbot_id,
            access["company_id"],
            **filters,
        )
        return jsonify({"status": "success", "data": escalations}), 200

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        logging.error(f"Error fetching escalations: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@agent_blueprint.route("/api/agent/escalations/<int:action_id>/resolve", methods=["POST"])
@token_required
@role_required("admin", "owner")
def resolve_esc(action_id):
    try:
        data = request.get_json() or {}
        chatbot_id = data.get("chatbot_id")

        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400

        access = verify_chatbot_access(chatbot_id)
        resolved, changed = resolve_escalation(
            action_id,
            chatbot_id,
            access["company_id"],
        )
        if not resolved:
            return jsonify({"status": "error", "message": "Escalation not found."}), 404

        conversation_id = resolved.get("conversation_id")
        ai_resumed = resolved.get("_ai_resumed")
        if ai_resumed is None:
            ai_resumed = bool(conversation_id) and not is_conversation_escalated(conversation_id, chatbot_id)
        notification_status = "not_sent"
        notification_code = None
        if changed and ai_resumed:
            conversation = get_conversation_by_id_and_chatbot(conversation_id, chatbot_id)
            if conversation and conversation.get("source_channel") in {"telegram", "whatsapp", "wasender"}:
                end_msg = "The customer service session has ended. You are now chatting with the AI assistant again."
                try:
                    with conversation_delivery_lock(conversation_id):
                        if is_conversation_escalated(conversation_id, chatbot_id, conversation=conversation):
                            ai_resumed = False
                        else:
                            _dispatch_conversation_reply(conversation, end_msg)
                            save_message(conversation_id=conversation_id, sender_type="bot", message_text=end_msg,
                                         message_type="text", delivery_status="sent", ai_generated=False)
                            notification_status = "sent"
                except ChannelDeliveryError as error:
                    notification_status = "failed"
                    notification_code = error.code
                except Exception as error:
                    logging.error("Closing notification failed (%s)", type(error).__name__)
                    notification_status = "failed"
                    notification_code = "DELIVERY_FAILED"

        return jsonify({
            "status": "success", "message": "Escalation resolved." if changed else "Escalation was already resolved.",
            "data": {"already_resolved": not changed, "ai_resumed": ai_resumed,
                     "handoff_state": "ai" if ai_resumed else "human",
                     "notification_status": notification_status, "notification_code": notification_code},
        }), 200

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

        if not chatbot_id or not text:
            return jsonify({"status": "error", "message": "chatbot_id and text are required"}), 400

        verify_chatbot_access(chatbot_id)

        conversation = get_conversation_by_id_and_chatbot(conversation_id, chatbot_id)
        if not conversation:
            return jsonify({"status": "error", "message": "Conversation not found"}), 404

        try:
            _dispatch_conversation_reply(conversation, text)
        except ChannelDeliveryError as error:
            return jsonify({"status": "error", "code": error.code, "message": str(error)}), (
                502 if error.code == "DELIVERY_FAILED" else 409
            )
        except Exception as error:
            logging.error("Agent delivery failed (%s)", type(error).__name__)
            return jsonify({"status": "error", "code": "DELIVERY_FAILED", "message": "The provider did not confirm delivery. Check the conversation before retrying."}), 502

        # Persist only after the external channel accepted the message. This
        # prevents an unsupported or unavailable channel from creating a
        # transcript row that claims delivery.
        save_message(
            conversation_id=conversation_id,
            sender_type="bot",
            message_text=text,
            message_type="text",
            delivery_status="sent",
            ai_generated=False,
        )

        return jsonify({"status": "success", "message": "Reply sent successfully.", "data": {"delivery_status": "sent"}}), 200

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        logging.error(f"Agent reply error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def _dispatch_conversation_reply(conversation, text):
    channel = get_bound_channel(conversation)
    source = conversation["source_channel"]
    recipient = conversation.get("platform_user_id") or conversation.get("customer_phone")
    if not recipient:
        raise ChannelDeliveryError("DELIVERY_FAILED", "The conversation recipient is missing.")
    if source == "telegram":
        result = send_telegram_message(channel["bot_token"], recipient, text)
    elif source == "wasender":
        result = send_wasender_text_message(channel["api_key"], recipient, text)
    else:
        from app.utils.whatsapp_utils import get_text_message_input
        result = send_whatsapp_message(get_text_message_input(recipient, text), channel=channel)
    if not delivery_accepted(source, result):
        raise ChannelDeliveryError("DELIVERY_FAILED", "The provider did not confirm delivery. Check the conversation before retrying.")
    return result
