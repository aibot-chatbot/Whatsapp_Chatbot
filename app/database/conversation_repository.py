from app.database.db import supabase


def get_or_create_conversation(chatbot_id: int, customer_phone: str, customer_name: str = None):
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
        return existing.data[0]

    new_conversation = {
        "chatbot_id": chatbot_id,
        "customer_phone": customer_phone,
        "customer_name": customer_name,
        "source_channel": "whatsapp",
        "conversation_status": "open",
    }

    result = supabase.table("conversations").insert(new_conversation).execute()
    return result.data[0]