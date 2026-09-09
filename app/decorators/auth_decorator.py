from functools import wraps
from flask import request, jsonify, g
import jwt
import logging

from app.utils.jwt_utils import get_jwt_secret
from app.utils.auth_token import (
    AuthTokenValidationError,
    validate_password_fingerprint,
)


logger = logging.getLogger(__name__)


def _is_positive_integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


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

            # Keep claims for identity diagnostics only. Tenant and role
            # authorization are refreshed from the database below.
            g.jwt_claims = data
            g.user_id = data.get("user_id")

            if not _is_positive_integer(g.user_id):
                return jsonify({"status": "error", "message": "Invalid token!"}), 401

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
        # request context so authorization layers can use authoritative
        # database tenant state without trusting the JWT company claim.
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

        refreshed_user_id = current_user.get("id")
        refreshed_company_id = current_user.get("company_id")
        if (
            not _is_positive_integer(refreshed_user_id)
            or refreshed_user_id != g.user_id
            or not _is_positive_integer(refreshed_company_id)
        ):
            logger.error("Authentication backend returned invalid user authorization context")
            return jsonify({
                "status": "error",
                "code": "authentication_backend_unavailable",
                "message": "Authentication service is temporarily unavailable."
            }), 503

        database_role = current_user.get("role")
        if not isinstance(database_role, str):
            normalized_role = ""
        else:
            normalized_role = database_role.strip().lower()
        if normalized_role not in {"owner", "admin", "member"}:
            logger.error("Authentication backend returned invalid user authorization role")
            return jsonify({
                "status": "error",
                "code": "authorization_context_invalid",
                "message": "Unable to validate account authorization."
            }), 503

        try:
            validate_password_fingerprint(data, current_user)
        except AuthTokenValidationError:
            return jsonify({
                "status": "error",
                "message": "Session is no longer valid. Please log in again."
            }), 401
        except RuntimeError:
            return jsonify({
                "status": "error",
                "message": "Authentication is not configured properly."
            }), 500

        g.authenticated_user = current_user
        g.current_user = current_user
        g.user_id = refreshed_user_id
        g.company_id = refreshed_company_id
        g.role = normalized_role

        from app.services.company_status_service import (
            company_operational_required,
            requires_company_operational_state,
        )

        if requires_company_operational_state(request.method, request.blueprint, request.endpoint):
            return company_operational_required(f)(*args, **kwargs)
        return f(*args, **kwargs)

    return decorated
