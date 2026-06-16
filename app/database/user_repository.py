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
