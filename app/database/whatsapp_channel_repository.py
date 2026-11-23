from datetime import datetime, timezone

from app.database.db import supabase


TABLE_NAME = "whatsapp_channels"


def _normalize_waba_fields(data: dict):
    normalized = dict(data or {})
    waba_id = (
        normalized.get("whatsapp_business_account_id")
        or normalized.get("waba_id")
    )

    if waba_id:
        normalized["whatsapp_business_account_id"] = waba_id
        normalized["waba_id"] = waba_id

    return normalized


def create_whatsapp_channel(
    company_id: int,
    chatbot_id: int,
    phone_number_id: str,
    whatsapp_business_account_id: str = None,
    business_id: str = None,
    access_token: str = None,
    display_phone_number: str = None,
    verified_name: str = None,
    token_type: str = None,
    token_expires_at: str = None,
    webhook_secret: str = None,
    webhook_url: str = None,
    meta_app_id: str = None,
    signup_payload: dict = None,
    connection_status: str = "pending",
    is_active: bool = True,
    last_error: str = None,
    onboarding_type: str = "standard",
):
    data = _normalize_waba_fields({
        "company_id": company_id,
        "chatbot_id": chatbot_id,
        "phone_number_id": phone_number_id,
        "whatsapp_business_account_id": whatsapp_business_account_id,
        "business_id": business_id,
        "access_token": access_token,
        "display_phone_number": display_phone_number,
        "verified_name": verified_name,
        "token_type": token_type,
        "token_expires_at": token_expires_at,
        "webhook_secret": webhook_secret,
        "webhook_url": webhook_url,
        "meta_app_id": meta_app_id,
        "signup_payload": signup_payload,
        "connection_status": connection_status,
        "is_active": is_active,
        "last_error": last_error,
        "connection_attempted_at": datetime.now(timezone.utc).isoformat(),
        "onboarding_type": onboarding_type,
    })

    result = supabase.table(TABLE_NAME).insert(data).execute()
    return result.data[0] if result.data else None


def upsert_whatsapp_channel_by_phone_number_id(phone_number_id: str, channel_data: dict):
    if not phone_number_id:
        return None

    data = _normalize_waba_fields(channel_data)
    data["phone_number_id"] = phone_number_id

    existing_channel = get_whatsapp_channel_by_phone_number_id(phone_number_id)

    if existing_channel:
        if (str(existing_channel.get("company_id")) != str(data.get("company_id"))
                or str(existing_channel.get("chatbot_id")) != str(data.get("chatbot_id"))):
            raise PermissionError("This WhatsApp number is already assigned to another chatbot.")
        return update_whatsapp_channel(existing_channel["id"], data)

    result = supabase.table(TABLE_NAME).insert(data).execute()
    return result.data[0] if result.data else None


def get_whatsapp_channel_by_phone_number_id(phone_number_id: str):
    """
    Get WhatsApp channel settings by Meta phone_number_id.
    This maps a WhatsApp number to the correct chatbot.
    """
    if not phone_number_id:
        return None

    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("phone_number_id", phone_number_id)
        .eq("is_active", True)
        .eq("connection_status", "connected")
        .limit(2)
        .execute()
    )

    rows = response.data or []

    if len(rows) != 1:
        return None

    return rows[0]


def get_registration_pin(company_id, chatbot_id, phone_number_id, waba_id):
    result = (supabase.table(TABLE_NAME).select("register_pin_encrypted")
              .eq("company_id", company_id).eq("chatbot_id", chatbot_id)
              .eq("phone_number_id", phone_number_id).eq("whatsapp_business_account_id", waba_id)
              .not_.is_("register_pin_encrypted", "null").order("id", desc=True).limit(1).execute())
    return result.data[0]["register_pin_encrypted"] if result.data else None


def get_pin_reservation(phone_number_id):
    """The pending attempt holding this number's 090 reservation, if any."""
    result = (supabase.table(TABLE_NAME).select("id,connection_status,connection_attempted_at")
              .eq("phone_number_id", phone_number_id).eq("is_active", True).eq("connection_status", "pending")
              .not_.is_("register_pin_encrypted", "null").limit(1).execute())
    return result.data[0] if result.data else None


def get_connected_whatsapp_channels_by_waba_id(waba_id: str):
    if not waba_id:
        return []
    result = (supabase.table(TABLE_NAME).select("id,company_id,chatbot_id,phone_number_id,verified_at")
              .eq("whatsapp_business_account_id", waba_id)
              .eq("is_active", True).eq("connection_status", "connected").execute())
    return result.data or []


def get_whatsapp_channels_by_chatbot(chatbot_id: int):
    """
    Get all WhatsApp channels connected to a chatbot.
    Used by Integration page to show channel status.
    """
    result = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .order("created_at", desc=True)
        .execute()
    )

    return sorted(result.data or [], key=lambda row: str(
        row.get("connection_attempted_at") or row.get("created_at") or ""), reverse=True)


def get_whatsapp_channel_by_id(channel_id: int):
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


def update_whatsapp_channel(channel_id: int, update_data: dict, expected_attempt_at=None, expected_status=None):
    update_data = _normalize_waba_fields(update_data)

    query = (
        supabase
        .table(TABLE_NAME)
        .update(update_data)
        .eq("id", channel_id)
    )
    if expected_attempt_at:
        query = query.eq("connection_attempted_at", expected_attempt_at)
    if expected_status:
        query = query.eq("connection_status", expected_status)
    result = query.execute()

    return result.data[0] if result.data else None


def disconnect_whatsapp_channel(channel_id: int):
    return update_whatsapp_channel(channel_id, {
        "is_active": False,
        "connection_status": "disconnected",
        "last_error": None,
    })


def sanitize_whatsapp_channel_for_frontend(channel: dict):
    if not channel:
        return None

    return {
        "id": channel.get("id"),
        "company_id": channel.get("company_id"),
        "chatbot_id": channel.get("chatbot_id"),
        "phone_number_id": channel.get("phone_number_id"),
        "display_phone_number": channel.get("display_phone_number"),
        "verified_name": channel.get("verified_name"),
        "whatsapp_business_account_id": (
            channel.get("whatsapp_business_account_id")
            or channel.get("waba_id")
        ),
        "waba_id": (
            channel.get("whatsapp_business_account_id")
            or channel.get("waba_id")
        ),
        "business_id": channel.get("business_id"),
        "connection_status": channel.get("connection_status"),
        "last_error": channel.get("last_error"),
        "is_active": channel.get("is_active"),
        "created_at": channel.get("created_at"),
        "updated_at": channel.get("updated_at"),
        "connected_at": channel.get("connected_at"),
        "disconnected_at": channel.get("disconnected_at"),
        "connection_attempted_at": channel.get("connection_attempted_at"),
        "verified_at": channel.get("verified_at"),
    }
