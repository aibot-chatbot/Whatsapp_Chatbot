"""web_widget_repository.py — Supabase access for chatbot website widgets.

One row per chatbot. The `public_key` column is the customer-facing
identifier used in embed snippets so the internal chatbot_id is never
exposed on third-party websites.
"""

from datetime import datetime, timezone

from app.database.db import supabase

TABLE_NAME = "chatbot_web_widgets"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_widget_by_chatbot_id(chatbot_id, company_id=None):
    query = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("chatbot_id", chatbot_id)
    )

    if company_id is not None:
        query = query.eq("company_id", company_id)

    response = query.limit(1).execute()
    rows = response.data or []
    return rows[0] if rows else None


def get_widget_by_public_key(public_key):
    """Public lookup used by unauthenticated widget endpoints."""
    if not public_key:
        return None

    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("public_key", public_key)
        .limit(1)
        .execute()
    )

    rows = response.data or []
    return rows[0] if rows else None


def create_widget(chatbot_id, company_id, public_key, defaults=None):
    payload = {
        "chatbot_id": chatbot_id,
        "company_id": company_id,
        "public_key": public_key,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }

    if defaults:
        payload.update(defaults)

    response = (
        supabase
        .table(TABLE_NAME)
        .insert(payload)
        .execute()
    )

    rows = response.data or []
    return rows[0] if rows else None


def update_widget(chatbot_id, company_id, data):
    payload = dict(data)
    payload["updated_at"] = _now_iso()

    response = (
        supabase
        .table(TABLE_NAME)
        .update(payload)
        .eq("chatbot_id", chatbot_id)
        .eq("company_id", company_id)
        .execute()
    )

    rows = response.data or []
    return rows[0] if rows else None


def delete_widget(chatbot_id, company_id):
    response = (
        supabase
        .table(TABLE_NAME)
        .delete()
        .eq("chatbot_id", chatbot_id)
        .eq("company_id", company_id)
        .execute()
    )

    return bool(response.data)
