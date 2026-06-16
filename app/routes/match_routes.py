from flask import Blueprint, jsonify, request

from app.services.match_service import check_pdf_config_match
from app.services.settings_service import update_chatbot_runtime
from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access, role_required

match_blueprint = Blueprint("match", __name__)


@match_blueprint.route("/api/match/check", methods=["POST"])
@token_required
@role_required("admin", "owner")
def check_match():
    try:
        data = request.get_json() or {}
        profile_name = data.get("profile_name")
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        access = verify_chatbot_access(chatbot_id)

        result = check_pdf_config_match(
            profile_name=profile_name,
            chatbot_id=chatbot_id,
            company_id=access["company_id"],
        )

        if result.get("validation_status") == "completed":
            last_match_result = bool(result.get("match", False))
        else:
            last_match_result = None

        update_chatbot_runtime({
            "last_match_result": last_match_result,
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
