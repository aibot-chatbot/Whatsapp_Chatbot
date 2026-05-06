from app.database.db import supabase

TABLE_NAME = "processed_webhook_messages"


def is_processed(chatbot_id, platform_message_id):
    response = (
        supabase
        .table(TABLE_NAME)
        .select("id")
        .eq("chatbot_id", chatbot_id)
        .eq("platform_message_id", platform_message_id)
        .limit(1)
        .execute()
    )

    rows = response.data or []
    return len(rows) > 0


def save_processed(chatbot_id, platform_message_id):
    response = (
        supabase
        .table(TABLE_NAME)
        .insert({
            "chatbot_id": chatbot_id,
            "platform_message_id": platform_message_id,
        })
        .execute()
    )

    rows = response.data or []

    if not rows:
        raise ValueError("Failed to save processed webhook message")

    return rows[0]