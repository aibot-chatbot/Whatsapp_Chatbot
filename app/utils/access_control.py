from functools import wraps
from flask import g, jsonify


def get_current_company_id():
    company_id = getattr(g, "company_id", None)

    if not company_id:
        raise ValueError("Company ID not found in token. Please login again.")

    return company_id


def role_required(*allowed_roles):
    """Decorator that checks the current user's role against allowed roles.

    Usage:
        @role_required("admin", "owner")
        def some_route():
            ...

    Returns 403 JSON if the user's role is not in the allowed list.
    Comparison is case-insensitive.
    """
    allowed = set(r.lower() for r in allowed_roles)

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user_role = getattr(g, "role", None)
            if not user_role or user_role.lower() not in allowed:
                return jsonify({
                    "status": "error",
                    "message": "You do not have permission to perform this action."
                }), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


def verify_chatbot_access(chatbot_id):
    from app.database.db import supabase

    company_id = get_current_company_id()

    response = (
        supabase
        .table("chatbots")
        .select("id, company_id")
        .eq("id", chatbot_id)
        .eq("company_id", company_id)
        .is_("deleted_at", "null")
        .neq("status", "archived")
        .limit(1)
        .execute()
    )

    rows = response.data or []

    if not rows:
        raise PermissionError("You do not have access to this chatbot.")

    return rows[0]
