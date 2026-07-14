from app.rate_limit import limiter
from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from app.database.user_repository import get_user_by_email, create_user
from app.database.company_repository import create_company
from app.database.password_reset_repository import (
    upsert_password_reset_otp,
    get_password_reset_otp,
    mark_password_reset_otp_verified,
    delete_password_reset_otp,
)
from app.services.email_service import send_otp_email
from app.services.billing_service import ensure_default_company_subscription
from app.utils.jwt_utils import get_jwt_secret
import logging
logger = logging.getLogger(__name__)

import jwt
import datetime
import os


def auth_config_error_response():
    return jsonify({
        "status": "error",
        "message": "Authentication is not configured properly."
    }), 500

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


def parse_otp_expiry(expiry_value):
    if isinstance(expiry_value, datetime.datetime):
        expiry = expiry_value

    elif isinstance(expiry_value, str):
        expiry = datetime.datetime.fromisoformat(expiry_value.replace("Z", "+00:00"))

    else:
        return None

    if expiry.tzinfo is None:
        return expiry.replace(tzinfo=datetime.timezone.utc)

    return expiry


auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.route("/google", methods=["POST"])
def google_auth():
    """
    Verify a Google ID token and log in or create the user.
    If it's a new user and no company_name is provided, return a prompt signal.
    """
    import requests as http_requests

    data = request.get_json() or {}
    credential = (data.get("credential") or "").strip()
    company_name = (data.get("company_name") or "").strip()

    if not credential:
        return jsonify({"status": "error", "message": "Google credential token is required"}), 400

    # Verify the token with Google's tokeninfo endpoint
    google_client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    verify_url = f"https://oauth2.googleapis.com/tokeninfo?id_token={credential}"
    try:
        google_resp = http_requests.get(verify_url, timeout=10)
        token_info = google_resp.json()
    except Exception as e:
        return jsonify({"status": "error", "message": "Failed to contact Google servers"}), 502

    if google_resp.status_code != 200 or token_info.get("error_description"):
        return jsonify({"status": "error", "message": "Invalid Google token. Please try again."}), 401

    # Validate audience (aud) matches our client ID â€” skip if not configured yet
    if google_client_id and token_info.get("aud") != google_client_id:
        return jsonify({"status": "error", "message": "Token audience mismatch"}), 401

    email = (token_info.get("email") or "").strip().lower()
    full_name = (token_info.get("name") or email.split("@")[0]).strip()
    google_sub = token_info.get("sub", "")

    if not email:
        return jsonify({"status": "error", "message": "Google did not return an email address"}), 400

    from app.database.db import supabase

    # Check if user already exists
    existing_user = get_user_by_email(email)

    if existing_user:
        # Check if user is deactivated
        if existing_user.get("status") != "active":
            return jsonify({
                "status": "error",
                "message": "Your account has been deactivated. Please contact your administrator."
            }), 403

        # Existing user â€” log them in
        try:
            token = jwt.encode({
                "user_id": existing_user["id"],
                "company_id": existing_user.get("company_id"),
                "email": existing_user["email"],
                "role": existing_user["role"],
                "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24)
            }, get_jwt_secret(), algorithm="HS256")
        except RuntimeError:
            return auth_config_error_response()

        return jsonify({
            "status": "success",
            "message": "Login successful",
            "token": token,
            "user": {
                "id": existing_user["id"],
                "company_id": existing_user.get("company_id"),
                "full_name": existing_user.get("full_name"),
                "email": existing_user["email"],
                "role": existing_user["role"]
            }
        })

    # New user â€” need company name
    if not company_name:
        return jsonify({
            "status": "needs_company",
            "message": "Please enter your company name to complete registration."
        }), 200

    # Create company and user
    try:
        company = create_company(
            company_name=company_name,
            contact_email=email
        )

        user = create_user(
            company_id=company["id"],
            full_name=full_name,
            email=email,
            password_hash=None,  # Google users don't need a password
            role="admin",
            status="active"
        )

        # Mark as verified immediately (Google verified their email)
        supabase.table("users").update({
            "is_verified": True
        }).eq("id", user["id"]).execute()

        # Assign the Free subscription plan to the new company.
        # This runs after the company and verified user exist. If subscription
        # assignment fails, the account is still created successfully -- billing
        # failure should not block the user from logging in.
        try:
            ensure_default_company_subscription(company["id"])
        except Exception:
            logging.exception(
                "Failed to assign Free subscription for company %s after Google registration",
                company["id"],
            )
        try:
            token = jwt.encode({
                "user_id": user["id"],
                "company_id": company["id"],
                "email": email,
                "role": "admin",
                "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24)
            }, get_jwt_secret(), algorithm="HS256")
        except RuntimeError:
            return auth_config_error_response()

        return jsonify({
            "status": "success",
            "message": "Account created successfully!",
            "token": token,
            "user": {
                "id": user["id"],
                "company_id": company["id"],
                "full_name": full_name,
                "email": email,
                "role": "admin"
            }
        })

    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to create account: {str(e)}"}), 500


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
@limiter.limit(lambda: __import__("flask").current_app.config.get("RATELIMIT_LOGIN", "10/minute"))
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


    # Check if user is deactivated
    if user.get("status") != "active":
        return jsonify({
            "status": "error",
            "message": "Your account has been deactivated. Please contact your administrator."
        }), 403

    if not user.get("is_verified", False):
        return jsonify({
            "status": "unverified",
            "message": "Please verify your email address before logging in.",
            "email": email
        }), 403

    try:
        token = jwt.encode({
            "user_id": user["id"],
            "company_id": user.get("company_id"),
            "email": user["email"],
            "role": user["role"],
            "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        }, get_jwt_secret(), algorithm="HS256")
    except RuntimeError:
        return auth_config_error_response()

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

        # Upsert into pending_registrations â€” does NOT touch users/companies/bots
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
            logger.info("OTP sent to " + email)
        else:
            logger.warning("Email failed for " + email)

        return jsonify({
            "status": "success",
            "message": "A verification code has been sent to your email. Please verify to complete registration.",
            "data": {"email": email}
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@auth_bp.route("/verify-otp", methods=["POST"])
@limiter.limit(lambda: __import__("flask").current_app.config.get("RATELIMIT_OTP", "5/hour"))
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

    # OTP is valid â€” now create the real account
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

        # Assign the Free subscription plan to the new company.
        # This runs after the company and verified user exist but before the
        # pending registration is cleaned up. If subscription assignment fails,
        # the account is still created successfully -- billing failure should not
        # block the user from logging in.
        try:
            ensure_default_company_subscription(company["id"])
        except Exception:
            logging.exception(
                "Failed to assign Free subscription for company %s after email verification",
                company["id"],
            )

        # Clean up pending registration
        supabase.table("pending_registrations").delete().eq("email", email).execute()
        return jsonify({"status": "success", "message": "Email verified! Your account is ready. Please login."}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"Account creation failed: {str(e)}"}), 500

@auth_bp.route("/resend-otp", methods=["POST"])
@limiter.limit(lambda: __import__("flask").current_app.config.get("RATELIMIT_OTP", "5/hour"))
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
        logger.info("Resent OTP via email to " + email)
    else:
        logger.warning("Resend failed for " + email)

    return jsonify({"status": "success", "message": "New verification code sent to your email"}), 200


@auth_bp.route("/forgot-password", methods=["POST"])
@limiter.limit(lambda: __import__("flask").current_app.config.get("RATELIMIT_OTP", "5/hour"))
def forgot_password():
    from app.services.email_service import send_reset_email
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()

    if not email:
        return jsonify({"status": "error", "message": "Email is required"}), 400

    # Verify if user exists in the database
    user = get_user_by_email(email)
    if not user:
        return jsonify({"status": "error", "message": "No account associated with this email address."}), 404

    otp = generate_otp()
    otp_expiry = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)

    upsert_password_reset_otp(
        email=email,
        otp_code=otp,
        otp_expiry=otp_expiry.isoformat(),
    )

    # Extract name
    full_name = user.get("full_name", "User")
    first_name = full_name.split(" ")[0] if full_name else "User"

    email_sent = send_reset_email(email, otp, recipient_name=first_name)
    if not email_sent:
        logger.info("Reset OTP for " + email)

    return jsonify({
        "status": "success",
        "message": "A secure password reset verification code has been sent to your email address."
    }), 200


@auth_bp.route("/verify-reset-otp", methods=["POST"])
def verify_reset_otp():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    otp = (data.get("otp") or "").strip()

    if not email or not otp:
        return jsonify({"status": "error", "message": "Email and OTP code are required"}), 400

    otp_record = get_password_reset_otp(email)
    if not otp_record:
        return jsonify({"status": "error", "message": "No password reset request found or session expired."}), 400

    if otp_record.get("otp_code") != otp:
        return jsonify({"status": "error", "message": "Invalid password reset verification code."}), 400

    expiry = parse_otp_expiry(otp_record.get("otp_expiry"))
    if not expiry or datetime.datetime.now(datetime.timezone.utc) > expiry:
        delete_password_reset_otp(email)
        return jsonify({"status": "error", "message": "Verification code has expired. Please request a new one."}), 400

    # OTP is valid! Mark as verified
    mark_password_reset_otp_verified(email)
    return jsonify({
        "status": "success",
        "message": "Verification code successfully verified."
    }), 200


@auth_bp.route("/reset-password", methods=["POST"])
@limiter.limit(lambda: __import__("flask").current_app.config.get("RATELIMIT_OTP", "5/hour"))
def reset_password():
    from app.database.db import supabase
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    otp = (data.get("otp") or "").strip()
    new_password = data.get("password") or ""
    confirm_password = data.get("confirm_password") or ""

    if not email or not otp or not new_password:
        return jsonify({"status": "error", "message": "All fields are required."}), 400

    if new_password != confirm_password:
        return jsonify({"status": "error", "message": "Passwords do not match."}), 400

    # Validate password strength
    is_strong, msg = validate_password_strength(new_password)
    if not is_strong:
        return jsonify({"status": "error", "message": msg}), 400

    otp_record = get_password_reset_otp(email)
    if not otp_record or not otp_record.get("verified") or otp_record.get("otp_code") != otp:
        return jsonify({"status": "error", "message": "Invalid or unverified password reset session."}), 400

    expiry = parse_otp_expiry(otp_record.get("otp_expiry"))
    if not expiry or datetime.datetime.now(datetime.timezone.utc) > expiry:
        delete_password_reset_otp(email)
        return jsonify({"status": "error", "message": "Session expired. Please request a new reset code."}), 400

    try:
        # Update user's password in Supabase
        password_hash = generate_password_hash(new_password)
        supabase.table("users").update({
            "password_hash": password_hash,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }).eq("email", email).execute()

        # Clean up OTP record
        delete_password_reset_otp(email)

        return jsonify({
            "status": "success",
            "message": "Your password has been reset successfully! You can now log in with your new password."
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to reset password: {str(e)}"}), 500
