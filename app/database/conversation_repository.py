from datetime import datetime, timezone
from app.database.db import supabase
from app.database.billing_usage_repository import get_company_chatbot_ids


def get_or_create_conversation(
    chatbot_id: int,
    customer_phone: str,
    customer_name: str = None,
    source_channel: str = "whatsapp",
):
    now = datetime.now(timezone.utc).isoformat()

    if source_channel == "telegram":
        return get_or_create_platform_conversation(
            chatbot_id=chatbot_id,
            platform_user_id=str(customer_phone),
            customer_name=customer_name,
            source_channel=source_channel,
            customer_phone=None,
        )

    def fetch_existing_open_conversation():
        existing_result = (
            supabase.table("conversations")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("customer_phone", customer_phone)
            .eq("source_channel", source_channel)
            .eq("conversation_status", "open")
            .limit(1)
            .execute()
        )

        rows = existing_result.data or []
        return rows[0] if rows else None

    existing = fetch_existing_open_conversation()

    if existing:
        update_data = {
            "updated_at": now
        }

        if customer_name:
            update_data["customer_name"] = customer_name

        updated = (
            supabase.table("conversations")
            .update(update_data)
            .eq("id", existing["id"])
            .execute()
        )

        return updated.data[0] if updated.data else existing

    new_conversation = {
        "chatbot_id": chatbot_id,
        "customer_phone": customer_phone,
        "customer_name": customer_name,
        "source_channel": source_channel,
        "conversation_status": "open",
        "updated_at": now,
    }

    try:
        result = supabase.table("conversations").insert(new_conversation).execute()
        return result.data[0]

    except Exception:
        # If two webhooks arrive at almost the same time,
        # the unique index may block the second insert.
        # In that case, fetch the conversation created by the first request.
        existing_after_conflict = fetch_existing_open_conversation()

        if existing_after_conflict:
            return existing_after_conflict

        raise


def get_or_create_platform_conversation(
    chatbot_id: int,
    platform_user_id: str,
    customer_name: str = None,
    source_channel: str = "telegram",
    customer_phone: str = None,
):
    """
    Get or create conversation using platform user ID.

    For Telegram:
    - platform_user_id = Telegram chat/user ID
    - customer_phone = real phone number only after user shares contact
    """
    now = datetime.now(timezone.utc).isoformat()

    def fetch_existing_by_platform_id():
        existing_result = (
            supabase.table("conversations")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("platform_user_id", platform_user_id)
            .eq("source_channel", source_channel)
            .eq("conversation_status", "open")
            .limit(1)
            .execute()
        )

        rows = existing_result.data or []
        return rows[0] if rows else None

    def fetch_legacy_telegram_conversation():
        """
        Old Telegram records saved Telegram ID inside customer_phone.
        This prevents duplicate conversations after we add platform_user_id.
        """
        legacy_result = (
            supabase.table("conversations")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("customer_phone", platform_user_id)
            .eq("source_channel", source_channel)
            .eq("conversation_status", "open")
            .limit(1)
            .execute()
        )

        rows = legacy_result.data or []
        return rows[0] if rows else None

    existing = fetch_existing_by_platform_id() or fetch_legacy_telegram_conversation()

    if existing:
        update_data = {
            "platform_user_id": platform_user_id,
            "updated_at": now,
        }

        if customer_name:
            update_data["customer_name"] = customer_name

        if customer_phone:
            update_data["customer_phone"] = customer_phone
        elif existing.get("customer_phone") == platform_user_id:
            # Clear old wrong Telegram ID from customer_phone
            update_data["customer_phone"] = None

        updated = (
            supabase.table("conversations")
            .update(update_data)
            .eq("id", existing["id"])
            .execute()
        )

        return updated.data[0] if updated.data else existing

    new_conversation = {
        "chatbot_id": chatbot_id,
        "platform_user_id": platform_user_id,
        "customer_phone": customer_phone,
        "customer_name": customer_name,
        "source_channel": source_channel,
        "conversation_status": "open",
        "updated_at": now,
    }

    result = supabase.table("conversations").insert(new_conversation).execute()
    return result.data[0]


def update_conversation_phone_by_platform(
    chatbot_id: int,
    platform_user_id: str,
    customer_phone: str,
    customer_name: str = None,
    source_channel: str = "telegram",
):
    """
    Save real phone number after Telegram user clicks Share Phone Number.
    """
    now = datetime.now(timezone.utc).isoformat()

    update_data = {
        "customer_phone": customer_phone,
        "platform_user_id": platform_user_id,
        "updated_at": now,
    }

    if customer_name:
        update_data["customer_name"] = customer_name

    result = (
        supabase.table("conversations")
        .update(update_data)
        .eq("chatbot_id", chatbot_id)
        .eq("platform_user_id", platform_user_id)
        .eq("source_channel", source_channel)
        .eq("conversation_status", "open")
        .execute()
    )

    rows = result.data or []

    if rows:
        return rows[0]

    return get_or_create_platform_conversation(
        chatbot_id=chatbot_id,
        platform_user_id=platform_user_id,
        customer_name=customer_name,
        source_channel=source_channel,
        customer_phone=customer_phone,
    )


def get_conversations_by_bot(chatbot_id: int):
    """
    Fetches all conversations associated with a specific chatbot,
    ordered by the most recently updated.
    """
    result = (
        supabase.table("conversations")
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .order("updated_at", desc=True)
        .execute()
    )
    return result.data


def _count_messages_by_conversation_ids(conversation_ids):
    """
    Batched message count for a set of conversations: one query total, not
    one per conversation. Returns {conversation_id: count}.
    """
    if not conversation_ids:
        return {}

    result = (
        supabase.table("messages")
        .select("conversation_id")
        .in_("conversation_id", conversation_ids)
        .execute()
    )

    counts = {}
    for row in (result.data or []):
        conversation_id = row.get("conversation_id")
        counts[conversation_id] = counts.get(conversation_id, 0) + 1
    return counts


def get_conversations_for_company(company_id: int):
    """
    Company-scoped conversation list: every conversation across the caller's
    non-archived, non-deleted chatbots (reuses get_company_chatbot_ids so the
    "which bots does this company own" rule stays in one place).

    Each row is annotated with chatbot_id (already present via select("*")),
    bot_name and message_count. Only three queries total regardless of how
    many conversations or chatbots are involved -- conversations, chatbots,
    messages -- so this stays O(1) queries, not O(n).
    """
    chatbot_ids = get_company_chatbot_ids(company_id)
    if not chatbot_ids:
        return []

    conversations_result = (
        supabase.table("conversations")
        .select("*")
        .in_("chatbot_id", chatbot_ids)
        .order("updated_at", desc=True)
        .execute()
    )
    conversations = conversations_result.data or []
    if not conversations:
        return []

    bots_result = (
        supabase.table("chatbots")
        .select("id,bot_name")
        .in_("id", chatbot_ids)
        .execute()
    )
    bot_names = {row["id"]: row.get("bot_name") for row in (bots_result.data or [])}

    conversation_ids = [c["id"] for c in conversations if c.get("id") is not None]
    message_counts = _count_messages_by_conversation_ids(conversation_ids)

    for conversation in conversations:
        conversation["bot_name"] = bot_names.get(conversation.get("chatbot_id"))
        conversation["message_count"] = message_counts.get(conversation.get("id"), 0)

    return conversations


def get_conversation_by_id_and_chatbot(conversation_id: int, chatbot_id: int):
    result = (
        supabase.table("conversations")
        .select("*")
        .eq("id", conversation_id)
        .eq("chatbot_id", chatbot_id)
        .limit(1)
        .execute()
    )

    rows = result.data or []
    return rows[0] if rows else None
