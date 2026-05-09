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