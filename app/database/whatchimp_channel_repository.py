import logging
from datetime import datetime, timezone

from app.database.db import supabase
from app.database.db_errors import is_unique_violation


TABLE_NAME = "whatchimp_channels"
PROCESSED_TABLE = "processed_whatchimp_messages"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def create_whatchimp_channel(company_id: int, chatbot_id: int, api_token: str, phone_number_id: str,
                             display_phone_number: str, business_name: str, webhook_secret: str, webhook_url: str):
    result = supabase.table(TABLE_NAME).insert({
        "company_id": company_id,
        "chatbot_id": chatbot_id,
        "api_token": api_token,
        "phone_number_id": phone_number_id,
        "display_phone_number": display_phone_number,
        "business_name": business_name,
        "webhook_secret": webhook_secret,
        "webhook_url": webhook_url,
        "connection_status": "pending",
        "last_error": None,
        "is_active": True,
        "updated_at": _now_iso(),
        "connection_attempted_at": _now_iso(),
    }).execute()
    return result.data[0] if result.data else None


def get_whatchimp_channel_by_secret(webhook_secret: str):
    if not webhook_secret:
        return None
    rows = (supabase.table(TABLE_NAME).select("*")
            .eq("webhook_secret", webhook_secret).eq("is_active", True).eq("connection_status", "connected")
            .limit(2).execute()).data or []
    return rows[0] if len(rows) == 1 else None


def get_whatchimp_channel_by_id(channel_id: int):
    if not channel_id:
        return None
    rows = supabase.table(TABLE_NAME).select("*").eq("id", channel_id).limit(1).execute().data or []
    return rows[0] if rows else None


def get_whatchimp_channels_by_chatbot(chatbot_id: int):
    rows = (supabase.table(TABLE_NAME).select("*").eq("chatbot_id", chatbot_id)
            .order("created_at", desc=True).execute()).data or []
    return sorted(rows, key=lambda row: str(row.get("connection_attempted_at") or row.get("created_at") or ""),
                  reverse=True)


def update_whatchimp_channel(channel_id: int, update_data: dict, expected_attempt_at=None, expected_status=None):
    query = supabase.table(TABLE_NAME).update({**update_data, "updated_at": _now_iso()}).eq("id", channel_id)
    if expected_attempt_at:
        query = query.eq("connection_attempted_at", expected_attempt_at)
    if expected_status:
        query = query.eq("connection_status", expected_status)
    result = query.execute()
    return result.data[0] if result.data else None


def disconnect_whatchimp_channel(channel_id: int):
    # A disconnected channel never sends again, so its customer's key is not kept.
    return update_whatchimp_channel(channel_id, {"is_active": False, "connection_status": "disconnected",
                                                 "api_token": None})


def mark_whatchimp_inbound(channel_id: int):
    """Best effort: proves to the owner that the link pasted into WhatChimp works."""
    try:
        supabase.table(TABLE_NAME).update({"last_inbound_at": _now_iso()}).eq("id", channel_id).execute()
    except Exception as error:
        logging.warning("Could not record WhatChimp inbound time (%s)", type(error).__name__)


def claim_whatchimp_message(channel_id, message_id):
    """The insert is the claim: a duplicate webhook delivery hits the UNIQUE and returns False."""
    if not channel_id or not message_id:
        raise ValueError("Message identity is required")
    try:
        supabase.table(PROCESSED_TABLE).insert({"whatchimp_channel_id": channel_id, "message_id": str(message_id)}).execute()
        return True
    except Exception as error:
        if is_unique_violation(error):
            return False
        raise


def release_whatchimp_message_claim(channel_id, message_id):
    try:
        (supabase.table(PROCESSED_TABLE).delete()
         .eq("whatchimp_channel_id", channel_id).eq("message_id", str(message_id)).execute())
    except Exception:
        logging.error("Could not release message claim; manual review required")
