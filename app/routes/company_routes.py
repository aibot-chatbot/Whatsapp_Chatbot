from flask import Blueprint, g, jsonify

from app.database.user_repository import get_users_by_company
from app.decorators.auth_decorator import token_required

company_blueprint = Blueprint("company", __name__)


@company_blueprint.route("/api/company/members", methods=["GET"])
@token_required
def get_company_members():
    """
    Minimal member list for the caller's company, for an assignee picker.
    Backed by the existing get_users_by_company (tenant-scoped by
    g.company_id, refreshed from the database by token_required -- never
    trusts a client-supplied company id).

    Deliberately conservative: only id, name and email are exposed. No
    password hash, no role, no status, no verification state, no other
    column get_users_by_company happens to return.
    """
    try:
        company_id = g.company_id
        users = get_users_by_company(company_id)

        members = [
            {
                "id": user.get("id"),
                "name": user.get("full_name"),
                "email": user.get("email"),
            }
            for user in users
            if user.get("status") == "active"
        ]

        return jsonify({
            "status": "success",
            "data": members
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
