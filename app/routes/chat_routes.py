from flask import Blueprint, request, jsonify
from app.decorators.auth_decorator import token_required

# import your existing chatbot function
from app.services.gemini_service import generate_response

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

        # use a dummy user id for testing
        reply = generate_response(user_message, "test_user")

        return jsonify({
            "status": "success",
            "reply": reply
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500