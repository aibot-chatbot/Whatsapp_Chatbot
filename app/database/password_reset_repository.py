from datetime import datetime, timezone

from app.database.db import supabase


TABLE_NAME = "password_reset_otps"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def upsert_password_reset_otp(email, otp_code, otp_expiry):
    payload = {
        "email": email.strip().lower(),
        "otp_code": otp_code,
        "otp_expiry": otp_expiry,
        "verified": False,
        "updated_at": _now_iso(),
    }

    response = (
        supabase.table(TABLE_NAME)
        .upsert(payload, on_conflict="email")
        .execute()
    )

    rows = response.data or []
    return rows[0] if rows else None


def get_password_reset_otp(email):
    response = (
        supabase.table(TABLE_NAME)
        .select("*")
        .eq("email", email.strip().lower())
        .limit(1)
        .execute()
    )

    rows = response.data or []
    return rows[0] if rows else None


def mark_password_reset_otp_verified(email):
    response = (
        supabase.table(TABLE_NAME)
        .update({
            "verified": True,
            "updated_at": _now_iso(),
        })
        .eq("email", email.strip().lower())
        .execute()
    )

    rows = response.data or []
    return rows[0] if rows else None


def delete_password_reset_otp(email):
    supabase.table(TABLE_NAME).delete().eq("email", email.strip().lower()).execute()
