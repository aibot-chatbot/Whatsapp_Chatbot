from flask import Blueprint, jsonify, request

from app.services.gemini_service import generate_response
from app.services.settings_service import get_deployed_runtime
from app.services.profile_service import get_profile_by_name
from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access

testbot_blueprint = Blueprint("testbot", __name__)
TESTBOT_SESSION_ID = "web_testbot_session"

@testbot_blueprint.route("/api/testbot/context", methods=["GET"])
@token_required
def get_testbot_context():
    try:
        chatbot_id = request.args.get("chatbot_id", 1, type=int)
        verify_chatbot_access(chatbot_id)
        deployed = get_deployed_runtime(chatbot_id)
        profile_name = deployed.get("deployed_profile_name", "")
        profile = get_profile_by_name(profile_name, chatbot_id) if profile_name else {}

        return jsonify({
            "status": "success",
            "data": {
                "active_profile": profile_name,
                "bot_name": (profile or {}).get("bot_name", ""),
                "company_name": (profile or {}).get("company_name", ""),
                "active_pdf": deployed.get("deployed_pdf_file_name", "")
            }
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@testbot_blueprint.route("/api/testbot/chat", methods=["POST"])
@token_required
def chat_with_testbot():
    try:
        data = request.get_json() or {}
        user_message = (data.get("message") or "").strip()

        if not user_message:
            return jsonify({
                "status": "error",
                "message": "Message is required."
            }), 400

        chatbot_id = request.args.get("chatbot_id", 1, type=int)
        verify_chatbot_access(chatbot_id)
        reply = generate_response(user_message, TESTBOT_SESSION_ID, chatbot_id)

        return jsonify({
            "status": "success",
            "data": {
                "reply": reply
            }
        }), 200
    except PermissionError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 403
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500