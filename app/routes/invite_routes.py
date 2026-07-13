from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, g
import secrets
from werkzeug.security import generate_password_hash

from app.decorators.auth_decorator import token_required
from app.utils.access_control import role_required
from app.database.invite_repository import (
    get_pending_invite_by_email,
    get_invite_by_token,
    update_invite,
    create_invite,
    get_invites_by_company,
    get_invite_by_id,
    delete_invite,
)
from app.database.user_repository import get_user_by_email, create_user
from app.services.billing_guard import can_add_team_member, BillingLimitError
from app.routes.auth_routes import validate_password_strength

invite_bp = Blueprint("invite", __name__, url_prefix="/api/invites")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def _build_invite_url(token):
    """Build the full invite acceptance URL from the configured frontend URL."""
    from flask import current_app
    base = current_app.config.get("FRONTEND_URL", "http://localhost:3000")
    return f"{base}/accept-invite?token={token}"



# ── Admin: Create Invite ──────────────────────────────────────────────


@invite_bp.route("", methods=["POST"])
@token_required
@role_required("admin", "owner")
def create_invite_endpoint():
    """Create a new invite for a user to join the company."""
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                "status": "error",
                "message": "No data provided."
            }), 400

        email = (data.get("email") or "").strip().lower()
        role = (data.get("role") or "").strip().lower()

        if not email:
            return jsonify({
                "status": "error",
                "message": "Email is required."
            }), 400

        if role not in ("admin", "member"):
            return jsonify({
                "status": "error",
                "message": "Role must be 'admin' or 'member'."
            }), 400

        company_id = g.company_id

        # Check subscription limit before creating invitation
        can_add_team_member(company_id)

        existing = get_pending_invite_by_email(email, company_id)
        if existing:
            return jsonify({
                "status": "error",
                "message": "A pending invite already exists for this email."
            }), 409

        token = secrets.token_urlsafe(32)

        invite = create_invite(
            email=email,
            company_id=company_id,
            role=role,
            token=token,
            created_by=g.user_id
        )

        invite_link = _build_invite_url(token)

        # Send invite email (non-blocking — failure does not break response)
        try:
            from app.services.email_service import send_invite_email
            send_invite_email(email, invite_link, recipient_name=email.split("@")[0])
        except Exception as email_err:
            import logging
            logging.error(f"Failed to send invite email to {email}: {email_err}")

        return jsonify({
            "status": "success",
            "message": "Invite created successfully",
            "invite_link": invite_link
        }), 201

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e)
        }), 403
    except Exception as e:
                return jsonify({
            "status": "success",
            "data": []
        }), 200



# ── Admin: List Company Invites ────────────────────────────────────────


@invite_bp.route("", methods=["GET"])
@token_required
@role_required("admin", "owner")
def list_company_invites():
    """List invites for the current company, optionally filtered by status."""
    try:
        status = (request.args.get("status") or "").strip().lower() or None
        company_id = g.company_id

        import logging
        invites = get_invites_by_company(company_id, status=status)
        logging.warning(f"list_company_invites: company_id={company_id!r} (type={type(company_id).__name__}), status={status!r}, result_count={len(invites)}")

        safe_invites = []
        for inv in invites:
            safe_invites.append({
                "id": inv.get("id"),
                "email": inv.get("email"),
                "role": inv.get("role"),
                "status": inv.get("status"),
                "created_at": inv.get("created_at"),
                "expires_at": inv.get("expires_at"),
            })

        return jsonify({
            "status": "success",
            "data": safe_invites
        }), 200

    except Exception as e:
        import logging
        logging.error(f"list_company_invites error: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# ── Admin: Resend Invite ───────────────────────────────────────────────


@invite_bp.route("/resend", methods=["POST"])
@token_required
@role_required("admin", "owner")
def resend_invite():
    """Resend an existing pending invite."""
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                "status": "error",
                "message": "No data provided."
            }), 400

        email = (data.get("email") or "").strip().lower()

        if not email:
            return jsonify({
                "status": "error",
                "message": "Email is required."
            }), 400

        company_id = g.company_id

        invite = get_pending_invite_by_email(email, company_id)
        if not invite:
            return jsonify({
                "status": "error",
                "message": "No pending invite found for this email."
            }), 404

        token = invite.get("token")
        invite_link = _build_invite_url(token)

        # Send invite email (non-blocking)
        try:
            from app.services.email_service import send_invite_email
            send_invite_email(email, invite_link, recipient_name=email.split("@")[0])
        except Exception as email_err:
            import logging
            logging.error(f"Failed to resend invite email to {email}: {email_err}")

        return jsonify({
            "status": "success",
            "message": "Invitation resent successfully."
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


# ── Admin: Cancel / Delete Invite ──────────────────────────────────────


@invite_bp.route("/<int:invite_id>", methods=["DELETE"])
@token_required
@role_required("admin", "owner")
def cancel_invite(invite_id):
    """Cancel (delete) a pending invite."""
    try:
        company_id = g.company_id

        invite = get_invite_by_id(invite_id)
        if not invite:
            return jsonify({
                "status": "error",
                "message": "Invite not found."
            }), 404

        if invite.get("company_id") != company_id:
            return jsonify({
                "status": "error",
                "message": "Invite not found."
            }), 404

        if invite.get("status") != "pending":
            return jsonify({
                "status": "error",
                "message": "Only pending invites can be cancelled."
            }), 400

        delete_invite(invite_id)

        return jsonify({
            "status": "success",
            "message": "Invitation cancelled successfully."
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

# ── Public: Validate Invite Token ─────────────────────────────────────


@invite_bp.route("/validate", methods=["GET"])
def validate_invite():
    """Check an invite token and return its details if valid."""
    try:
        token = (request.args.get("token") or "").strip()

        if not token:
            return jsonify({
                "status": "error",
                "message": "Token is required."
            }), 400

        invite = get_invite_by_token(token)

        if not invite:
            return jsonify({
                "status": "error",
                "message": "Invalid invite token."
            }), 404

        if invite.get("status") != "pending":
            return jsonify({
                "status": "error",
                "message": "This invite has already been used."
            }), 410

        expires_at = invite.get("expires_at")
        if expires_at:
            try:
                expires_dt = datetime.fromisoformat(expires_at)
                if expires_dt < datetime.now(timezone.utc):
                    return jsonify({
                        "status": "error",
                        "message": "This invite has expired."
                    }), 410
            except (ValueError, TypeError):
                pass

        return jsonify({
            "status": "success",
            "valid": True,
            "email": invite.get("email"),
            "company_id": invite.get("company_id"),
            "role": invite.get("role")
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# ── Public: Accept Invite ──────────────────────────────────────────────


@invite_bp.route("/accept", methods=["POST"])
def accept_invite():
    """Accept an invite, creating the user account."""
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                "status": "error",
                "message": "No data provided."
            }), 400

        token = (data.get("token") or "").strip()
        full_name = (data.get("full_name") or "").strip()
        password = data.get("password") or ""

        if not token:
            return jsonify({
                "status": "error",
                "message": "Token is required."
            }), 400

        if not full_name:
            return jsonify({
                "status": "error",
                "message": "Full name is required."
            }), 400

        if not password:
            return jsonify({
                "status": "error",
                "message": "Password is required."
            }), 400

        # ── Validate invite ──

        invite = get_invite_by_token(token)

        if not invite:
            return jsonify({
                "status": "error",
                "message": "Invalid invite token."
            }), 404

        if invite.get("status") != "pending":
            return jsonify({
                "status": "error",
                "message": "This invite has already been used."
            }), 410

        expires_at = invite.get("expires_at")
        if expires_at:
            try:
                expires_dt = datetime.fromisoformat(expires_at)
                if expires_dt < datetime.now(timezone.utc):
                    return jsonify({
                        "status": "error",
                        "message": "This invite has expired."
                    }), 410
            except (ValueError, TypeError):
                pass

        # ── Validate password strength ──

        is_strong, msg = validate_password_strength(password)
        if not is_strong:
            return jsonify({
                "status": "error",
                "message": msg
            }), 400

        # ── Check email not already registered ──

        email = invite.get("email")
        existing_user = get_user_by_email(email)
        if existing_user:
            return jsonify({
                "status": "error",
                "message": "This email is already registered."
            }), 409

        # ── Check subscription limit before creating user ──
        company_id_from_invite = invite.get("company_id")
        can_add_team_member(company_id_from_invite)

        # ── Create user ──

        password_hash = generate_password_hash(password)
        company_id = invite.get("company_id")
        role = invite.get("role")

        user = create_user(
            company_id=company_id,
            full_name=full_name,
            email=email,
            password_hash=password_hash,
            role=role,
            status="active",
            is_verified=True
        )

        # ── Mark invite as accepted ──

        update_invite(token, {
            "status": "accepted",
            "accepted_at": _now_iso()
        })

        return jsonify({
            "status": "success",
            "message": "Account created successfully. You can now log in."
        }), 201

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e)
        }), 403
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500




