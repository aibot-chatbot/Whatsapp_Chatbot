from datetime import datetime, timedelta, timezone

from app.database.db import supabase


TABLE_NAME = "invites"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _expires_at_iso(hours=72):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def build_invite_expiry(hours=72):
    return _expires_at_iso(hours)


def _positive_integer(value, field_name):
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a positive integer")
    try:
        normalized = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"{field_name} must be a positive integer")
    if normalized <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return normalized


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


def get_pending_invite_by_email(email, company_id, valid_only=True):
    """Fetch a company-scoped pending invite, optionally requiring valid expiry."""
    normalized_email = str(email or "").strip().lower()
    if not normalized_email:
        return None
    company_id = _positive_integer(company_id, "Company ID")
    response = (
        supabase.table(TABLE_NAME)
        .select("*")
        .eq("email", normalized_email)
        .eq("company_id", company_id)
        .eq("status", "pending")
        .order("id", desc=True)
        .execute()
    )
    rows = response.data or []
    if not valid_only:
        return rows[0] if rows else None

    now = datetime.now(timezone.utc)
    for row in rows:
        expiry = _parse_expiry(row.get("expires_at"))
        if expiry is not None and expiry > now:
            return row
    return None


def count_valid_pending_invitations(company_id):
    """Count only pending invitations with a present, parseable future expiry."""
    company_id = _positive_integer(company_id, "Company ID")
    response = (
        supabase.table(TABLE_NAME)
        .select("id,expires_at")
        .eq("company_id", company_id)
        .eq("status", "pending")
        .execute()
    )
    now = datetime.now(timezone.utc)
    count = 0
    for row in response.data or []:
        expiry = _parse_expiry(row.get("expires_at"))
        if expiry is not None and expiry > now:
            count += 1
    return count


def get_invite_by_token(token):
    """Fetch an invite by its token regardless of status."""
    if not token:
        return None
    response = (
        supabase.table(TABLE_NAME)
        .select("*")
        .eq("token", token)
        .limit(1)
        .execute()
    )
    data = response.data
    return data[0] if data else None


def update_invite(token, company_id, payload):
    """Update an invitation by token within its validated company."""
    if not token:
        raise ValueError("Token is required")
    company_id = _positive_integer(company_id, "Company ID")

    scoped_payload = dict(payload or {})
    if not scoped_payload:
        raise ValueError("No invitation fields to update")
    scoped_payload["updated_at"] = _now_iso()

    response = (
        supabase.table(TABLE_NAME)
        .update(scoped_payload)
        .eq("token", token)
        .eq("company_id", company_id)
        .execute()
    )

    rows = response.data or []

    if not rows:
        raise ValueError("Failed to update invite")

    return rows[0]


def create_invite(email, company_id, role, token, created_by):
    """Insert a new invite record."""
    company_id = _positive_integer(company_id, "Company ID")
    created_by = _positive_integer(created_by, "Creator user ID")
    normalized_email = str(email or "").strip().lower()
    normalized_role = str(role or "").strip().lower()
    if not normalized_email:
        raise ValueError("Email is required")
    if normalized_role not in ("admin", "member"):
        raise ValueError("Role must be 'admin' or 'member'")
    if not token:
        raise ValueError("Token is required")
    payload = {
        "email": normalized_email,
        "company_id": company_id,
        "role": normalized_role,
        "token": token,
        "status": "pending",
        "expires_at": _expires_at_iso(),
        "created_by": created_by,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }

    response = supabase.table(TABLE_NAME).insert(payload).execute()
    rows = response.data or []

    if not rows:
        raise ValueError("Failed to create invite")

    return rows[0]

def get_invites_by_company(company_id, status=None):
    """List invites for a company, optionally filtered by status."""
    company_id = _positive_integer(company_id, "Company ID")
    query = supabase.table(TABLE_NAME).select("*").eq("company_id", company_id)
    if status:
        query = query.eq("status", status.lower())
    response = query.order("id", desc=True).execute()
    return response.data or []


def get_invite_by_id(invite_id, company_id):
    """Fetch one invitation using both its id and tenant company id."""
    invite_id = _positive_integer(invite_id, "Invite ID")
    company_id = _positive_integer(company_id, "Company ID")
    response = (
        supabase.table(TABLE_NAME)
        .select("*")
        .eq("id", invite_id)
        .eq("company_id", company_id)
        .limit(1)
        .execute()
    )
    data = response.data
    return data[0] if data else None


def update_invite_for_company(invite_id, company_id, payload):
    """Update an invitation using both its id and tenant company id."""
    invite_id = _positive_integer(invite_id, "Invite ID")
    company_id = _positive_integer(company_id, "Company ID")
    scoped_payload = dict(payload or {})
    if not scoped_payload:
        raise ValueError("No invitation fields to update")
    scoped_payload["updated_at"] = _now_iso()
    response = (
        supabase.table(TABLE_NAME)
        .update(scoped_payload)
        .eq("id", invite_id)
        .eq("company_id", company_id)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise ValueError("Failed to update invite")
    return rows[0]


def delete_invite(invite_id, company_id):
    """Delete an invitation using both its id and tenant company id."""
    invite_id = _positive_integer(invite_id, "Invite ID")
    company_id = _positive_integer(company_id, "Company ID")
    response = (
        supabase.table(TABLE_NAME)
        .delete()
        .eq("id", invite_id)
        .eq("company_id", company_id)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise ValueError("Failed to delete invite")
    return rows[0]
