"""OpenRouter keys and which Client uses each one. Service role only: see data/081."""
from app.database.db import supabase

KEYS_TABLE = "openrouter_client_keys"
ASSIGNMENTS_TABLE = "openrouter_key_assignments"
_KEY_COLUMNS = "id,key_hash,encrypted_key,label,status"


def create_key(key_hash, encrypted_key, label):
    result = supabase.table(KEYS_TABLE).insert({
        "key_hash": key_hash,
        "encrypted_key": encrypted_key,
        "label": label,
    }).execute()
    return result.data[0]


def get_company_key(company_id):
    result = (
        supabase.table(ASSIGNMENTS_TABLE)
        .select(f"{KEYS_TABLE}({_KEY_COLUMNS})")
        .eq("company_id", company_id)
        .limit(1)
        .execute()
    )
    return result.data[0][KEYS_TABLE] if result.data else None


def list_keys(status):
    """Keys with this status, oldest first, each with its number of Clients."""
    result = (
        supabase.table(KEYS_TABLE)
        .select(f"{_KEY_COLUMNS},{ASSIGNMENTS_TABLE}(count)")
        .eq("status", status)
        .order("id")
        .execute()
    )
    return [
        {key: value for key, value in row.items() if key != ASSIGNMENTS_TABLE}
        | {"clients": sum(item["count"] for item in row[ASSIGNMENTS_TABLE])}
        for row in result.data
    ]


def assign_company(company_id, key_id):
    """Keeps the existing assignment if there is one: a Client never changes key by accident."""
    supabase.table(ASSIGNMENTS_TABLE).upsert(
        {"company_id": company_id, "key_id": key_id},
        on_conflict="company_id",
        ignore_duplicates=True,
    ).execute()


def _set_status(key_id, status):
    supabase.table(KEYS_TABLE).update({"status": status}).eq("id", key_id).execute()


def mark_disabled(key_id):
    _set_status(key_id, "disabled")


def mark_active(key_id):
    _set_status(key_id, "active")
