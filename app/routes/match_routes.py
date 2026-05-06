from flask import Blueprint, jsonify, request

from app.services.match_service import check_pdf_config_match
from app.services.settings_service import update_chatbot_runtime
from app.decorators.auth_decorator import token_required

match_blueprint = Blueprint("match", __name__)


@match_blueprint.route("/api/match/check", methods=["POST"])
@token_required
def check_match():
    try:
        data = request.get_json() or {}
        profile_name = data.get("profile_name")

        result = check_pdf_config_match(profile_name=profile_name)

        chatbot_id = 1
        update_chatbot_runtime({
            "last_match_result": bool(result.get("match", False)),
            "last_match_reason": result.get("reason", ""),
        }, chatbot_id)

        return jsonify({
            "status": "success",
            "data": result
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500