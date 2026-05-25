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

    result = supabase.table("messages").insert(message_data).execute()
    return result.data[0] if result.data else None


def update_message_delivery_status(
    message_id: int,
    delivery_status: str,
    retry_count: int = None,
    next_retry_at: str = None,
    last_retry_at: str = None,
    first_failed_at: str = None,
    last_error: str = None,
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

    result = (
        supabase
        .table("messages")
        .update(update_data)
        .eq("id", message_id)
        .execute()
    )

    return result.data[0] if result.data else None


def mark_message_retrying(message_id: int):
    return update_message_delivery_status(
        message_id=message_id,
        delivery_status="retrying",
        next_retry_at=None,
        last_retry_at=_now_iso(),
    )


def mark_message_sent_after_retry(message_id: int, retry_count: int):
    return update_message_delivery_status(
        message_id=message_id,
        delivery_status="sent",
        retry_count=retry_count,
        next_retry_at=None,
        last_retry_at=_now_iso(),
        last_error=None,
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
        )

    return update_message_delivery_status(
        message_id=message_id,
        delivery_status="failed",
        retry_count=retry_count,
        next_retry_at=_next_retry_iso(delay_seconds),
        last_retry_at=_now_iso(),
        last_error=error_message,
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