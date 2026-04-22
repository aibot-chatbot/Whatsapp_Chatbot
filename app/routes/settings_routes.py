from flask import Blueprint, jsonify, request

from app.services.settings_service import get_settings, update_settings, set_active_profile


settings_blueprint = Blueprint("settings", __name__)


@settings_blueprint.route("/api/settings", methods=["GET"])
def fetch_settings():
    try:
        settings = get_settings()
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