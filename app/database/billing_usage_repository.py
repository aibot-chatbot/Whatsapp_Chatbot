from datetime import datetime, timezone

from app.database.db import supabase


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _active_company_chatbots(company_id, columns):
    if not company_id:
        raise ValueError("Company ID is required")

    response = (
        supabase
        .table("chatbots")
        .select(columns)
        .eq("company_id", company_id)
        .is_("deleted_at", "null")
        .neq("status", "archived")
        .execute()
    )

    return response.data or []


def get_company_chatbot_ids(company_id):
    """Return active, non-archived chatbot IDs belonging to a company."""
    return [row["id"] for row in _active_company_chatbots(company_id, "id")]


def count_company_chatbots(company_id):
    """Count active, non-archived chatbots belonging to a company.

    Archived chatbots preserve their data but no longer consume a plan slot.
    Uses database COUNT with count="exact" for efficiency.
    """
    if not company_id:
        raise ValueError("Company ID is required")

    response = (
        supabase
        .table("chatbots")
        .select("id", count="exact")
        .eq("company_id", company_id)
        .is_("deleted_at", "null")
        .neq("status", "archived")
        .execute()
    )

    return response.count or 0


def count_active_company_members(company_id):
    """Count active team members (status = active) for a company.

    Uses the users table status field directly. This includes all roles
    (admin, owner, member) that have status = active.
    Uses database COUNT with count="exact" for efficiency.
    """
    if not company_id:
        raise ValueError("Company ID is required")

    response = (
        supabase
        .table("users")
        .select("id", count="exact")
        .eq("company_id", company_id)
        .eq("status", "active")
        .execute()
    )

    return response.count or 0



def count_pending_company_invitations(company_id):
    """Count pending valid invitations for a company.

    Pending invitations are counted only if:
      - status = 'pending'
      - expires_at is NULL OR expires_at > current UTC time

    This prevents companies from bypassing the team_member_limit by
    creating unlimited pending invitations.

    Accepted, expired or deleted invitations are not counted.
    """
    if not company_id:
        raise ValueError("Company ID is required")

    now_iso = datetime.now(timezone.utc).isoformat()

    # Fetch all pending invites for this company
    response = (
        supabase
        .table("invites")
        .select("id,expires_at")
        .eq("company_id", company_id)
        .eq("status", "pending")
        .execute()
    )

    rows = response.data or []

    if not rows:
        return 0

    count = 0
    for row in rows:
        expires_at = row.get("expires_at")
        if not expires_at:
            # No expiry set — treat as valid
            count += 1
        else:
            try:
                expires_dt = datetime.fromisoformat(expires_at)
                if expires_dt > datetime.now(timezone.utc):
                    count += 1
            except (ValueError, TypeError):
                # Malformed expiry — count it (fail open to avoid bypass)
                count += 1

    return count

def list_company_channel_slots(company_id):
    """Return the connected channels that hold a company's paid channel slots,
    one dict per slot: provider, chatbot_id, bot_name.

    Slots are a company-wide pool, so the Publish page of one bot needs the
    bot names to explain a full plan.

    All three channel tables use the same status convention:
      - is_active = true  (channel record is active)
      - connection_status = 'connected'  (channel handshake completed)

    A disconnected channel has is_active = false and
    connection_status = 'disconnected', so it is excluded.
    Channels linked to archived or deleted/missing chatbots are also excluded
    because they no longer represent a usable connected channel.
    """
    bot_names = {
        row["id"]: row.get("bot_name")
        for row in _active_company_chatbots(company_id, "id,bot_name")
    }

    if not bot_names:
        return []

    slots = []

    for provider in ("telegram", "wasender", "whatsapp"):
        response = (
            supabase
            .table(f"{provider}_channels")
            .select("chatbot_id")
            .eq("company_id", company_id)
            .eq("is_active", True)
            .eq("connection_status", "connected")
            .in_("chatbot_id", list(bot_names))
            .execute()
        )
        slots.extend(
            {"provider": provider, "chatbot_id": row["chatbot_id"],
             "bot_name": bot_names[row["chatbot_id"]]}
            for row in (response.data or [])
        )

    return slots


def count_company_channels(company_id):
    """Count the paid channel slots in use; see list_company_channel_slots."""
    return len(list_company_channel_slots(company_id))


def count_company_knowledge_files(company_id):
    """Count total knowledge files across all chatbots for a company.

    Knowledge files are hard-deleted (DELETE query), so every remaining row
    represents a file that exists in storage and consumes the company's
    file allowance.

    Files are linked to chatbot_id, so we first get the company's chatbot IDs
    then query knowledge_files with an IN filter.
    Uses database COUNT with count="exact".
    """
    if not company_id:
        raise ValueError("Company ID is required")

    chatbot_ids = get_company_chatbot_ids(company_id)

    if not chatbot_ids:
        return 0

    response = (
        supabase
        .table("knowledge_files")
        .select("id", count="exact")
        .in_("chatbot_id", chatbot_ids)
        .execute()
    )

    return response.count or 0


def sum_company_knowledge_storage(company_id):
    """Sum total knowledge file sizes across all chatbots for a company.

    Every remaining row in knowledge_files corresponds to a file on storage
    (hard delete removes both), so all rows contribute to storage usage.

    NULL file_size is handled safely (treated as 0 bytes).

    Note: This uses a SELECT query rather than SUM aggregation because
    Supabase may not support sum() on the json/db interface for all column
    types. The result is an integer byte count. Only id and chatbot_id fields
    are selected (no large content fields).
    """
    if not company_id:
        raise ValueError("Company ID is required")

    chatbot_ids = get_company_chatbot_ids(company_id)

    if not chatbot_ids:
        return 0

    response = (
        supabase
        .table("knowledge_files")
        .select("file_size")
        .in_("chatbot_id", chatbot_ids)
        .execute()
    )

    rows = response.data or []

    if not rows:
        return 0

    total = 0
    for row in rows:
        size = row.get("file_size")
        if size is not None:
            total += int(size)
    return total


def sum_company_ai_usage_tokens(company_id, period_start, period_end):
    """Aggregate AI usage token counts for a company over a billing period.

    Sums prompt_tokens, completion_tokens, and total_tokens from ai_usage_logs
    scoped to the company and time range.

    Args:
        company_id: The company to aggregate tokens for.
        period_start: Start of the billing period (inclusive).
        period_end: End of the billing period (exclusive).

    Returns:
        dict: {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}
        All values default to 0 when no usage exists or the company has no chatbots.
    """
    if not company_id:
        raise ValueError("Company ID is required")

    if not period_start or not period_end:
        raise ValueError("period_start and period_end are required")

    period_start_iso = (
        period_start.isoformat()
        if hasattr(period_start, "isoformat")
        else str(period_start)
    )
    period_end_iso = (
        period_end.isoformat()
        if hasattr(period_end, "isoformat")
        else str(period_end)
    )

    response = (
        supabase
        .table("ai_usage_logs")
        .select("prompt_tokens,completion_tokens,total_tokens")
        .eq("company_id", company_id)
        .eq("request_status", "completed")
        .gte("created_at", period_start_iso)
        .lt("created_at", period_end_iso)
        .execute()
    )

    rows = response.data or []

    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0

    for row in rows:
        prompt_tokens += row.get("prompt_tokens") or 0
        completion_tokens += row.get("completion_tokens") or 0
        total_tokens += row.get("total_tokens") or 0

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
