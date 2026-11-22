import logging
from app.database.db import supabase


def save_message(
    conversation_id: int,
    sender_type: str,
    message_text: str = None,
    message_type: str = "text",
    platform_message_id: str = None,
    delivery_status: str = "sent",
    ai_generated: bool = False,
    retry_count: int = 0,
    next_retry_at: str = None,
    last_retry_at: str = None,
    first_failed_at: str = None,
    last_error: str = None,
    actor_user_id: int = None,
):
    message_data = {
        "conversation_id": conversation_id,
        "sender_type": sender_type,
        "message_type": message_type,
        "message_text": message_text,
        "platform_message_id": platform_message_id,
        "delivery_status": delivery_status,
        "ai_generated": ai_generated,
        "retry_count": retry_count,
        "next_retry_at": next_retry_at,
        "last_retry_at": last_retry_at,
        "first_failed_at": first_failed_at,
        "last_error": last_error,
    }
    if actor_user_id is not None:
        message_data["actor_user_id"] = actor_user_id

    result = supabase.table("messages").insert(message_data).execute()
    return result.data[0] if result.data else None


def get_widget_human_messages(conversation_id: int, after_id: int, limit: int = 51):
    """Only customer-visible staff text; database failures must remain failures."""
    result = (
        supabase.table("messages")
        .select("id,message_text,created_at,sender_type")
        .eq("conversation_id", conversation_id)
        .eq("sender_type", "human")
        .eq("ai_generated", False)
        .eq("message_type", "text")
        .eq("delivery_status", "sent")
        .gt("id", after_id)
        .order("id")
        .limit(limit)
        .execute()
    )
    if not isinstance(result.data, list):
        raise RuntimeError("Widget staff messages unavailable")
    return result.data


def get_messages_by_conversation(conversation_id: int):
    """
    Fetches all messages for a specific conversation,
    ordered by creation time ascending (chronological).
    """
    result = (
        supabase.table("messages")
        .select("*")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data


def latest_staff_reply_at(conversation_id, chatbot_id, *, web=False):
    query = (supabase.table("messages").select("created_at,conversations!inner(chatbot_id)")
             .eq("conversation_id", conversation_id).eq("conversations.chatbot_id", chatbot_id)
             .eq("ai_generated", False))
    # The widget records delivered staff messages as human; older channels record them as bot.
    query = query.in_("sender_type", ["bot", "human"]) if web else query.eq("sender_type", "bot")
    rows = query.order("created_at", desc=True).limit(1).execute().data
    return rows[0]["created_at"] if rows else None


def get_latest_bot_message_text(conversation_id: int):
    """Text of the most recent bot message in a conversation, or None."""
    result = (
        supabase.table("messages")
        .select("message_text")
        .eq("conversation_id", conversation_id)
        .eq("sender_type", "bot")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0].get("message_text") if rows else None


def count_messages_by_conversation(conversation_id: int, sender_type: str = None):
    """
    Count messages in a conversation without transferring the rows.

    Used by the website widget to enforce a per-session message cap so an
    embedded chatbot cannot be abused to burn a company's AI credit.
    """
    query = (
        supabase.table("messages")
        .select("id", count="exact")
        .eq("conversation_id", conversation_id)
    )

    if sender_type:
        query = query.eq("sender_type", sender_type)

    result = query.limit(1).execute()
    return result.count or 0


def get_messages_by_conversation_and_chatbot(conversation_id: int, chatbot_id: int):
    """
    Fetch messages only when the conversation belongs to the requested chatbot.
    Returns None when the conversation is missing or belongs to a different chatbot.
    """
    messages_result = (
        supabase
        .table("messages")
        .select("*,conversations!inner(chatbot_id)")
        .eq("conversation_id", conversation_id)
        .eq("conversations.chatbot_id", chatbot_id)
        .order("created_at", desc=False)
        .execute()
    )

    messages = messages_result.data or []
    if messages:
        for message in messages:
            message.pop("conversations", None)
        return messages

    conversation_result = (
        supabase
        .table("conversations")
        .select("id")
        .eq("id", conversation_id)
        .eq("chatbot_id", chatbot_id)
        .limit(1)
        .execute()
    )

    if not (conversation_result.data or []):
        return None

    return []


def get_message_health_by_chatbot(chatbot_id: int):
    """
    Summarize delivery health for dashboard readiness.
    All queries are scoped through the parent conversation's chatbot_id.
    """
    statuses = ["failed", "retrying", "permanent_failed"]
    counts = {}

    for status in statuses:
        try:
            result = (
                supabase
                .table("messages")
                .select("id,conversations!inner(chatbot_id)", count="exact")
                .eq("sender_type", "bot")
                .eq("delivery_status", status)
                .eq("conversations.chatbot_id", chatbot_id)
                .execute()
            )
            counts[status] = result.count if result.count is not None else len(result.data or [])
        except Exception as e:
            logging.error(
                "Failed to count %s messages for chatbot_id=%s: %s",
                status,
                chatbot_id,
                e,
            )
            counts[status] = 0

    last_error_rows = []
    for status in statuses:
        try:
            result = (
                supabase
                .table("messages")
                .select("last_error,created_at,conversations!inner(chatbot_id)")
                .eq("sender_type", "bot")
                .eq("delivery_status", status)
                .eq("conversations.chatbot_id", chatbot_id)
                .order("created_at", desc=True)
                .limit(5)
                .execute()
            )
            last_error_rows.extend(result.data or [])
        except Exception as e:
            logging.error(
                "Failed to load %s message errors for chatbot_id=%s: %s",
                status,
                chatbot_id,
                e,
            )
    last_error_rows.sort(key=lambda row: row.get("created_at") or "", reverse=True)
    last_error = next(
        (row.get("last_error") for row in last_error_rows if row.get("last_error")),
        None,
    )

    try:
        last_success_result = (
            supabase
            .table("messages")
            .select("created_at,conversations!inner(chatbot_id)")
            .eq("sender_type", "bot")
            .eq("delivery_status", "sent")
            .eq("conversations.chatbot_id", chatbot_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        last_success_rows = last_success_result.data or []
    except Exception as e:
        logging.error(
            "Failed to load last successful bot message for chatbot_id=%s: %s",
            chatbot_id,
            e,
        )
        last_success_rows = []
    last_success_at = last_success_rows[0].get("created_at") if last_success_rows else None

    try:
        last_message_result = (
            supabase
            .table("messages")
            .select("created_at,conversations!inner(chatbot_id)")
            .eq("conversations.chatbot_id", chatbot_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        last_message_rows = last_message_result.data or []
    except Exception as e:
        logging.error(
            "Failed to load last message activity for chatbot_id=%s: %s",
            chatbot_id,
            e,
        )
        last_message_rows = []
    last_message_at = last_message_rows[0].get("created_at") if last_message_rows else None

    return {
        "failed": counts["failed"],
        "retrying": counts["retrying"],
        "permanent_failed": counts["permanent_failed"],
        "last_error": last_error,
        "last_success_at": last_success_at,
        "last_message_at": last_message_at,
    }
