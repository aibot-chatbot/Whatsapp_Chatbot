from datetime import datetime, timezone

from app.database.invite_repository import get_invite_by_token, update_invite
from app.database.user_repository import create_user, get_user_by_email
from app.services.billing_guard import can_accept_team_invitation


class InvitationValidationError(ValueError):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


def _parse_expiry(value):
    if not value:
        return None
    try:
        expiry = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return expiry


def _positive_company_id(value):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    return value


def get_valid_pending_invitation(token):
    invite = get_invite_by_token(token)
    if not invite:
        raise InvitationValidationError("Invalid invite token.", 404)
    if invite.get("status") != "pending":
        raise InvitationValidationError("This invite has already been used.", 410)

    company_id = _positive_company_id(invite.get("company_id"))
    if company_id is None:
        raise InvitationValidationError("This invitation has invalid company information.", 400)

    email = str(invite.get("email") or "").strip().lower()
    if not email:
        raise InvitationValidationError("This invitation has no email address.", 400)

    role = invite.get("role")
    if role not in ("admin", "member"):
        raise InvitationValidationError("This invitation has an invalid role.", 400)

    expiry = _parse_expiry(invite.get("expires_at"))
    if expiry is None:
        raise InvitationValidationError("This invitation has an invalid expiry.", 410)
    if expiry <= datetime.now(timezone.utc):
        raise InvitationValidationError("This invite has expired.", 410)

    validated = dict(invite)
    validated["company_id"] = company_id
    validated["email"] = email
    return validated


def accept_pending_invitation(token, full_name, password_hash, verified_email=None):
    invite = get_valid_pending_invitation(token)
    invite_email = str(invite.get("email") or "").strip().lower()
    if verified_email is not None and invite_email != str(verified_email).strip().lower():
        raise InvitationValidationError(
            "The Google account email does not match this invitation.",
            403,
        )
    if get_user_by_email(invite_email):
        raise InvitationValidationError("This email is already registered.", 409)

    company_id = invite["company_id"]
    can_accept_team_invitation(company_id)
    user = create_user(
        company_id=company_id,
        full_name=full_name,
        email=invite_email,
        password_hash=password_hash,
        role=invite["role"],
        status="active",
        is_verified=True,
    )
    update_invite(token, company_id, {
        "status": "accepted",
        "accepted_at": datetime.now(timezone.utc).isoformat(),
    })
    return user
