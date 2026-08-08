from datetime import datetime, timezone

from app.database.db import supabase


TABLE_NAME = "companies"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def create_company(company_name, business_type=None, contact_email=None, contact_phone=None):
    if not company_name:
        raise ValueError("Company name is required")

    payload = {
        "company_name": company_name.strip(),
        "business_type": business_type or "",
        "contact_email": contact_email or "",
        "contact_phone": contact_phone or "",
        "status": "active",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }

    response = supabase.table(TABLE_NAME).insert(payload).execute()
    rows = response.data or []

    if not rows:
        raise ValueError("Failed to create company")

    return rows[0]


def get_company_by_id(company_id):
    if not company_id:
        raise ValueError("Company ID is required")

    response = (
        supabase.table(TABLE_NAME)
        .select("id,company_name,contact_email,contact_phone")
        .eq("id", company_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def get_company_status_by_id(company_id):
    if not company_id:
        raise ValueError("Company ID is required")

    response = (
        supabase.table(TABLE_NAME)
        .select("id,status")
        .eq("id", company_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def update_company(company_id, updates):
    if not company_id:
        raise ValueError("Company ID is required")

    allowed_fields = {"company_name", "contact_email", "contact_phone"}
    payload = {key: value for key, value in (updates or {}).items() if key in allowed_fields}
    if not payload:
        raise ValueError("No company fields to update")

    payload["updated_at"] = _now_iso()
    response = (
        supabase.table(TABLE_NAME)
        .update(payload)
        .eq("id", company_id)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise ValueError("Company not found or access denied")
    return rows[0]
