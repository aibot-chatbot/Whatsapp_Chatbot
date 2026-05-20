from datetime import datetime, timezone
from app.database.db import supabase


def get_or_create_conversation(
    chatbot_id: int,
    customer_phone: str,
    customer_name: str = None,
    source_channel: str = "whatsapp",
):
    now = datetime.now(timezone.utc).isoformat()

    existing = (
        supabase.table("conversations")
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .eq("customer_phone", customer_phone)
        .eq("source_channel", source_channel)
        .eq("conversation_status", "open")
        .limit(1)
        .execute()
    )

    if existing.data:
        conversation_id = existing.data[0]["id"]

        update_data = {
            "updated_at": now
        }

        if customer_name:
            update_data["customer_name"] = customer_name

        updated = (
            supabase.table("conversations")
            .update(update_data)
            .eq("id", conversation_id)
            .execute()
        )

        return updated.data[0] if updated.data else existing.data[0]

    new_conversation = {
        "chatbot_id": chatbot_id,
        "customer_phone": customer_phone,
        "customer_name": customer_name,
        "source_channel": source_channel,
        "conversation_status": "open",
        "updated_at": now,
    }

    result = supabase.table("conversations").insert(new_conversation).execute()
    return result.data[0]

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