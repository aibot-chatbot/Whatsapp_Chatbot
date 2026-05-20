from app.database.db import supabase


def create_telegram_channel(
    company_id: int,
    chatbot_id: int,
    bot_token: str,
    bot_username: str = None,
    telegram_bot_id: str = None,
    webhook_secret: str = None,
    webhook_url: str = None,
):
    data = {
        "company_id": company_id,
        "chatbot_id": chatbot_id,
        "bot_token": bot_token,
        "bot_username": bot_username,
        "telegram_bot_id": telegram_bot_id,
        "webhook_secret": webhook_secret,
        "webhook_url": webhook_url,
        "connection_status": "pending",
        "is_active": True,
    }

    result = supabase.table("telegram_channels").insert(data).execute()
    return result.data[0] if result.data else None


def get_telegram_channel_by_secret(webhook_secret: str):
    if not webhook_secret:
        return None

    result = (
        supabase
        .table("telegram_channels")
        .select("*")
        .eq("webhook_secret", webhook_secret)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )

    rows = result.data or []
    return rows[0] if rows else None


def get_telegram_channel_by_bot_id(telegram_bot_id: str):
    if not telegram_bot_id:
        return None

    result = (
        supabase
        .table("telegram_channels")
        .select("*")
        .eq("telegram_bot_id", str(telegram_bot_id))
        .eq("is_active", True)
        .limit(1)
        .execute()
    )

    rows = result.data or []
    return rows[0] if rows else None


def get_telegram_channel_by_id(channel_id: int):
    if not channel_id:
        return None

    result = (
        supabase
        .table("telegram_channels")
        .select("*")
        .eq("id", channel_id)
        .limit(1)
        .execute()
    )

    rows = result.data or []
    return rows[0] if rows else None


def update_telegram_channel(channel_id: int, update_data: dict):
    result = (
        supabase
        .table("telegram_channels")
        .update(update_data)
        .eq("id", channel_id)
        .execute()
    )

    return result.data[0] if result.data else None


def get_telegram_channels_by_chatbot(chatbot_id: int):
    result = (
        supabase
        .table("telegram_channels")
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .order("created_at", desc=True)
        .execute()
    )

    return result.data or []