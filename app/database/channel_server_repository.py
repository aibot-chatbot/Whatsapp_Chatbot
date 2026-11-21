"""Service-role storage for linked devices and atomic inbound message claims."""
from datetime import datetime, timezone

from app.database.db import supabase
from app.database.db_errors import is_unique_violation


def now():
    return datetime.now(timezone.utc).isoformat()


def _first(result):
    return next(iter(result.data or []), None)


def _channels():
    return supabase.table("channel_server_channels")


def create(values):
    return _first(_channels().insert(values).execute())


def get(channel_id):
    return _first(_channels().select("*").eq("id", channel_id).limit(1).execute())


def list_channels(chatbot_id):
    return (_channels().select("*").eq("chatbot_id", chatbot_id)
            .order("is_active", desc=True).order("id", desc=True).execute().data or [])


def active_session(name):
    return _first(_channels().select("*").eq("session_name", name).eq("is_active", True).limit(1).execute())


def update(channel, changes):
    # A late status callback must never reactivate an owner-disconnected row.
    return _first(_channels().update({**changes, "updated_at": now()})
                  .eq("id", channel["id"]).eq("company_id", channel["company_id"])
                  .eq("connection_status", channel["connection_status"])
                  .eq("updated_at", channel["updated_at"]).execute())


def claim(message_id):
    try:
        supabase.table("processed_channel_server_messages").insert({"message_id": message_id}).execute()
    except Exception as error:
        if is_unique_violation(error):
            return False
        raise
    return True


def release(message_id):
    supabase.table("processed_channel_server_messages").delete().eq("message_id", message_id).execute()
