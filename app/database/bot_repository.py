from datetime import datetime, timezone

from app.database.db import supabase

TABLE_NAME = "chatbots"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_all_bots(company_id):
    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("company_id", company_id)
        .order("created_at", desc=True)
        .execute()
    )

    return response.data or []


def get_bot_by_id(bot_id, company_id=None):
    query = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("id", bot_id)
    )

    if company_id is not None:
        query = query.eq("company_id", company_id)

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
        "ai_provider": data.get("ai_provider", "deepseek"),
        "model_name": data.get("model_name", "deepseek-v4-flash"),
        "temperature": data.get("temperature", 0.7),
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


def delete_bot(bot_id, company_id):
    response = (
        supabase
        .table(TABLE_NAME)
        .delete()
        .eq("id", bot_id)
        .eq("company_id", company_id)
        .execute()
    )

    return response.data or []
