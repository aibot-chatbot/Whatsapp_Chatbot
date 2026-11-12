from flask import Blueprint, g, jsonify, request

from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access
from app.database.agent_action_repository import get_agent_actions_by_conversation_and_chatbot
from app.database.conversation_repository import (
    get_conversations_by_bot,
    get_conversations_for_company,
)
from app.database.message_repository import get_messages_by_conversation_and_chatbot
from app.utils.api_errors import server_error

conversation_blueprint = Blueprint("conversations", __name__)


@conversation_blueprint.route("/api/conversations", methods=["GET"])
@token_required
def get_conversations():
    """
    Fetches conversations for a specific chatbot (?chatbot_id=), or,
    company-wide (?company=1), across every non-archived, non-deleted bot
    the caller's company owns. chatbot_id takes precedence when both are
    given. Both forms return rows annotated with bot_name and message_count.
    """
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)

        if chatbot_id:
            # Security check
            verify_chatbot_access(chatbot_id)

            conversations = get_conversations_by_bot(chatbot_id)

            return jsonify({
                "status": "success",
                "data": conversations
            }), 200

        if request.args.get("company", type=int):
            conversations = get_conversations_for_company(g.company_id)

            return jsonify({
                "status": "success",
                "data": conversations
            }), 200

        return jsonify({
            "status": "error",
            "message": "chatbot_id is required"
        }), 400

    except PermissionError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 403
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 401
    except Exception as e:
        return server_error("get_conversations", e)


@conversation_blueprint.route("/api/conversations/<int:conversation_id>/intents", methods=["GET"])
@token_required
def get_conversation_intents(conversation_id):
    """
    Fetches the agent_actions rows detected for a conversation: message_id,
    intent, confidence, action_type, reason, status. Never returns payload --
    it may contain raw model output.
    """
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)

        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        # Security check: Ensure the user has access to this bot
        verify_chatbot_access(chatbot_id)

        intents = get_agent_actions_by_conversation_and_chatbot(
            conversation_id,
            chatbot_id,
            g.company_id,
        )

        if intents is None:
            return jsonify({
                "status": "error",
                "message": "Conversation not found"
            }), 404

        return jsonify({
            "status": "success",
            "data": intents
        }), 200

    except PermissionError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 403
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 401
    except Exception as e:
        return server_error("get_conversation_intents", e)


@conversation_blueprint.route("/api/conversations/<int:conversation_id>/messages", methods=["GET"])
@token_required
def get_conversation_messages(conversation_id):
    """
    Fetches the full chat transcript for a specific conversation.
    """
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        # Security check: Ensure the user has access to this bot
        verify_chatbot_access(chatbot_id)

        messages = get_messages_by_conversation_and_chatbot(conversation_id, chatbot_id)

        if messages is None:
            return jsonify({
                "status": "error",
                "message": "Conversation not found"
            }), 404

        return jsonify({
            "status": "success",
            "data": messages
        }), 200

    except PermissionError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 403
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 401
    except Exception as e:
        return server_error("get_conversation_messages", e)
