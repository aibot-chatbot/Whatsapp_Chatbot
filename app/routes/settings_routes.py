from flask import Blueprint, jsonify, request

from app.services.settings_service import (
    get_settings,
    get_deployed_settings_summary,
    update_settings,
    set_active_profile,
    apply_profile_to_settings,
)
from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access, role_required

settings_blueprint = Blueprint("settings", __name__)

@settings_blueprint.route("/api/settings", methods=["GET"])
@token_required
@role_required("admin", "owner")
def fetch_settings():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)

        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        settings = get_deployed_settings_summary(chatbot_id)
        return jsonify({
            "status": "success",
            "data": settings
        }), 200
    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@settings_blueprint.route("/api/settings", methods=["PUT"])
@token_required
@role_required("admin", "owner")
def save_settings():
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                "status": "error",
                "message": "No data provided"
            }), 400

        chatbot_id = request.args.get("chatbot_id", type=int)

        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        updated_settings = update_settings(data, chatbot_id)

        return jsonify({
            "status": "success",
            "data": updated_settings
        }), 200
    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@settings_blueprint.route("/api/settings/active-profile", methods=["PUT"])
@token_required
@role_required("admin", "owner")
def save_active_profile():
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                "status": "error",
                "message": "No data provided"
            }), 400

        active_profile = data.get("active_profile", "")
        chatbot_id = request.args.get("chatbot_id", type=int)

        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        updated_settings = set_active_profile(active_profile, chatbot_id)

        return jsonify({
            "status": "success",
            "data": updated_settings
        }), 200
    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@settings_blueprint.route("/api/settings/apply-profile", methods=["PUT"])
@token_required
@role_required("admin", "owner")
def apply_profile():
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                "status": "error",
                "message": "No data provided"
            }), 400

        profile_name = data.get("profile_name", "")
        chatbot_id = request.args.get("chatbot_id", type=int)

        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        updated_settings = apply_profile_to_settings(profile_name, chatbot_id)

        return jsonify({
            "status": "success",
            "data": updated_settings,
            "message": f'Profile "{profile_name}" has been deployed to the live bot. Connected channels will use the updated profile and knowledge.'
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

