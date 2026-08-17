from flask import Blueprint, request, jsonify
from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access, role_required

# import your existing chatbot function
from app.services.ai_router import generate_response, OPERATION_TEST_CHAT
from app.services.billing_guard import BillingLimitError
from app.services.company_status_service import company_operational_required

# create blueprint
chat_blueprint = Blueprint("chat", __name__)


@chat_blueprint.route("/api/chat/test", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
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
            operation_type=OPERATION_TEST_CHAT,
        )

        return jsonify({
            "status": "success",
            "reply": reply
        }), 200

    except BillingLimitError as e:
        if e.code == "ai_credit_insufficient":
            return jsonify({
                "status": "error",
                "code": "ai_credit_insufficient",
                "message": str(e)
            }), 402
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e),
            "details": e.details or {}
        }), 403
    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
