from datetime import datetime, timezone
from app.database.db import supabase

TABLE_NAME = "bot_media_attachments"

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def get_active_attachments(chatbot_id):
    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .eq("is_active", True)
        .order("created_at", desc=False)
        .execute()
    )
    return response.data or []

def get_all_attachments(chatbot_id):
    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .order("created_at", desc=False)
        .execute()
    )
    return response.data or []

def get_attachment_by_id(attachment_id, chatbot_id):
    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("id", attachment_id)
        .eq("chatbot_id", chatbot_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None

def create_attachment(chatbot_id, company_id, data):
    payload = {
        "chatbot_id": chatbot_id,
        "company_id": company_id,
        "label": data.get("label", ""),
        "media_url": data.get("media_url", ""),
        "media_type": data.get("media_type", "image"),
        "caption": data.get("caption", ""),
        "keywords": data.get("keywords", []),
        "meta_template_name": data.get("meta_template_name", ""),
        "meta_language_code": data.get("meta_language_code", "en_US"),
        "is_active": data.get("is_active", True),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    
    response = (
        supabase
        .table(TABLE_NAME)
        .insert(payload)
        .execute()
    )
    
    rows = response.data or []
    return rows[0] if rows else None

def update_attachment(attachment_id, chatbot_id, data):
    payload = {
        "updated_at": _now_iso(),
    }
    
    # Only update fields that were provided
    valid_keys = [
        "label", "media_url", "media_type", "caption", 
        "keywords", "meta_template_name", "meta_language_code", "is_active"
    ]
    
    for key in valid_keys:
        if key in data:
            payload[key] = data[key]
            
    response = (
        supabase
        .table(TABLE_NAME)
        .update(payload)
        .eq("id", attachment_id)
        .eq("chatbot_id", chatbot_id)
        .execute()
    )
    
    rows = response.data or []
    return rows[0] if rows else None

def delete_attachment(attachment_id, chatbot_id):
    response = (
        supabase
        .table(TABLE_NAME)
        .delete()
        .eq("id", attachment_id)
        .eq("chatbot_id", chatbot_id)
        .execute()
    )
    
    return response.data
