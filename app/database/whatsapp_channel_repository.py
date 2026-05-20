from app.database.db import supabase


def get_whatsapp_channel_by_phone_number_id(phone_number_id: str):
    """
    Get WhatsApp channel settings by Meta phone_number_id.
    This maps a WhatsApp number to the correct chatbot.
    """
    if not phone_number_id:
        return None

    response = (
        supabase
        .table("whatsapp_channels")
        .select("*")
        .eq("phone_number_id", phone_number_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )

    rows = response.data or []

    if not rows:
        return None

    return rows[0]


def get_whatsapp_channels_by_chatbot(chatbot_id: int):
    """
    Get all WhatsApp channels connected to a chatbot.
    Used by Integration page to show channel status.
    """
    result = (
        supabase
        .table("whatsapp_channels")
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .order("created_at", desc=True)
        .execute()
    )

    return result.data or []


def get_whatsapp_channel_by_id(channel_id: int):
    if not channel_id:
        return None

    result = (
        supabase
        .table("whatsapp_channels")
        .select("*")
        .eq("id", channel_id)
        .limit(1)
        .execute()
    )

    rows = result.data or []
    return rows[0] if rows else None


def update_whatsapp_channel(channel_id: int, update_data: dict):
    result = (
        supabase
        .table("whatsapp_channels")
        .update(update_data)
        .eq("id", channel_id)
        .execute()
    )

    return result.data[0] if result.data else None