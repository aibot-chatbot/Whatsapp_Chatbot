import logging
from datetime import datetime, timezone, timedelta
from app.database.db import supabase


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _next_retry_iso(delay_seconds: int = 60):
    return (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat()


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


def update_message_delivery_status(
    message_id: int,
    delivery_status: str,
    retry_count: int = None,
    next_retry_at: str = None,
    last_retry_at: str = None,
    first_failed_at: str = None,
    last_error: str = None,
    expected_status: str = None,
):
    update_data = {
        "delivery_status": delivery_status,
    }

    if retry_count is not None:
        update_data["retry_count"] = retry_count

    update_data["next_retry_at"] = next_retry_at

    if last_retry_at is not None:
        update_data["last_retry_at"] = last_retry_at

    if first_failed_at is not None:
        update_data["first_failed_at"] = first_failed_at

    if last_error is not None:
        update_data["last_error"] = last_error

    query = (
        supabase
        .table("messages")
        .update(update_data)
        .eq("id", message_id)
    )
    if expected_status is not None:
        query = query.eq("delivery_status", expected_status)
    result = query.execute()

    return result.data[0] if result.data else None


def mark_message_retrying(message_id: int):
    # Claim before the provider call; simultaneous workers cannot send twice.
    result = (supabase.table("messages").update({"delivery_status": "retrying", "next_retry_at": None,
                                                "last_retry_at": _now_iso()})
              .eq("id", message_id).eq("delivery_status", "failed").execute())
    return result.data[0] if result.data else None


def mark_message_sent_after_retry(message_id: int, retry_count: int):
    return update_message_delivery_status(
        message_id=message_id,
        delivery_status="sent",
        retry_count=retry_count,
        next_retry_at=None,
        last_retry_at=_now_iso(),
        last_error=None,
        expected_status="retrying",
    )


def mark_message_retry_failed(
    message_id: int,
    retry_count: int,
    error_message: str = None,
    max_retries: int = 3,
    delay_seconds: int = 60,
):
    if retry_count >= max_retries:
        return update_message_delivery_status(
            message_id=message_id,
            delivery_status="permanent_failed",
            retry_count=retry_count,
            next_retry_at=None,
            last_retry_at=_now_iso(),
            last_error=error_message,
            expected_status="retrying",
        )

    return update_message_delivery_status(
        message_id=message_id,
        delivery_status="failed",
        retry_count=retry_count,
        next_retry_at=_next_retry_iso(delay_seconds),
        last_retry_at=_now_iso(),
        last_error=error_message,
        expected_status="retrying",
    )


def get_retryable_failed_wasender_messages(limit: int = 1, max_retries: int = 3):
    """
    Get failed Wasender bot messages that are ready for automatic retry.
    Limit should stay small because WasenderAPI free trial allows 1 message per minute.
    """
    now = _now_iso()

    result = (
        supabase
        .table("messages")
        .select("*")
        .eq("sender_type", "bot")
        .eq("ai_generated", True)
        .eq("delivery_status", "failed")
        .lt("retry_count", max_retries)
        .order("created_at", desc=False)
        .limit(20)
        .execute()
    )

    rows = result.data or []
    retryable = []

    for message in rows:
        next_retry_at = message.get("next_retry_at")

        if next_retry_at and str(next_retry_at) > now:
            continue

        conversation_result = (
            supabase
            .table("conversations")
            .select("*")
            .eq("id", message.get("conversation_id"))
            .eq("source_channel", "wasender")
            .limit(1)
            .execute()
        )

        conversations = conversation_result.data or []

        if not conversations:
            continue

        message["conversation"] = conversations[0]
        retryable.append(message)

        if len(retryable) >= limit:
            break

    return retryable


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
