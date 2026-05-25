from datetime import datetime, timezone
from app.database.db import supabase


def get_or_create_conversation(
    chatbot_id: int,
    customer_phone: str,
    customer_name: str = None,
    source_channel: str = "whatsapp",
):
    now = datetime.now(timezone.utc).isoformat()

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