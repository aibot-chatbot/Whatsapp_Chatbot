from flask import Blueprint, jsonify, request, g
from werkzeug.security import generate_password_hash, check_password_hash

from app.database.user_repository import get_user_by_id, get_user_by_email, create_user, update_user, get_users_by_company, count_active_admins_by_company
from app.decorators.auth_decorator import token_required
from app.utils.access_control import role_required
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


# ===== Team users blueprint (separate prefix) =====
team_bp = Blueprint("team", __name__, url_prefix="/api/users")

@team_bp.route("", methods=["POST"])
@token_required
@role_required("admin", "owner")
def create_company_member():
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                "status": "error",
                "message": "No data provided."
            }), 400

        full_name = (data.get("full_name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        role = (data.get("role") or "").strip().lower()
        password = data.get("password") or ""
        confirm_password = data.get("confirm_password") or ""

        # Validate required fields
        if not full_name:
            return jsonify({"status": "error", "message": "Full name is required."}), 400

        if not email:
            return jsonify({"status": "error", "message": "Email is required."}), 400

        if not role:
            return jsonify({"status": "error", "message": "Role is required."}), 400

        if role not in ("admin", "member"):
            return jsonify({"status": "error", "message": "Allowed roles: admin, member."}), 400

        if not password or not confirm_password:
            return jsonify({"status": "error", "message": "Password and confirm password are required."}), 400

        if password != confirm_password:
            return jsonify({"status": "error", "message": "Passwords do not match."}), 400

        # Password strength
        is_strong, msg = validate_password_strength(password)
        if not is_strong:
            return jsonify({"status": "error", "message": msg}), 400

        # Email uniqueness
        existing = get_user_by_email(email)
        if existing:
            return jsonify({"status": "error", "message": "Email already registered."}), 409

        # Create user under current company
        company_id = g.company_id
        password_hash = generate_password_hash(password)

        user = create_user(
            company_id=company_id,
            full_name=full_name,
            email=email,
            password_hash=password_hash,
            role=role,
            status="active",
            is_verified=True
        )

        return jsonify({
            "status": "success",
            "message": "Member account created successfully.",
            "data": {
                "id": user["id"],
                "company_id": user.get("company_id"),
                "full_name": user.get("full_name"),
                "email": user.get("email"),
                "role": user.get("role"),
                "status": user.get("status"),
                "is_verified": user.get("is_verified")
            }
        }), 201

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



@team_bp.route("", methods=["GET"])
@token_required
@role_required("admin", "owner")
def list_company_users():
    try:
        company_id = g.company_id
        users = get_users_by_company(company_id)

        return jsonify({
            "status": "success",
            "data": users
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


@team_bp.route("/<int:user_id>/role", methods=["PUT"])
@token_required
@role_required("admin", "owner")
def update_member_role(user_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data provided."}), 400

        new_role = (data.get("role") or "").strip().lower()
        if new_role not in ("admin", "member"):
            return jsonify({"status": "error", "message": "Role must be 'admin' or 'member'."}), 400

        company_id = g.company_id
        current_user_id = g.user_id

        # Cannot change own role
        if user_id == current_user_id:
            return jsonify({"status": "error", "message": "You cannot change your own role."}), 403

        # Load target user
        target = get_user_by_id(user_id)
        if not target:
            return jsonify({"status": "error", "message": "User not found."}), 404
        if target.get("company_id") != company_id:
            return jsonify({"status": "error", "message": "User does not belong to your company."}), 403

        # If demoting an admin/owner, ensure at least one other active admin remains
        if target.get("role") in ("admin", "owner") and new_role != target.get("role"):
            admin_count = count_active_admins_by_company(company_id)
            if admin_count <= 1:
                return jsonify({"status": "error", "message": "Cannot demote the last active admin in the company."}), 403

        updated = update_user(user_id, {"role": new_role})

        return jsonify({
            "status": "success",
            "message": "Role updated successfully.",
            "data": {
                "id": updated["id"],
                "full_name": updated.get("full_name"),
                "email": updated.get("email"),
                "role": updated.get("role"),
                "status": updated.get("status"),
                "is_verified": updated.get("is_verified")
            }
        }), 200

    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@team_bp.route("/<int:user_id>/status", methods=["PUT"])
@token_required
@role_required("admin", "owner")
def update_member_status(user_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data provided."}), 400

        new_status = (data.get("status") or "").strip().lower()
        if new_status not in ("active", "inactive"):
            return jsonify({"status": "error", "message": "Status must be 'active' or 'inactive'."}), 400

        company_id = g.company_id
        current_user_id = g.user_id

        # Cannot deactivate self
        if user_id == current_user_id:
            return jsonify({"status": "error", "message": "You cannot deactivate your own account."}), 403

        # Load target user
        target = get_user_by_id(user_id)
        if not target:
            return jsonify({"status": "error", "message": "User not found."}), 404
        if target.get("company_id") != company_id:
            return jsonify({"status": "error", "message": "User does not belong to your company."}), 403

        # If deactivating an admin/owner, ensure at least one other active admin remains
        if new_status == "inactive" and target.get("role") in ("admin", "owner"):
            admin_count = count_active_admins_by_company(company_id)
            if admin_count <= 1:
                return jsonify({"status": "error", "message": "Cannot deactivate the last active admin in the company."}), 403

        updated = update_user(user_id, {"status": new_status})

        return jsonify({
            "status": "success",
            "message": "Status updated successfully.",
            "data": {
                "id": updated["id"],
                "full_name": updated.get("full_name"),
                "email": updated.get("email"),
                "role": updated.get("role"),
                "status": updated.get("status"),
                "is_verified": updated.get("is_verified")
            }
        }), 200

    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
