from datetime import datetime, timedelta, timezone

from app.database.db import supabase


TABLE_NAME = "invites"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _expires_at_iso(hours=72):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def get_pending_invite_by_email(email, company_id):
    """Check if a pending invite already exists for this email + company."""
    try:
        company_id = int(company_id)
    except (ValueError, TypeError):
        pass
    response = (
        supabase.table(TABLE_NAME)
        .select("*")
        .eq("email", email.strip().lower())
        .eq("company_id", company_id)
        .eq("status", "pending")
        .limit(1)
        .execute()
    )
    data = response.data
    return data[0] if data else None


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


def update_invite(token, payload):
    """Update an invite record by token."""
    if not token:
        raise ValueError("Token is required")

    payload["updated_at"] = _now_iso()

    response = (
        supabase.table(TABLE_NAME)
        .update(payload)
        .eq("token", token)
        .execute()
    )

    rows = response.data or []

    if not rows:
        raise ValueError("Failed to update invite")

    return rows[0]


def create_invite(email, company_id, role, token, created_by):
    """Insert a new invite record."""
    try:
        company_id = int(company_id)
    except (ValueError, TypeError):
        pass
    payload = {
        "email": email.strip().lower(),
        "company_id": company_id,
        "role": role,
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
    import logging
    try:
        # Normalize company_id to int (Supabase stores this as int)
        try:
            company_id_int = int(company_id)
        except (ValueError, TypeError):
            company_id_int = company_id
        company_id_str = str(company_id)

        # Strategy 1: try int match first
        query = supabase.table(TABLE_NAME).select("*").eq("company_id", company_id_int)
        if status:
            query = query.eq("status", status.lower())
        response = query.order("id", desc=True).execute()
        result = response.data or []

        logging.warning(f"get_invites_by_company: int match for company_id={company_id_int!r} returned {len(result)} rows")

        if not result:
            # Strategy 2: try string match
            query2 = supabase.table(TABLE_NAME).select("*").eq("company_id", company_id_str)
            if status:
                query2 = query2.eq("status", status.lower())
            response2 = query2.order("id", desc=True).execute()
            result = response2.data or []
            logging.warning(f"get_invites_by_company: str match for company_id={company_id_str!r} returned {len(result)} rows")

        if not result:
            # Strategy 3: fetch all invites and filter in Python
            all_resp = supabase.table(TABLE_NAME).select("*").order("id", desc=True).execute()
            all_data = all_resp.data or []
            logging.warning(f"get_invites_by_company: total invites in table: {len(all_data)}")
            if all_data:
                # Show distinct company_id values
                distinct = set(r.get("company_id") for r in all_data)
                logging.warning(f"get_invites_by_company: distinct company_ids in table: {distinct!r}")
                logging.warning(f"get_invites_by_company: looking for company_id={company_id_int!r} or {company_id_str!r}")

                # Filter by matching company_id (try both int and str)
                result = []
                for r in all_data:
                    db_cid = r.get("company_id")
                    if db_cid == company_id_int or db_cid == company_id_str:
                        if status:
                            if r.get("status") == status.lower():
                                result.append(r)
                        else:
                            result.append(r)

                logging.warning(f"get_invites_by_company: post-filter matched {len(result)} rows")

        return result
    except Exception as e:
        logging.error(f"get_invites_by_company error: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return []


def get_invite_by_id(invite_id):
    """Fetch a single invite by its id."""
    if not invite_id:
        return None
    response = (
        supabase.table(TABLE_NAME)
        .select("*")
        .eq("id", invite_id)
        .limit(1)
        .execute()
    )
    data = response.data
    return data[0] if data else None


def delete_invite(invite_id):
    """Delete an invite record by id."""
    if not invite_id:
        raise ValueError("Invite id is required")
    response = (
        supabase.table(TABLE_NAME)
        .delete()
        .eq("id", invite_id)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise ValueError("Failed to delete invite")
    return rows[0]
