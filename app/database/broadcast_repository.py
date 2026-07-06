from datetime import datetime, timezone
from app.database.db import supabase

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def create_campaign(company_id, chatbot_id, name, channel_type, message_template):
    payload = {
        "company_id": company_id,
        "chatbot_id": chatbot_id,
        "name": name,
        "channel_type": channel_type,
        "message_template": message_template,
        "status": "draft",
        "created_at": _now_iso(),
        "updated_at": _now_iso()
    }
    response = supabase.table("broadcast_campaigns").insert(payload).execute()
    return response.data[0] if response.data else None

def get_campaigns(company_id, chatbot_id):
    response = (
        supabase.table("broadcast_campaigns")
        .select("*")
        .eq("company_id", company_id)
        .eq("chatbot_id", chatbot_id)
        .order("created_at", desc=True)
        .execute()
    )
    return response.data or []

def get_campaign_by_id(campaign_id, company_id):
    response = (
        supabase.table("broadcast_campaigns")
        .select("*")
        .eq("id", campaign_id)
        .eq("company_id", company_id)
        .execute()
    )
    return response.data[0] if response.data else None

def update_campaign_status(campaign_id, company_id, status):
    payload = {
        "status": status,
        "updated_at": _now_iso()
    }
    response = (
        supabase.table("broadcast_campaigns")
        .update(payload)
        .eq("id", campaign_id)
        .eq("company_id", company_id)
        .execute()
    )
    return response.data[0] if response.data else None

def create_broadcast_log(campaign_id, recipient_phone, status="pending", error_message=None):
    payload = {
        "campaign_id": campaign_id,
        "recipient_phone": recipient_phone,
        "status": status,
        "error_message": error_message,
        "created_at": _now_iso()
    }
    response = supabase.table("broadcast_logs").insert(payload).execute()
    return response.data[0] if response.data else None

def get_broadcast_logs_by_campaign(campaign_id):
    response = (
        supabase.table("broadcast_logs")
        .select("*")
        .eq("campaign_id", campaign_id)
        .order("created_at", desc=False)
        .execute()
    )
    return response.data or []

def update_broadcast_log_status(log_id, status, error_message=None, sent_at=None):
    payload = {
        "status": status,
        "error_message": error_message
    }
    if sent_at:
        payload["sent_at"] = sent_at
    response = (
        supabase.table("broadcast_logs")
        .update(payload)
        .eq("id", log_id)
        .execute()
    )
    return response.data[0] if response.data else None
