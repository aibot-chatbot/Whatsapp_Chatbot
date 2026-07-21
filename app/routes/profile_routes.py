from flask import Blueprint, jsonify, request

from app.services.profile_service import get_profiles, save_profile, delete_profile
from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access, role_required

profile_blueprint = Blueprint("profile", __name__)

@profile_blueprint.route("/api/profiles", methods=["GET"])
@token_required
@role_required("admin", "owner")
def fetch_profiles():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        profiles = get_profiles(chatbot_id)
        return jsonify({
            "status": "success",
            "data": profiles
        }), 200
    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@profile_blueprint.route("/api/profiles", methods=["POST"])
@token_required
@role_required("admin", "owner")
def create_profile():
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
        saved_profile = save_profile(data, chatbot_id)

        return jsonify({
            "status": "success",
            "data": saved_profile
        }), 200
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@profile_blueprint.route("/api/profiles/<profile_name>", methods=["DELETE"])
@token_required
@role_required("admin", "owner")
def remove_profile(profile_name):
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        deleted_profile = delete_profile(profile_name, chatbot_id)

        return jsonify({
            "status": "success",
            "data": deleted_profile
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
