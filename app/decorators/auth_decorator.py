from functools import wraps
from flask import request, jsonify, g
import jwt
import logging

from app.utils.jwt_utils import get_jwt_secret


logger = logging.getLogger(__name__)


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        if "Authorization" in request.headers:
            parts = request.headers["Authorization"].split()
            if len(parts) == 2 and parts[0] == "Bearer":
                token = parts[1]

        if not token:
            return jsonify({"status": "error", "message": "Token is missing!"}), 401

        try:
            data = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])

            # Store decoded token data for routes to use
            g.current_user = data
            g.company_id = data.get("company_id")
            g.user_id = data.get("user_id")
            g.role = data.get("role")

        except RuntimeError:
            return jsonify({
                "status": "error",
                "message": "Authentication is not configured properly."
            }), 500
        except jwt.ExpiredSignatureError:
            return jsonify({"status": "error", "message": "Token has expired! Please log in again."}), 401
        except jwt.InvalidTokenError:
            return jsonify({"status": "error", "message": "Invalid token!"}), 401


        # Check if user account is still active. Keep the refreshed row on the
        # request context so stricter authorization layers can use authoritative
        # database state without trusting role/company claims from the JWT.
        try:
            from app.database.user_repository import get_user_by_id
            current_user = get_user_by_id(g.user_id)
        except Exception:
            logger.error("Authentication backend unavailable while validating user")
            return jsonify({
                "status": "error",
                "code": "authentication_backend_unavailable",
                "message": "Authentication service is temporarily unavailable."
            }), 503

        if not current_user or current_user.get("status") != "active":
            return jsonify({
                "status": "error",
                "code": "account_inactive",
                "message": "Your account has been deactivated. Please contact your administrator."
            }), 403

        g.authenticated_user = current_user

        return f(*args, **kwargs)

    return decorated
