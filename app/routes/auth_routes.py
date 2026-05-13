from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from app.database.user_repository import get_user_by_email, create_user
from app.database.company_repository import create_company
from app.services.email_service import send_otp_email

import jwt
import datetime
import os


SECRET_KEY = os.getenv("JWT_SECRET", "super-secret-default-key-please-change")

def validate_password_strength(password):
    """
    Validates that a password is strong:
    - At least 8 characters
    - Contains at least one uppercase letter
    - Contains at least one number
    - Contains at least one special character
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not any(char.isupper() for char in password):
        return False, "Password must contain at least one uppercase letter."
    if not any(char.isdigit() for char in password):
        return False, "Password must contain at least one number."
    if not any(char in "!@#$%^&*()-_=+[]{}|;:,.<>?" for char in password):
        return False, "Password must contain at least one special character."
    return True, ""

def generate_otp():
    import random
    return str(random.randint(100000, 999999))

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

    if not user.get("is_verified", False):
        return jsonify({
            "status": "unverified",
            "message": "Please verify your email address before logging in.",
            "email": email
        }), 403

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
        from app.database.db import supabase
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

        is_strong, msg = validate_password_strength(password)
        if not is_strong:
            return jsonify({"status": "error", "message": msg}), 400

        # Block if a verified account already exists
        existing_user = get_user_by_email(email)
        if existing_user and existing_user.get("is_verified"):
            return jsonify({"status": "error", "message": "Email already registered"}), 409

        password_hash = generate_password_hash(password)
        otp = generate_otp()
        otp_expiry = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)).isoformat()

        # Upsert into pending_registrations — does NOT touch users/companies/bots
        supabase.table("pending_registrations").upsert({
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "company_name": company_name,
            "password_hash": password_hash,
            "otp_code": otp,
            "otp_expiry": otp_expiry
        }, on_conflict="email").execute()

        email_sent = send_otp_email(email, otp, recipient_name=first_name)
        if email_sent:
            print(f"DEBUG: OTP sent to {email}")
        else:
            print(f"DEBUG: Email failed for {email}, OTP: {otp}")

        return jsonify({
            "status": "success",
            "message": "A verification code has been sent to your email. Please verify to complete registration.",
            "data": {"email": email}
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@auth_bp.route("/verify-otp", methods=["POST"])
def verify_otp():
    from app.database.db import supabase
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    otp = data.get("otp", "").strip()

    if not email or not otp:
        return jsonify({"status": "error", "message": "Email and OTP are required"}), 400

    # Check pending_registrations first
    pending_res = supabase.table("pending_registrations").select("*").eq("email", email).limit(1).execute()
    pending = pending_res.data[0] if pending_res.data else None

    if not pending:
        return jsonify({"status": "error", "message": "No pending registration found for this email"}), 404

    stored_otp = pending.get("otp_code")
    expiry_str = pending.get("otp_expiry")

    if not stored_otp or stored_otp != otp:
        return jsonify({"status": "error", "message": "Invalid verification code"}), 400

    if expiry_str:
        expiry = datetime.datetime.fromisoformat(expiry_str)
        if datetime.datetime.now(datetime.timezone.utc) > expiry:
            return jsonify({"status": "error", "message": "Verification code expired. Please request a new one."}), 400

    # OTP is valid — now create the real account
    try:
        company = create_company(
            company_name=pending["company_name"],
            business_type="",
            contact_email=email,
            contact_phone=""
        )

        full_name = f"{pending['first_name']} {pending['last_name']}".strip()

        user = create_user(
            company_id=company["id"],
            full_name=full_name,
            email=email,
            password_hash=pending["password_hash"],
            role="admin",
            status="active"
        )

        # Mark user as verified immediately
        supabase.table("users").update({"is_verified": True}).eq("id", user["id"]).execute()

        # Clean up pending registration
        supabase.table("pending_registrations").delete().eq("email", email).execute()

        return jsonify({"status": "success", "message": "Email verified! Your account is ready. Please login."}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"Account creation failed: {str(e)}"}), 500

@auth_bp.route("/resend-otp", methods=["POST"])
def resend_otp():
    from app.database.db import supabase
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()

    if not email:
        return jsonify({"status": "error", "message": "Email is required"}), 400

    pending_res = supabase.table("pending_registrations").select("*").eq("email", email).limit(1).execute()
    pending = pending_res.data[0] if pending_res.data else None

    if not pending:
        return jsonify({"status": "error", "message": "No pending registration found for this email"}), 404

    otp = generate_otp()
    otp_expiry = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)).isoformat()

    supabase.table("pending_registrations").update({
        "otp_code": otp,
        "otp_expiry": otp_expiry
    }).eq("email", email).execute()

    email_sent = send_otp_email(email, otp, recipient_name=pending.get("first_name", "User"))
    if email_sent:
        print(f"DEBUG: Resent OTP via email to {email}")
    else:
        print(f"DEBUG: Resend failed for {email}, OTP: {otp}")

    return jsonify({"status": "success", "message": "New verification code sent to your email"}), 200