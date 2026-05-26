from flask import Blueprint, request, jsonify
from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access

# import your existing chatbot function
from app.services.ai_router import generate_response

# create blueprint
chat_blueprint = Blueprint("chat", __name__)


@chat_blueprint.route("/api/chat/test", methods=["POST"])
@token_required
def test_chat():
    try:
        data = request.get_json()

        if not data or "message" not in data:
            return jsonify({
                "status": "error",
                "message": "Missing 'message' in request"
            }), 400

        user_message = data["message"]
        chatbot_id = request.args.get("chatbot_id", type=int)

        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)

        # use a dummy user id for testing
        reply = generate_response(
            user_message,
            "test_user",
            chatbot_id=chatbot_id,
            source_channel="web",
        )

        return jsonify({
            "status": "success",
            "reply": reply
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
