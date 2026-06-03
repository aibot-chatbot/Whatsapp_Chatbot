from functools import wraps
from flask import request, jsonify, g
import jwt

from app.utils.jwt_utils import get_jwt_secret


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

        return f(*args, **kwargs)

    return decorated
