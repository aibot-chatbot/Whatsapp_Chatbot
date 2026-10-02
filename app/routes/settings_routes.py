from flask import Blueprint, g, jsonify, request

from app.services.settings_service import (
    get_settings,
    get_deployed_settings_summary,
    update_settings,
    set_active_profile,
    apply_profile_to_settings,
)
from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access, role_required
from app.utils.api_errors import server_error
from app.services.company_status_service import company_operational_required
from app.services.industry_template_service import (
    IndustryTemplateError, get_industry_settings, confirm_industry_template, review_industry_template,
)

settings_blueprint = Blueprint("settings", __name__)


@settings_blueprint.route("/api/settings/industry-template", methods=["GET"])
@token_required
@role_required("admin", "owner")
def industry_template_settings():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify(status="error", message="chatbot_id is required"), 400
        verify_chatbot_access(chatbot_id)
        return jsonify(status="success", data=get_industry_settings(chatbot_id, g.company_id))
    except IndustryTemplateError as exc:
        return jsonify(status="error", code=exc.code, message=str(exc)), exc.status_code
    except PermissionError as exc:
        return jsonify(status="error", message=str(exc)), 403
    except Exception as exc:
        return server_error("industry_template_settings", exc)


@settings_blueprint.route("/api/settings/industry-template/confirm", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def confirm_industry_template_settings():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify(status="error", message="chatbot_id is required"), 400
        verify_chatbot_access(chatbot_id)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(status="error", message="Request body must be a JSON object"), 400
        result = confirm_industry_template(
            chatbot_id, g.company_id, g.user_id,
            payload.get("proposal_id"), payload.get("template_id"),
        )
        return jsonify(status="success", data=result)
    except IndustryTemplateError as exc:
        return jsonify(status="error", code=exc.code, message=str(exc)), exc.status_code
    except PermissionError as exc:
        return jsonify(status="error", message=str(exc)), 403
    except Exception as exc:
        return server_error("confirm_industry_template", exc)


@settings_blueprint.route("/api/settings/industry-template/review", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def review_industry_template_settings():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify(status="error", message="chatbot_id is required"), 400
        verify_chatbot_access(chatbot_id)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(status="error", message="Request body must be a JSON object"), 400
        return jsonify(status="success", data=review_industry_template(
            chatbot_id, g.company_id, payload.get("proposal_id")))
    except IndustryTemplateError as exc:
        return jsonify(status="error", code=exc.code, message=str(exc)), exc.status_code
    except PermissionError as exc:
        return jsonify(status="error", message=str(exc)), 403
    except Exception as exc:
        return server_error("review_industry_template", exc)

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
        return server_error("fetch_settings", e)


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
        return server_error("save_settings", e)


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
        return server_error("save_active_profile", e)

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
        return server_error("apply_profile", e)
