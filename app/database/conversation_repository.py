from datetime import datetime, timezone
from app.database.db import supabase
from app.database.billing_usage_repository import get_company_chatbot_ids


def _scope_origin(query, channel_id, provider_id):
    if (channel_id is None) != (provider_id is None):
        raise ValueError("Both channel and provider identity are required")
    if channel_id is None:
        return query.is_("source_channel_id", "null")
    if isinstance(channel_id, bool) or not isinstance(channel_id, int) or channel_id <= 0 or not str(provider_id).strip():
        raise ValueError("A valid channel and provider identity are required")
    return query.eq("source_channel_id", channel_id).eq("source_provider_id", str(provider_id))


def get_or_create_conversation(
    chatbot_id: int,
    customer_phone: str,
    customer_name: str = None,
    source_channel: str = "whatsapp",
    source_channel_id: int = None,
    source_provider_id: str = None,
):
    now = datetime.now(timezone.utc).isoformat()

    if source_channel == "telegram":
        return get_or_create_platform_conversation(
            chatbot_id=chatbot_id,
            platform_user_id=str(customer_phone),
            customer_name=customer_name,
            source_channel=source_channel,
            customer_phone=None,
            source_channel_id=source_channel_id,
            source_provider_id=source_provider_id,
        )

    def fetch_existing_open_conversation():
        return find_open_conversation(chatbot_id=chatbot_id, customer_phone=customer_phone,
                                      source_channel=source_channel, source_channel_id=source_channel_id,
                                      source_provider_id=source_provider_id)

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

    if source_channel_id is not None:
        new_conversation.update(source_channel_id=source_channel_id, source_provider_id=str(source_provider_id))

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


def find_open_conversation(chatbot_id: int, customer_phone: str, source_channel: str,
                           source_channel_id: int = None, source_provider_id: str = None):
    """The open conversation for this customer on this channel, without creating one."""
    query = (
        supabase.table("conversations")
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .eq("customer_phone", customer_phone)
        .eq("source_channel", source_channel)
        .eq("conversation_status", "open")
    )
    existing_result = _scope_origin(query, source_channel_id, source_provider_id).limit(1).execute()

    rows = existing_result.data or []
    return rows[0] if rows else None


def find_widget_conversation(chatbot_id: int, session_id: str):
    """Resolve an existing web capability without creating or adopting a chat."""
    result = (
        supabase.table("conversations")
        .select("id,chatbot_id,source_channel,platform_user_id,source_channel_id")
        .eq("chatbot_id", chatbot_id)
        .eq("source_channel", "web")
        .eq("platform_user_id", session_id)
        .is_("source_channel_id", "null")
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    if not isinstance(result.data, list):
        raise RuntimeError("Widget conversation lookup unavailable")
    return result.data[0] if result.data else None


def get_or_create_platform_conversation(
    chatbot_id: int,
    platform_user_id: str,
    customer_name: str = None,
    source_channel: str = "telegram",
    customer_phone: str = None,
    source_channel_id: int = None,
    source_provider_id: str = None,
):
    """
    Get or create conversation using the platform conversation/destination ID.

    For Telegram:
    - platform_user_id = Telegram chat ID, independent of the message author
    - customer_phone = real phone number shared in a private chat only
    """
    now = datetime.now(timezone.utc).isoformat()

    def fetch_existing_by_platform_id():
        query = (
            supabase.table("conversations")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("platform_user_id", platform_user_id)
            .eq("source_channel", source_channel)
            .eq("conversation_status", "open")
        )
        existing_result = _scope_origin(query, source_channel_id, source_provider_id).limit(1).execute()

        rows = existing_result.data or []
        return rows[0] if rows else None

    def fetch_legacy_telegram_conversation():
        """
        Old Telegram records saved Telegram ID inside customer_phone.
        This prevents duplicate conversations after we add platform_user_id.
        """
        query = (
            supabase.table("conversations")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("customer_phone", platform_user_id)
            .eq("source_channel", source_channel)
            .eq("conversation_status", "open")
        )
        existing_result = _scope_origin(query, source_channel_id, source_provider_id).limit(1).execute()

        rows = existing_result.data or []
        return rows[0] if rows else None

    existing = fetch_existing_by_platform_id()
    # New bound conversations have an exact destination. A profile phone or
    # legacy sender ID must never be adopted as that destination's history.
    if not existing and source_channel_id is None:
        existing = fetch_legacy_telegram_conversation()

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

    if source_channel_id is not None:
        new_conversation.update(source_channel_id=source_channel_id, source_provider_id=str(source_provider_id))
    try:
        result = supabase.table("conversations").insert(new_conversation).execute()
        return result.data[0]
    except Exception:
        existing = fetch_existing_by_platform_id()
        if existing:
            return existing
        raise


def update_conversation_phone_by_platform(
    chatbot_id: int,
    platform_user_id: str,
    customer_phone: str,
    customer_name: str = None,
    source_channel: str = "telegram",
    source_channel_id: int = None,
    source_provider_id: str = None,
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

    query = (
        supabase.table("conversations")
        .update(update_data)
        .eq("chatbot_id", chatbot_id)
        .eq("platform_user_id", platform_user_id)
        .eq("source_channel", source_channel)
        .eq("conversation_status", "open")
    )

    result = _scope_origin(query, source_channel_id, source_provider_id).execute()

    rows = result.data or []

    if rows:
        return rows[0]

    return get_or_create_platform_conversation(
        chatbot_id=chatbot_id,
        platform_user_id=platform_user_id,
        customer_name=customer_name,
        source_channel=source_channel,
        customer_phone=customer_phone,
        source_channel_id=source_channel_id,
        source_provider_id=source_provider_id,
    )


def get_conversations_by_bot(chatbot_id: int):
    """
    Fetches all conversations associated with a specific chatbot,
    ordered by the most recently updated, annotated with bot_name and
    message_count exactly like the company-wide list.
    """
    result = (
        supabase.table("conversations")
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .order("updated_at", desc=True)
        .execute()
    )
    return _annotate_conversations(result.data or [], [chatbot_id])


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
    return _annotate_conversations(conversations_result.data or [], chatbot_ids)


def _annotate_conversations(conversations, chatbot_ids):
    """Adds bot_name and message_count in two queries total, never one per row."""
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


_ANY_STAGE = object()


def save_customer_needs(conversation_id: int, chatbot_id: int, needs: dict, *, expected_stage=_ANY_STAGE) -> bool:
    """Store the customer needs card (data/077). Scoped by chatbot too, so a wrong id can
    never write into another tenant's conversation. True when a row was updated."""
    query = (
        supabase.table("conversations")
        .update({"customer_needs": needs})
        .eq("id", conversation_id)
        .eq("chatbot_id", chatbot_id)
    )
    # Two replies can start from the same card. Only the winning stage change may notify staff.
    if expected_stage is None:
        query = query.is_("customer_needs->>stage", "null")
    elif expected_stage is not _ANY_STAGE:
        query = query.eq("customer_needs->>stage", expected_stage)
    return bool(query.execute().data)


def reset_testbot_conversation(chatbot_id: int, company_id: int, session_id: str):
    """Finish only the Test Lab session; retain its transcript for review."""
    from app.database.agent_action_repository import ESCALATION_INTENTS
    from app.services.conversation_delivery_lock import conversation_delivery_lock

    result = (
        supabase.table("conversations")
        .select("id")
        .eq("chatbot_id", chatbot_id)
        .eq("customer_phone", session_id)
        .eq("source_channel", "web")
        .eq("conversation_status", "open")
        .execute()
    )
    for conversation in result.data or []:
        conversation_id = conversation["id"]
        with conversation_delivery_lock(conversation_id):
            (
                supabase.table("agent_actions")
                .update({"status": "resolved"})
                .eq("conversation_id", conversation_id)
                .eq("chatbot_id", chatbot_id)
                .eq("company_id", company_id)
                .eq("status", "detected")
                .in_("intent", ESCALATION_INTENTS)
                .execute()
            )
            closed = (
                supabase.table("conversations")
                .update({
                    "conversation_status": "closed",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", conversation_id)
                .eq("chatbot_id", chatbot_id)
                .eq("customer_phone", session_id)
                .eq("source_channel", "web")
                .execute()
            )
            if not closed.data:
                raise RuntimeError("Test conversation reset was not saved")
