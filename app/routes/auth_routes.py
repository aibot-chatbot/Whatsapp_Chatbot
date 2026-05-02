from flask import Blueprint, request, jsonify
from app.database.user_repository import get_user_by_email
import jwt
import datetime
import os

SECRET_KEY = os.getenv("JWT_SECRET", "super-secret-default-key-please-change")

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()

    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    user = get_user_by_email(email)

    if not user:
        return jsonify({"error": "User not found"}), 404

    # TEMP (no hashing yet)
    if user["password_hash"] != password:
        return jsonify({"error": "Invalid password"}), 401

    # Generate JWT token
    token = jwt.encode({
        'user_id': user['id'],
        'email': user['email'],
        'role': user['role'],
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    }, SECRET_KEY, algorithm="HS256")

    return jsonify({
        "status": "success",
        "message": "Login successful",
        "token": token,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "role": user["role"]
        }
    })