from app.database.db import supabase


TABLE_NAME = "processed_wasender_messages"


def is_wasender_message_processed(wasender_channel_id: int, message_id: str):
    if not wasender_channel_id or not message_id:
        return False

    result = (
        supabase
        .table(TABLE_NAME)
        .select("id")
        .eq("wasender_channel_id", wasender_channel_id)
        .eq("message_id", str(message_id))
        .limit(1)
        .execute()
    )

    rows = result.data or []
    return len(rows) > 0


def save_processed_wasender_message(wasender_channel_id: int, message_id: str):
    if not wasender_channel_id or not message_id:
        return None

    data = {
        "wasender_channel_id": wasender_channel_id,
        "message_id": str(message_id),
    }

    result = supabase.table(TABLE_NAME).insert(data).execute()
    return result.data[0] if result.data else None