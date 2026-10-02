from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, g
import secrets
from werkzeug.security import generate_password_hash

from app.rate_limit import limiter
from app.decorators.auth_decorator import token_required
from app.utils.access_control import role_required
from app.database.invite_repository import (
    build_invite_expiry,
    get_pending_invite_by_email,
    create_invite,
    get_invites_by_company,
    get_invite_by_id,
    update_invite_for_company,
    delete_invite,
)
from app.database.user_repository import get_user_by_email
from app.services.billing_guard import can_add_team_member, BillingLimitError
from app.services.invitation_service import (
    InvitationValidationError,
    accept_pending_invitation,
    get_valid_pending_invitation,
)
from app.services.turnstile_service import require_turnstile
from app.routes.auth_routes import validate_password_strength

invite_bp = Blueprint("invite", __name__, url_prefix="/api/invites")


def _build_invite_url(token):
    """Build the full invite acceptance URL from the configured frontend URL."""
    from flask import current_app
    base = current_app.config.get("FRONTEND_URL", "http://localhost:3000").rstrip("/")
    return f"{base}/accept-invite.html?token={token}"



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

        if get_user_by_email(email):
            return jsonify({
                "status": "error",
                "message": "A registered user already exists for this email."
            }), 409

        existing = get_pending_invite_by_email(email, company_id)
        if existing:
            return jsonify({
                "status": "error",
                "message": "A valid pending invite already exists for this email."
            }), 409

        # Check subscription limit before creating invitation
        can_add_team_member(company_id)

        token = secrets.token_urlsafe(32)
        expires_at = build_invite_expiry()
        stale_invite = get_pending_invite_by_email(
            email,
            company_id,
            valid_only=False,
        )

        if stale_invite:
            invite = update_invite_for_company(
                stale_invite.get("id"),
                company_id,
                {
                    "token": token,
                    "expires_at": expires_at,
                    "role": role,
                    "status": "pending",
                    "created_by": g.user_id,
                },
            )
        else:
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

    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e)
        }), 403
    except Exception:
        import logging
        logging.exception("Failed to create invitation")
        return jsonify({
            "status": "error",
            "message": "Unable to create invitation."
        }), 500



# ── Admin: List Company Invites ────────────────────────────────────────


@invite_bp.route("", methods=["GET"])
@token_required
def list_company_invites():
    """List invites for the current company, optionally filtered by status."""
    try:
        status = (request.args.get("status") or "").strip().lower() or None
        company_id = g.company_id

        invites = get_invites_by_company(company_id, status=status)

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

    except Exception:
        import logging
        logging.exception("Failed to list company invitations")
        return jsonify({
            "status": "error",
            "message": "Unable to load invitations."
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

        company_id = g.company_id
        invite_id = data.get("invite_id")
        email = (data.get("email") or "").strip().lower()

        if invite_id is None and not email:
            return jsonify({
                "status": "error",
                "message": "Invite ID or email is required."
            }), 400

        if invite_id is None:
            candidate = get_pending_invite_by_email(email, company_id, valid_only=False)
            invite_id = candidate.get("id") if candidate else None
        elif isinstance(invite_id, bool):
            return jsonify({"status": "error", "message": "Invite ID must be a positive integer."}), 400
        else:
            try:
                invite_id = int(invite_id)
            except (TypeError, ValueError):
                return jsonify({"status": "error", "message": "Invite ID must be a positive integer."}), 400

        if not invite_id or invite_id <= 0:
            return jsonify({
                "status": "error",
                "message": "No pending invite found."
            }), 404

        invite = get_invite_by_id(invite_id, company_id)
        if not invite:
            return jsonify({
                "status": "error",
                "message": "No pending invite found."
            }), 404

        if invite.get("status") != "pending":
            return jsonify({
                "status": "error",
                "message": "Only pending invitations can be resent."
            }), 400

        invite_email = str(invite.get("email") or "").strip().lower()
        if not invite_email:
            return jsonify({"status": "error", "message": "Invitation email is missing."}), 400

        token = secrets.token_urlsafe(32)
        expires_at = build_invite_expiry()
        update_invite_for_company(invite_id, company_id, {
            "token": token,
            "expires_at": expires_at,
        })
        invite_link = _build_invite_url(token)

        # Send invite email (non-blocking)
        try:
            from app.services.email_service import send_invite_email
            send_invite_email(invite_email, invite_link, recipient_name=invite_email.split("@")[0])
        except Exception as email_err:
            import logging
            logging.error(f"Failed to resend invite email to {invite_email}: {email_err}")

        return jsonify({
            "status": "success",
            "message": "Invitation resent successfully."
        }), 200

    except Exception:
        import logging
        logging.exception("Failed to resend invitation")
        return jsonify({
            "status": "error",
            "message": "Unable to resend invitation."
        }), 500


# ── Admin: Cancel / Delete Invite ──────────────────────────────────────


@invite_bp.route("/<int:invite_id>", methods=["DELETE"])
@token_required
@role_required("admin", "owner")
def cancel_invite(invite_id):
    """Cancel (delete) a pending invite."""
    try:
        company_id = g.company_id

        invite = get_invite_by_id(invite_id, company_id)
        if not invite:
            return jsonify({
                "status": "error",
                "message": "Invite not found."
            }), 404

        if invite.get("status") != "pending":
            return jsonify({
                "status": "error",
                "message": "Only pending invites can be cancelled."
            }), 400

        delete_invite(invite_id, company_id)

        return jsonify({
            "status": "success",
            "message": "Invitation cancelled successfully."
        }), 200

    except Exception:
        import logging
        logging.exception("Failed to cancel invitation")
        return jsonify({
            "status": "error",
            "message": "Unable to cancel invitation."
        }), 500

# ── Public: Validate Invite Token ─────────────────────────────────────


@invite_bp.route("/validate", methods=["GET"])
@limiter.limit(lambda: __import__("flask").current_app.config.get("RATELIMIT_INVITE_VALIDATE", "30/minute"))
def validate_invite():
    """Check an invite token and return its details if valid."""
    try:
        token = (request.args.get("token") or "").strip()

        if not token:
            return jsonify({
                "status": "error",
                "message": "Token is required."
            }), 400

        invite = get_valid_pending_invitation(token)

        return jsonify({
            "status": "success",
            "valid": True,
            "email": invite.get("email"),
            "role": invite.get("role")
        }), 200

    except InvitationValidationError as e:
        return jsonify({"status": "error", "message": str(e)}), e.status_code
    except Exception:
        import logging
        logging.exception("Failed to validate invitation")
        return jsonify({
            "status": "error",
            "message": "Unable to validate invitation."
        }), 500


# ── Public: Accept Invite ──────────────────────────────────────────────


@invite_bp.route("/accept", methods=["POST"])
@limiter.limit(lambda: __import__("flask").current_app.config.get("RATELIMIT_INVITE_ACCEPT", "5/minute"))
@require_turnstile
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

        # ── Validate password strength ──

        is_strong, msg = validate_password_strength(password)
        if not is_strong:
            return jsonify({
                "status": "error",
                "message": msg
            }), 400

        password_hash = generate_password_hash(password)
        accept_pending_invitation(token, full_name, password_hash)

        return jsonify({
            "status": "success",
            "message": "Account created successfully. You can now log in."
        }), 201

    except InvitationValidationError as e:
        return jsonify({"status": "error", "message": str(e)}), e.status_code
    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e)
        }), 403
    except Exception:
        import logging
        logging.exception("Failed to accept invitation")
        return jsonify({
            "status": "error",
            "message": "Unable to accept invitation."
        }), 500




