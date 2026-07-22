import re

from app.database.company_repository import get_company_by_id, update_company
from app.database.invite_repository import count_valid_pending_invitations
from app.database.user_repository import count_active_users_by_company
from app.services.billing_service import get_current_subscription


MANAGEMENT_ROLES = frozenset({"admin", "owner"})
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _normalized_role(user):
    return str((user or {}).get("role") or "").strip().lower()


def _format_workspace(company, user, active_members, pending_invitations, subscription):
    role = _normalized_role(user)
    can_manage = role in MANAGEMENT_ROLES
    active_members = max(int(active_members or 0), 0)
    pending_invitations = max(int(pending_invitations or 0), 0)
    plan = (subscription or {}).get("plan") or {}
    plan_member_limit = plan.get("team_member_limit")
    remaining_seats = None
    if plan_member_limit is not None:
        remaining_seats = max(
            int(plan_member_limit) - active_members - pending_invitations,
            0,
        )

    return {
        "company": {
            "name": company.get("company_name") or "",
            "contact_email": company.get("contact_email") or "",
            "contact_phone": company.get("contact_phone") or "",
        },
        "current_user_role": role,
        "active_member_count": active_members,
        "pending_invitation_count": pending_invitations,
        "plan_member_limit": plan_member_limit,
        "remaining_seats": remaining_seats,
        "can_edit_company": can_manage,
        "can_manage_team": can_manage,
    }


def get_workspace_summary(company_id, user):
    company = get_company_by_id(company_id)
    if not company:
        raise LookupError("Company not found")

    active_members = count_active_users_by_company(company_id)
    pending_invitations = count_valid_pending_invitations(company_id)
    subscription = get_current_subscription(company_id)
    return _format_workspace(
        company,
        user,
        active_members,
        pending_invitations,
        subscription,
    )


def update_workspace_company(company_id, user, data):
    if _normalized_role(user) not in MANAGEMENT_ROLES:
        raise PermissionError("You do not have permission to update company information.")

    company_name = str((data or {}).get("company_name") or "").strip()
    contact_email = str((data or {}).get("contact_email") or "").strip().lower()
    if not company_name:
        raise ValueError("Company name is required.")
    if len(company_name) > 200:
        raise ValueError("Company name must be 200 characters or fewer.")
    if not contact_email:
        raise ValueError("Company contact email is required.")
    if len(contact_email) > 320 or not EMAIL_PATTERN.fullmatch(contact_email):
        raise ValueError("Please enter a valid company contact email.")

    updates = {
        "company_name": company_name,
        "contact_email": contact_email,
    }
    if "contact_phone" in (data or {}):
        contact_phone = str(data.get("contact_phone") or "").strip()
        if len(contact_phone) > 50:
            raise ValueError("Company phone must be 50 characters or fewer.")
        updates["contact_phone"] = contact_phone

    update_company(company_id, updates)
    return get_workspace_summary(company_id, user)
