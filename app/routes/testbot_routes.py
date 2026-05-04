from flask import Blueprint, jsonify, request

from app.services.gemini_service import generate_response
from app.services.settings_service import get_settings
from app.services.knowledge_service import get_active_pdf
from app.decorators.auth_decorator import token_required

testbot_blueprint = Blueprint("testbot", __name__)
TESTBOT_SESSION_ID = "web_testbot_session"

@testbot_blueprint.route("/api/testbot/context", methods=["GET"])
@token_required
def get_testbot_context():
    try:
        settings = get_settings() or {}
        active_pdf_data = get_active_pdf() or {}

        return jsonify({
            "status": "success",
            "data": {
                "active_profile": settings.get("active_profile", ""),
                "bot_name": settings.get("bot_name", ""),
                "company_name": settings.get("company_name", ""),
                "active_pdf": active_pdf_data.get("file_name", "")
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

        reply = generate_response(user_message, TESTBOT_SESSION_ID)

        return jsonify({
            "status": "success",
            "data": {
                "reply": reply
            }
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500