from datetime import datetime, timezone

from app.database.db import supabase


TABLE_NAME = "users"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_user_by_email(email):
    response = (
        supabase.table(TABLE_NAME)
        .select("*")
        .eq("email", email)
        .limit(1)
        .execute()
    )

    data = response.data

    if not data:
        return None

    return data[0]


def create_user(company_id, full_name, email, password_hash, role="admin", status="active", is_verified=False):
    if not company_id:
        raise ValueError("Company ID is required")

    if not full_name:
        raise ValueError("Full name is required")

    if not email:
        raise ValueError("Email is required")

    payload = {
        "company_id": company_id,
        "full_name": full_name.strip(),
        "email": email.strip().lower(),
        "password_hash": password_hash,
        "is_verified": is_verified,
        "role": role,
        "status": status,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }

    response = supabase.table(TABLE_NAME).insert(payload).execute()
    rows = response.data or []

    if not rows:
        raise ValueError("Failed to create user")

    return rows[0]

def get_user_by_id(user_id):
    response = (
        supabase.table(TABLE_NAME)
        .select("*")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )

    data = response.data

    if not data:
        return None

    return data[0]


def get_user_by_id_for_company(user_id, company_id):
    if not user_id or not company_id:
        return None
    response = (
        supabase.table(TABLE_NAME)
        .select("*")
        .eq("id", user_id)
        .eq("company_id", company_id)
        .limit(1)
        .execute()
    )
    data = response.data or []
    return data[0] if data else None


def update_user(user_id, payload):
    if not user_id:
        raise ValueError("User ID is required")

    payload["updated_at"] = _now_iso()

    response = (
        supabase.table(TABLE_NAME)
        .update(payload)
        .eq("id", user_id)
        .execute()
    )

    rows = response.data or []

    if not rows:
        raise ValueError("Failed to update user")

    return rows[0]


def update_user_for_company(user_id, company_id, payload):
    if not user_id:
        raise ValueError("User ID is required")
    if not company_id:
        raise ValueError("Company ID is required")

    scoped_payload = dict(payload or {})
    if not scoped_payload:
        raise ValueError("No fields to update")
    scoped_payload["updated_at"] = _now_iso()

    response = (
        supabase.table(TABLE_NAME)
        .update(scoped_payload)
        .eq("id", user_id)
        .eq("company_id", company_id)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise ValueError("User not found or access denied")
    return rows[0]


def get_users_by_company(company_id):
    if not company_id:
        raise ValueError("Company ID is required")

    response = (
        supabase.table(TABLE_NAME)
        .select("id, company_id, full_name, email, role, status, is_verified, created_at, updated_at")
        .eq("company_id", company_id)
        .order("created_at")
        .execute()
    )

    return response.data or []


def count_active_users_by_company(company_id):
    """Return an exact count of active users in a company without loading rows."""
    if not company_id:
        raise ValueError("Company ID is required")

    response = (
        supabase.table(TABLE_NAME)
        .select("id", count="exact", head=True)
        .eq("company_id", company_id)
        .eq("status", "active")
        .execute()
    )
    try:
        count = int(response.count or 0)
    except (TypeError, ValueError):
        count = 0
    return max(count, 0)


def count_active_admins_by_company(company_id):
    """Count active admin/owner users in a company."""
    response = (
        supabase.table(TABLE_NAME)
        .select("id", count="exact")
        .eq("company_id", company_id)
        .in_("role", ["admin", "owner"])
        .eq("status", "active")
        .execute()
    )
    return response.count or 0


def get_company_billing_contact(company_id):
    """Return the person billing email should reach for a company.

    That is the account owner: the earliest-created active admin, which is the
    user who registered the company. There is currently no "owner" role in the
    data - every account holder is stored as "admin" - but the role filter
    tolerates both so this keeps working if one is introduced later.

    Ordering by created_at rather than id is deliberate: it survives a future
    change to non-sequential identifiers.

    Returns {"email": str, "full_name": str} or None when the company has no
    active admin. Callers must treat None as "no one to email" rather than an
    error, because a company with every seat deactivated is a real state and
    must not break billing.

    Only email and full_name are selected. This row also carries password_hash,
    otp_code and otp_expiry, and none of them should travel with a notification.
    """
    response = (
        supabase.table(TABLE_NAME)
        .select("email, full_name")
        .eq("company_id", company_id)
        .in_("role", ["admin", "owner"])
        .eq("status", "active")
        .order("created_at", desc=False)
        .limit(1)
        .execute()
    )
    rows = getattr(response, "data", None) or []
    if not rows:
        return None
    contact = rows[0]
    email = (contact.get("email") or "").strip()
    if not email:
        return None
    return {"email": email, "full_name": (contact.get("full_name") or "").strip() or "there"}
