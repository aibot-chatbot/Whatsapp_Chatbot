"""OpenRouter keys and which Client uses each one. Service role only: see data/081."""
from app.database.db import supabase

KEYS_TABLE = "openrouter_client_keys"
ASSIGNMENTS_TABLE = "openrouter_key_assignments"
BALANCES_TABLE = "company_ai_credit_balances"
LEDGER_TABLE = "ai_credit_transactions"
#: PostgREST cuts a read off at 1000 rows without saying so.
LEDGER_PAGE_SIZE = 1000
_KEY_COLUMNS = "id,key_hash,encrypted_key,label,status"
# Kept out of _KEY_COLUMNS: they come from data/082, and every other read must work without it.
_REASON_COLUMNS = "id,disabled_reason,culprit_company_id"


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


def _charged_since(company_ids, since):
    total, offset = 0, 0
    while True:
        rows = (
            supabase.table(LEDGER_TABLE)
            .select("customer_charge_micro_myr")
            .in_("company_id", company_ids)
            .eq("transaction_type", "usage_debit")
            .gte("created_at", since)
            .order("id")
            .range(offset, offset + LEDGER_PAGE_SIZE - 1)
            .execute()
        ).data
        total += sum(row["customer_charge_micro_myr"] or 0 for row in rows)
        if len(rows) < LEDGER_PAGE_SIZE:
            return total
        offset += LEDGER_PAGE_SIZE


def list_key_companies(key_id):
    """The Clients on this key. A key holds few Clients, so the read needs no paging."""
    assigned = supabase.table(ASSIGNMENTS_TABLE).select("company_id").eq("key_id", key_id).execute()
    return [row["company_id"] for row in assigned.data]


def month_credit_micro_myr(key_id, month_start):
    """What the Clients on this key can spend this month: credit left plus what the app has
    charged them since month_start. A key holds few Clients, so the balance read needs no paging.
    """
    company_ids = list_key_companies(key_id)
    if not company_ids:
        return 0
    balances = (
        supabase.table(BALANCES_TABLE)
        .select("included_balance_micro_myr,topup_balance_micro_myr")
        .in_("company_id", company_ids)
        .execute()
    )
    credit_left = sum(row["included_balance_micro_myr"] + row["topup_balance_micro_myr"] for row in balances.data)
    return credit_left + _charged_since(company_ids, month_start)


def assign_company(company_id, key_id):
    """Keeps the existing assignment if there is one: a Client never changes key by accident."""
    supabase.table(ASSIGNMENTS_TABLE).upsert(
        {"company_id": company_id, "key_id": key_id},
        on_conflict="company_id",
        ignore_duplicates=True,
    ).execute()


def move_company(company_id, from_key_id, to_key_id):
    """Only while the Client is still on from_key_id, so a move never undoes another change.
    Needs the UPDATE grant from data/082.
    """
    (
        supabase.table(ASSIGNMENTS_TABLE)
        .update({"key_id": to_key_id})
        .eq("company_id", company_id)
        .eq("key_id", from_key_id)
        .execute()
    )


def list_disable_reasons():
    """Why each disabled key was disabled, by key id. The columns come from data/082, so this
    raises until that migration is applied.
    """
    result = supabase.table(KEYS_TABLE).select(_REASON_COLUMNS).eq("status", "disabled").execute()
    return {row["id"]: row for row in result.data}


def _set_status(key_id, status):
    supabase.table(KEYS_TABLE).update({"status": status}).eq("id", key_id).execute()


def mark_disabled(key_id, reason=None, culprit_company_id=None):
    """reason is "ours" (culprit_company_id names the Client it was disabled for) or "openrouter".
    Both need data/082; with no reason only the status is written, which works without it.
    """
    if reason is None:
        _set_status(key_id, "disabled")
        return
    supabase.table(KEYS_TABLE).update({
        "status": "disabled",
        "disabled_reason": reason,
        "culprit_company_id": culprit_company_id,
    }).eq("id", key_id).execute()


def mark_active(key_id):
    _set_status(key_id, "active")
