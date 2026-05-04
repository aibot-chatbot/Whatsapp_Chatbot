from flask import Blueprint, jsonify, request

from app.services.settings_service import (
    get_settings,
    get_deployed_settings_summary,
    update_settings,
    set_active_profile,
    apply_profile_to_settings,
)
from app.decorators.auth_decorator import token_required

settings_blueprint = Blueprint("settings", __name__)

@settings_blueprint.route("/api/settings", methods=["GET"])
@token_required
def fetch_settings():
    try:
        settings = get_deployed_settings_summary()
        return jsonify({
            "status": "success",
            "data": settings
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@settings_blueprint.route("/api/settings", methods=["PUT"])
@token_required
def save_settings():
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                "status": "error",
                "message": "No data provided"
            }), 400

        updated_settings = update_settings(data)

        return jsonify({
            "status": "success",
            "data": updated_settings
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@settings_blueprint.route("/api/settings/active-profile", methods=["PUT"])
@token_required
def save_active_profile():
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                "status": "error",
                "message": "No data provided"
            }), 400

        active_profile = data.get("active_profile", "")
        updated_settings = set_active_profile(active_profile)

        return jsonify({
            "status": "success",
            "data": updated_settings
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@settings_blueprint.route("/api/settings/apply-profile", methods=["PUT"])
@token_required
def apply_profile():
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                "status": "error",
                "message": "No data provided"
            }), 400

        profile_name = data.get("profile_name", "")
        updated_settings = apply_profile_to_settings(profile_name)

        return jsonify({
            "status": "success",
            "data": updated_settings,
            "message": f'Profile "{profile_name}" has been applied to WhatsApp bot settings.'
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