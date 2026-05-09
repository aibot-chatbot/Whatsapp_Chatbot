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


def create_user(company_id, full_name, email, password_hash, role="admin", status="active"):
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