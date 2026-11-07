"""OpenRouter keys and which Client uses each one. Service role only: see data/081."""
from app.database.db import supabase

KEYS_TABLE = "openrouter_client_keys"
ASSIGNMENTS_TABLE = "openrouter_key_assignments"
BALANCES_TABLE = "company_ai_credit_balances"
LEDGER_TABLE = "ai_credit_transactions"
#: PostgREST cuts a read off at 1000 rows without saying so.
LEDGER_PAGE_SIZE = 1000
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


def month_credit_micro_myr(key_id, month_start):
    """What the Clients on this key can spend this month: credit left plus what the app has
    charged them since month_start. A key holds few Clients, so the balance read needs no paging.
    """
    assigned = supabase.table(ASSIGNMENTS_TABLE).select("company_id").eq("key_id", key_id).execute()
    company_ids = [row["company_id"] for row in assigned.data]
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


def _set_status(key_id, status):
    supabase.table(KEYS_TABLE).update({"status": status}).eq("id", key_id).execute()


def mark_disabled(key_id):
    _set_status(key_id, "disabled")


def mark_active(key_id):
    _set_status(key_id, "active")
