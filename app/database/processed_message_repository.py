import logging
from app.database.db_errors import is_unique_violation
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

def claim_processed_message(chatbot_id, platform_message_id):
    if not chatbot_id or not platform_message_id:
        raise ValueError("Message identity is required")
    try:
        supabase.table(TABLE_NAME).insert({"chatbot_id": chatbot_id, "platform_message_id": str(platform_message_id)}).execute()
        return True
    except Exception as error:
        if is_unique_violation(error):
            return False
        raise


def release_processed_message_claim(chatbot_id, platform_message_id):
    try:
        supabase.table(TABLE_NAME).delete().eq("chatbot_id", chatbot_id).eq("platform_message_id", str(platform_message_id)).execute()
    except Exception:
        logging.error("Could not release message claim; manual review required")
