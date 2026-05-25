from datetime import datetime, timezone
from app.database.db import supabase


TABLE_NAME = "wasender_channels"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def create_wasender_channel(
    company_id: int,
    chatbot_id: int,
    api_key: str,
    phone_number: str = None,
    session_id: str = None,
    session_name: str = None,
    webhook_secret: str = None,
    webhook_url: str = None,
):
    data = {
        "company_id": company_id,
        "chatbot_id": chatbot_id,
        "api_key": api_key,
        "phone_number": phone_number,
        "session_id": session_id,
        "session_name": session_name,
        "webhook_secret": webhook_secret,
        "webhook_url": webhook_url,
        "connection_status": "pending",
        "last_error": None,
        "is_active": True,
        "updated_at": _now_iso(),
    }

    result = supabase.table(TABLE_NAME).insert(data).execute()
    return result.data[0] if result.data else None


def get_wasender_channel_by_secret(webhook_secret: str):
    if not webhook_secret:
        return None

    result = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("webhook_secret", webhook_secret)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )

    rows = result.data or []
    return rows[0] if rows else None


def get_wasender_channel_by_id(channel_id: int):
    if not channel_id:
        return None

    result = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("id", channel_id)
        .limit(1)
        .execute()
    )

    rows = result.data or []
    return rows[0] if rows else None


def get_wasender_channels_by_chatbot(chatbot_id: int):
    result = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .order("created_at", desc=True)
        .execute()
    )

    return result.data or []


def update_wasender_channel(channel_id: int, update_data: dict):
    update_data["updated_at"] = _now_iso()

    result = (
        supabase
        .table(TABLE_NAME)
        .update(update_data)
        .eq("id", channel_id)
        .execute()
    )

    return result.data[0] if result.data else None


def disconnect_wasender_channel(channel_id: int):
    return update_wasender_channel(channel_id, {
        "is_active": False,
        "connection_status": "disconnected",
    })  