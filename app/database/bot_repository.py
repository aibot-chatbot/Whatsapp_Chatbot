from datetime import datetime, timezone

from app.database.db import supabase

TABLE_NAME = "chatbots"
ACTIVE_STATUS = "active"
ARCHIVED_STATUS = "archived"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_all_bots(company_id):
    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("company_id", company_id)
        .is_("deleted_at", "null")
        .neq("status", ARCHIVED_STATUS)
        .order("created_at", desc=True)
        .execute()
    )

    return response.data or []


def get_archived_bots(company_id):
    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("company_id", company_id)
        .eq("status", ARCHIVED_STATUS)
        .order("deleted_at", desc=True)
        .execute()
    )

    return response.data or []


def get_bot_by_id(bot_id, company_id=None, include_archived=False):
    query = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("id", bot_id)
    )

    if company_id is not None:
        query = query.eq("company_id", company_id)

    if not include_archived:
        query = query.is_("deleted_at", "null").neq("status", ARCHIVED_STATUS)

    response = query.limit(1).execute()

    rows = response.data or []
    return rows[0] if rows else None


def create_bot(data, company_id):
    payload = {
        "company_id": company_id,
        "bot_name": data.get("bot_name"),
        "bot_description": data.get("bot_description", ""),
        "language": data.get("language", "English"),
        "tone": data.get("tone", "Friendly"),
        "welcome_message": data.get("welcome_message", ""),
        "fallback_message": data.get("fallback_message", ""),
        "is_active": data.get("is_active", True),
        "status": data.get("status", ACTIVE_STATUS),
        "deleted_at": None,
        "ai_provider": data.get("ai_provider", "deepseek"),
        "model_name": data.get("model_name", "deepseek-v4-flash"),
        "temperature": data.get("temperature", 0.7),
        # Message style settings — default all to True (enabled)
        "telegram_buttons_enabled": data.get("telegram_buttons_enabled", True),
        "telegram_markdown_enabled": data.get("telegram_markdown_enabled", True),
        "whatsapp_buttons_enabled": data.get("whatsapp_buttons_enabled", True),
        "whatsapp_markdown_enabled": data.get("whatsapp_markdown_enabled", True),
        "welcome_menu_labels": data.get("welcome_menu_labels", []),
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


def update_bot(bot_id, data, company_id):
    payload = dict(data)
    payload["updated_at"] = _now_iso()

    response = (
        supabase
        .table(TABLE_NAME)
        .update(payload)
        .eq("id", bot_id)
        .eq("company_id", company_id)
        .execute()
    )

    rows = response.data or []
    return rows[0] if rows else None


def archive_bot(bot_id, company_id):
    now = _now_iso()
    response = (
        supabase
        .table(TABLE_NAME)
        .update({
            "status": ARCHIVED_STATUS,
            "is_active": False,
            "deleted_at": now,
            "updated_at": now,
        })
        .eq("id", bot_id)
        .eq("company_id", company_id)
        .is_("deleted_at", "null")
        .neq("status", ARCHIVED_STATUS)
        .execute()
    )

    rows = response.data or []
    return rows[0] if rows else None


def restore_bot(bot_id, company_id):
    now = _now_iso()
    response = (
        supabase
        .table(TABLE_NAME)
        .update({
            "status": ACTIVE_STATUS,
            "is_active": True,
            "deleted_at": None,
            "updated_at": now,
        })
        .eq("id", bot_id)
        .eq("company_id", company_id)
        .eq("status", ARCHIVED_STATUS)
        .execute()
    )

    rows = response.data or []
    return rows[0] if rows else None


def permanently_delete_archived_chatbot_rpc(bot_id, company_id, confirm_bot_name):
    response = supabase.rpc(
        "permanently_delete_archived_chatbot",
        {
            "p_chatbot_id": bot_id,
            "p_company_id": company_id,
            "p_confirm_bot_name": confirm_bot_name,
        },
    ).execute()

    data = response.data

    if isinstance(data, list):
        return data[0] if data else None

    return data
