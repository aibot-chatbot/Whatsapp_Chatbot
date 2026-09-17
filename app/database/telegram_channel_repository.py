from datetime import datetime, timezone

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
        "connection_attempted_at": datetime.now(timezone.utc).isoformat(),
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


def get_telegram_channel_by_bot_id(telegram_bot_id: str, exclude_channel_id=None):
    if not telegram_bot_id:
        return None

    result = (
        supabase
        .table("telegram_channels")
        .select("*")
        .eq("telegram_bot_id", str(telegram_bot_id))
        .eq("is_active", True)
        .limit(2 if exclude_channel_id is not None else 1)
        .execute()
    )

    rows = result.data or []
    return next(
        (row for row in rows if row.get("id") != exclude_channel_id), None
    )


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


def update_telegram_channel(channel_id: int, update_data: dict, *, expected_status=None, expected_attempt_at=None):
    query = (
        supabase
        .table("telegram_channels")
        .update(update_data)
        .eq("id", channel_id)
    )
    if expected_status is not None:
        query = query.eq("connection_status", expected_status)
    if expected_attempt_at is not None:
        query = query.eq("connection_attempted_at", expected_attempt_at)
    result = query.execute()

    return result.data[0] if result.data else None


def claim_telegram_channel_operation(channel, update_data):
    """Serialize provider changes while retaining the active identity claim."""
    if channel.get("connection_status") == "pending":
        return None
    result = (
        supabase.table("telegram_channels")
        .update({**update_data, "connection_status": "pending",
                 "connection_slot_reserved": channel.get("connection_status") == "connected"})
        .eq("id", channel["id"])
        .eq("is_active", channel["is_active"])
        .eq("connection_status", channel["connection_status"])
        .execute()
    )
    return result.data[0] if result.data else None


def activate_telegram_channel(channel_id, chatbot_id, company_id, *, expected_attempt_at=None):
    """Atomically replace this chatbot's connected channel after verification.

    No sequence of independent REST updates can safely emulate this transaction.
    Missing migration/RPC therefore raises rather than reporting false success.
    """
    from app.database.channel_lifecycle_repository import activate_channel
    return activate_channel("telegram", channel_id, chatbot_id, company_id,
                            expected_attempt_at=expected_attempt_at)


def get_telegram_channels_by_chatbot(chatbot_id: int, *, active_only=False):
    query = (
        supabase
        .table("telegram_channels")
        .select("*")
        .eq("chatbot_id", chatbot_id)
    )
    if active_only:
        query = query.eq("is_active", True).eq("connection_status", "connected")
    result = query.order("created_at", desc=True).execute()

    # Only connect/reconnect changes attempt time; retiring an old row or reading
    # its delivery state must never hide the latest attempted connection.
    return sorted(result.data or [], key=lambda row: (
        row.get("connection_attempted_at") or row.get("created_at") or "",
        row.get("id") or 0,
    ), reverse=True)
