from flask import Blueprint, jsonify, request, g
from werkzeug.security import generate_password_hash, check_password_hash
from app.database.user_repository import get_user_by_id, get_user_by_email, create_user, update_user, get_users_by_company, count_active_admins_by_company
from app.decorators.auth_decorator import token_required
from app.utils.access_control import role_required
from app.routes.auth_routes import validate_password_strength

user_bp = Blueprint("user", __name__, url_prefix="/api/user")

@user_bp.route('"', methods=['GET'])
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
