from app.database.db import supabase

TABLE_NAME = "processed_telegram_updates"


def is_telegram_update_processed(telegram_channel_id: int, update_id: str):
    """
    Check whether this Telegram update has already been processed.
    This prevents duplicate bot replies if Telegram retries the webhook.
    """
    if not telegram_channel_id or update_id is None:
        return False

    response = (
        supabase
        .table(TABLE_NAME)
        .select("id")
        .eq("telegram_channel_id", telegram_channel_id)
        .eq("update_id", str(update_id))
        .limit(1)
        .execute()
    )

    rows = response.data or []
    return len(rows) > 0


def save_processed_telegram_update(telegram_channel_id: int, update_id: str):
    """
    Save processed Telegram update ID after successful handling.
    """
    if not telegram_channel_id or update_id is None:
        raise ValueError("telegram_channel_id and update_id are required")

    response = (
        supabase
        .table(TABLE_NAME)
        .insert({
            "telegram_channel_id": telegram_channel_id,
            "update_id": str(update_id),
        })
        .execute()
    )

    rows = response.data or []

    if not rows:
        raise ValueError("Failed to save processed Telegram update")

    return rows[0]