from flask import Blueprint, jsonify, request

from app.services.profile_service import get_profiles, save_profile, delete_profile
from app.decorators.auth_decorator import token_required

profile_blueprint = Blueprint("profile", __name__)

@profile_blueprint.route("/api/profiles", methods=["GET"])
@token_required
def fetch_profiles():
    try:
        profiles = get_profiles()
        return jsonify({
            "status": "success",
            "data": profiles
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@profile_blueprint.route("/api/profiles", methods=["POST"])
@token_required
def create_profile():
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                "status": "error",
                "message": "No data provided"
            }), 400

        saved_profile = save_profile(data)

        return jsonify({
            "status": "success",
            "data": saved_profile
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

@profile_blueprint.route("/api/profiles/<profile_name>", methods=["DELETE"])
@token_required
def remove_profile(profile_name):
    try:
        deleted_profile = delete_profile(profile_name)

        return jsonify({
            "status": "success",
            "data": deleted_profile
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