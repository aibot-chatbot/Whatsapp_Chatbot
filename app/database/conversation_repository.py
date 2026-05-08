from datetime import datetime, timezone
from app.database.db import supabase


def get_or_create_conversation(chatbot_id: int, customer_phone: str, customer_name: str = None):
    now = datetime.now(timezone.utc).isoformat()

    existing = (
        supabase.table("conversations")
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .eq("customer_phone", customer_phone)
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
        "source_channel": "whatsapp",
        "conversation_status": "open",
        "updated_at": now,
    }

    result = supabase.table("conversations").insert(new_conversation).execute()
    return result.data[0]