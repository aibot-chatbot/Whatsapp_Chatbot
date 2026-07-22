from flask import Blueprint, jsonify, request, g

from app.services.profile_service import get_profiles, save_profile, delete_profile
from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access, role_required
from app.services.workspace_service import get_workspace_summary, update_workspace_company

profile_blueprint = Blueprint("profile", __name__)


@profile_blueprint.route("/api/workspace", methods=["GET"])
@token_required
def fetch_workspace():
    try:
        return jsonify({
            "status": "success",
            "data": get_workspace_summary(g.company_id, g.authenticated_user),
        }), 200
    except LookupError as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    except Exception:
        return jsonify({
            "status": "error",
            "message": "Unable to retrieve workspace information.",
        }), 500


@profile_blueprint.route("/api/workspace", methods=["PUT"])
@token_required
def update_workspace():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"status": "error", "message": "No data provided."}), 400
        workspace = update_workspace_company(g.company_id, g.authenticated_user, data)
        return jsonify({
            "status": "success",
            "message": "Company information updated successfully.",
            "data": workspace,
        }), 200
    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except LookupError as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    except Exception:
        return jsonify({
            "status": "error",
            "message": "Unable to update company information.",
        }), 500

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
