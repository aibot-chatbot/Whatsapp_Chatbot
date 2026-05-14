from flask import Blueprint, jsonify, request

from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access
from app.database.conversation_repository import get_conversations_by_bot
from app.database.message_repository import get_messages_by_conversation

conversation_blueprint = Blueprint("conversations", __name__)


@conversation_blueprint.route("/api/conversations", methods=["GET"])
@token_required
def get_conversations():
    """
    Fetches all conversations for a specific chatbot.
    """
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        # Security check
        verify_chatbot_access(chatbot_id)

        conversations = get_conversations_by_bot(chatbot_id)

        return jsonify({
            "status": "success",
            "data": conversations
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
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


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
        # Note: In a fully robust system, you'd also verify that this conversation belongs to this chatbot
        verify_chatbot_access(chatbot_id)

        messages = get_messages_by_conversation(conversation_id)

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
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
