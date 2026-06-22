from datetime import datetime, timezone

from app.database.db import supabase


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_company_chatbot_ids(company_id):
    """Return list of chatbot IDs belonging to a company."""
    if not company_id:
        raise ValueError("Company ID is required")

    response = (
        supabase
        .table("chatbots")
        .select("id")
        .eq("company_id", company_id)
        .execute()
    )

    return [row["id"] for row in (response.data or [])]


def count_company_chatbots(company_id):
    """Count all chatbots belonging to a company.

    Chatbots are hard-deleted from the database, so every existing row
    represents an active chatbot resource consuming a plan slot.
    Uses database COUNT with count="exact" for efficiency.
    """
    if not company_id:
        raise ValueError("Company ID is required")

    response = (
        supabase
        .table("chatbots")
        .select("id", count="exact")
        .eq("company_id", company_id)
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


def count_company_channels(company_id):
    """Count connected channels across Telegram, Wasender, and WhatsApp
    channel tables for a company.

    All three channel tables use the same status convention:
      - is_active = true  (channel record is active)
      - connection_status = 'connected'  (channel handshake completed)

    A disconnected channel has is_active = false and
    connection_status = 'disconnected', so it is excluded.
    Uses database COUNT with count="exact" on each table.
    """
    if not company_id:
        raise ValueError("Company ID is required")

    total = 0

    for table in ("telegram_channels", "wasender_channels", "whatsapp_channels"):
        response = (
            supabase
            .table(table)
            .select("id", count="exact")
            .eq("company_id", company_id)
            .eq("is_active", True)
            .eq("connection_status", "connected")
            .execute()
        )
        total += response.count or 0

    return total


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


def count_company_ai_messages(company_id, period_start, period_end):
    """Count AI-generated bot messages for a company within a time range.

    Only counts messages where:
      - ai_generated = true (set at generation time regardless of delivery)
      - sender_type = 'bot'
      - created_at >= period_start (inclusive start)
      - created_at < period_end (exclusive end)
      - The message's conversation belongs to a chatbot owned by the company

    Failed and permanently failed messages are included because they still
    consumed AI generation resources. Non-AI bot messages (e.g. system
    fallback messages with ai_generated = false) are excluded.

    Uses Supabase count="exact" with an inner join on conversations
    to scope by chatbot_id without loading individual rows.

    Returns zero when the company has no chatbots or no messages.
    """
    if not company_id:
        raise ValueError("Company ID is required")

    if not period_start or not period_end:
        raise ValueError("period_start and period_end are required")

    chatbot_ids = get_company_chatbot_ids(company_id)

    if not chatbot_ids:
        return 0

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
        .table("messages")
        .select("id,conversations!inner(chatbot_id)", count="exact")
        .eq("ai_generated", True)
        .eq("sender_type", "bot")
        .in_("conversations.chatbot_id", chatbot_ids)
        .gte("created_at", period_start_iso)
        .lt("created_at", period_end_iso)
        .execute()
    )

    return response.count or 0
