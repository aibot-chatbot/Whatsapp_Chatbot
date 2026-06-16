from flask import Blueprint, jsonify, request, g
from werkzeug.security import generate_password_hash, check_password_hash

from app.database.user_repository import get_user_by_id, update_user
from app.decorators.auth_decorator import token_required
from app.routes.auth_routes import validate_password_strength

user_bp = Blueprint("user", __name__, url_prefix="/api/user")


@user_bp.route("", methods=["GET"])
@token_required
def fetch_current_user():
    try:
        user_id = g.user_id
        user = get_user_by_id(user_id)

        if not user:
            return jsonify({
                "status": "error",
                "message": "User not found"
            }), 404

        return jsonify({
            "status": "success",
            "data": {
                "id": user["id"],
                "full_name": user.get("full_name"),
                "email": user.get("email"),
                "role": user.get("role"),
                "company_id": user.get("company_id")
            }
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@user_bp.route("", methods=["PUT"])
@token_required
def update_current_user():
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                "status": "error",
                "message": "No data provided"
            }), 400

        user_id = g.user_id
        payload = {}

        if "full_name" in data:
            full_name = (data["full_name"] or "").strip()
            if not full_name:
                return jsonify({
                    "status": "error",
                    "message": "Full name is required"
                }), 400
            payload["full_name"] = full_name

        if "email" in data:
            email = (data["email"] or "").strip().lower()
            if not email:
                return jsonify({
                    "status": "error",
                    "message": "Email is required"
                }), 400
            payload["email"] = email

        if not payload:
            return jsonify({
                "status": "error",
                "message": "No fields to update"
            }), 400

        updated_user = update_user(user_id, payload)

        return jsonify({
            "status": "success",
            "message": "Profile updated successfully",
            "data": {
                "id": updated_user["id"],
                "full_name": updated_user.get("full_name"),
                "email": updated_user.get("email"),
                "role": updated_user.get("role")
            }
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


@user_bp.route("/password", methods=["PUT"])
@token_required
def change_password():
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                "status": "error",
                "message": "No data provided"
            }), 400

        current_password = data.get("current_password", "")
        new_password = data.get("new_password", "")
        confirm_password = data.get("confirm_password", "")

        if not current_password or not new_password or not confirm_password:
            return jsonify({
                "status": "error",
                "message": "All password fields are required"
            }), 400

        if new_password != confirm_password:
            return jsonify({
                "status": "error",
                "message": "New passwords do not match"
            }), 400

        is_strong, msg = validate_password_strength(new_password)
        if not is_strong:
            return jsonify({
                "status": "error",
                "message": msg
            }), 400

        user_id = g.user_id
        user = get_user_by_id(user_id)

        if not user:
            return jsonify({
                "status": "error",
                "message": "User not found"
            }), 404

        if not check_password_hash(user.get("password_hash", ""), current_password):
            return jsonify({
                "status": "error",
                "message": "Current password is incorrect"
            }), 403

        new_hash = generate_password_hash(new_password)
        update_user(user_id, {"password_hash": new_hash})

        return jsonify({
            "status": "success",
            "message": "Password changed successfully"
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500