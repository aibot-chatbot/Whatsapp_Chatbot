from app.database.db import supabase


def save_message(
    conversation_id: int,
    sender_type: str,
    message_text: str = None,
    message_type: str = "text",
    platform_message_id: str = None,
    delivery_status: str = "sent",
    ai_generated: bool = False,
):
    message_data = {
        "conversation_id": conversation_id,
        "sender_type": sender_type,
        "message_type": message_type,
        "message_text": message_text,
        "platform_message_id": platform_message_id,
        "delivery_status": delivery_status,
        "ai_generated": ai_generated,
    }

    result = supabase.table("messages").insert(message_data).execute()
    return result.data[0]