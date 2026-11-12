"""Supabase calls for self-service workspace deletion. No decisions are made here.

Eligibility and the deletion itself live in two SECURITY DEFINER functions
(data/080): account_deletion_blocker and delete_company_account. The
confirmation code is a row in account_deletion_codes, which only the service
role can reach.
"""

from app.database.db import supabase

CODES_TABLE = "account_deletion_codes"

# PostgREST answers at most 1000 rows per request and does not say so.
PAGE_SIZE = 1000
# Keeps the `in` filter's URL well under typical proxy limits.
CHATBOT_ID_CHUNK = 50


def get_deletion_blocker(company_id, user_id):
    """Return None when this user may delete this workspace, else a stable reason code."""
    data = supabase.rpc(
        "account_deletion_blocker",
        {"p_company_id": company_id, "p_user_id": user_id},
    ).execute().data
    if isinstance(data, list):
        data = data[0] if data else None
    if data is None:
        return None
    if isinstance(data, str) and data:
        return data
    # Fail closed: an answer this code does not understand must never read as "eligible".
    raise ValueError("account_deletion_blocker returned an unexpected value")


def upsert_deletion_code(user_id, code_hash, expires_at):
    """Store the code's hash, replacing any earlier code and resetting its attempts."""
    supabase.table(CODES_TABLE).upsert(
        {"user_id": user_id, "code_hash": code_hash, "expires_at": expires_at, "attempts": 0},
        on_conflict="user_id",
    ).execute()


def get_deletion_code(user_id):
    rows = (
        supabase.table(CODES_TABLE)
        .select("user_id, code_hash, expires_at, attempts")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
    ) or []
    return rows[0] if rows else None


def claim_deletion_code_attempt(user_id, code_hash, seen_attempts):
    """Spend one guess on exactly this code; True only for the caller that won it.

    A conditional update (compare-and-swap on attempts and the hash): of several
    concurrent guesses that read the same count, one matches and the rest match no
    row, so the attempt cap holds however many requests arrive at once.
    """
    rows = (
        supabase.table(CODES_TABLE)
        .update({"attempts": seen_attempts + 1})
        .eq("user_id", user_id)
        .eq("code_hash", code_hash)
        .eq("attempts", seen_attempts)
        .execute()
        .data
    )
    return bool(rows)


def delete_deletion_code(user_id):
    supabase.table(CODES_TABLE).delete().eq("user_id", user_id).execute()


def delete_company_account_rpc(company_id, user_id):
    """Run the transactional deletion; returns its {status, code, ...} verdict."""
    data = supabase.rpc(
        "delete_company_account",
        {"p_company_id": company_id, "p_user_id": user_id},
    ).execute().data
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _all_rows(build_query):
    """Every row of a query, one page at a time, ordered by id so pages do not overlap."""
    rows, offset = [], 0
    while True:
        page = build_query().order("id").range(offset, offset + PAGE_SIZE - 1).execute().data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def list_company_storage_files(company_id):
    """The stored-document rows to clean up after the database rows are gone.

    Must be read BEFORE the deletion: afterwards the rows that name the files
    no longer exist. Returns {"knowledge": [...], "media": [...]}, each row
    carrying the chatbot_id the service uses to prove the file is this tenant's.
    """
    chatbot_ids = [
        row["id"]
        for row in _all_rows(lambda: supabase.table("chatbots").select("id").eq("company_id", company_id))
    ]
    knowledge, media = [], []
    for start in range(0, len(chatbot_ids), CHATBOT_ID_CHUNK):
        chunk = chatbot_ids[start:start + CHATBOT_ID_CHUNK]
        knowledge.extend(_all_rows(
            lambda chunk=chunk: supabase.table("knowledge_files")
            .select("id, chatbot_id, file_name, file_path").in_("chatbot_id", chunk)
        ))
        media.extend(_all_rows(
            lambda chunk=chunk: supabase.table("bot_media_attachments")
            .select("id, chatbot_id, media_url").in_("chatbot_id", chunk)
        ))
    return {"knowledge": knowledge, "media": media}
