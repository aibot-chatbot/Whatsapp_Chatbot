from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from app.database.user_repository import get_user_by_email, create_user
from app.database.company_repository import create_company
from app.database.bot_repository import create_bot

import jwt
import datetime
import os


SECRET_KEY = os.getenv("JWT_SECRET", "super-secret-default-key-please-change")

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def is_password_valid(stored_password, input_password):
    if not stored_password or not input_password:
        return False

    # Support old users that were saved as plain text before hashing
    if stored_password == input_password:
        return True

    try:
        return check_password_hash(stored_password, input_password)
    except Exception:
        return False


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}

    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    user = get_user_by_email(email)

    if not user:
        return jsonify({"error": "User not found"}), 404

    if not is_password_valid(user.get("password_hash"), password):
        return jsonify({"error": "Invalid password"}), 401

    token = jwt.encode({
        "user_id": user["id"],
        "company_id": user.get("company_id"),
        "email": user["email"],
        "role": user["role"],
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    }, SECRET_KEY, algorithm="HS256")

    return jsonify({
        "status": "success",
        "message": "Login successful",
        "token": token,
        "user": {
            "id": user["id"],
            "company_id": user.get("company_id"),
            "full_name": user.get("full_name"),
            "email": user["email"],
            "role": user["role"]
        }
    })


@auth_bp.route("/register", methods=["POST"])
def register():
    try:
        data = request.get_json() or {}

        first_name = (data.get("first_name") or "").strip()
        last_name = (data.get("last_name") or "").strip()
        company_name = (data.get("company_name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        confirm_password = data.get("confirm_password") or ""

        if not first_name or not last_name:
            return jsonify({"status": "error", "message": "First name and last name are required"}), 400

        if not company_name:
            return jsonify({"status": "error", "message": "Company name is required"}), 400

        if not email or not password:
            return jsonify({"status": "error", "message": "Email and password are required"}), 400

        if password != confirm_password:
            return jsonify({"status": "error", "message": "Passwords do not match"}), 400

        existing_user = get_user_by_email(email)
        if existing_user:
            return jsonify({"status": "error", "message": "Email already registered"}), 409

        company = create_company(
            company_name=company_name,
            business_type=data.get("business_type", ""),
            contact_email=email,
            contact_phone=data.get("contact_phone", "")
        )

        full_name = f"{first_name} {last_name}".strip()
        password_hash = generate_password_hash(password)

        user = create_user(
            company_id=company["id"],
            full_name=full_name,
            email=email,
            password_hash=password_hash,
            role="admin",
            status="active"
        )

        default_bot = create_bot({
            "bot_name": f"{company_name} Assistant",
            "bot_description": f"Default chatbot for {company_name}",
            "language": "English",
            "tone": "Friendly",
            "welcome_message": f"Hi there! Welcome to {company_name}. How can I help you today?",
            "fallback_message": "Sorry, I do not have that information yet.",
            "is_active": True,
        }, company_id=company["id"])

        return jsonify({
            "status": "success",
            "message": "Account created successfully",
            "data": {
                "company": company,
                "user": {
                    "id": user["id"],
                    "company_id": user["company_id"],
                    "full_name": user["full_name"],
                    "email": user["email"],
                    "role": user["role"]
                },
                "chatbot": default_bot
            }
        }), 201

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500