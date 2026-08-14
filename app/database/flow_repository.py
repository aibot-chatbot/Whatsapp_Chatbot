import logging
from datetime import datetime, timezone

from app.database.db import supabase


ACTIVE_FLOW_STATUSES = ("active", "published")


def get_flow_for_chatbot(company_id: int, chatbot_id: int):
    result = (
        supabase.table("flows")
        .select("*")
        .eq("company_id", company_id)
        .eq("chatbot_id", chatbot_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def upsert_flow(company_id: int, chatbot_id: int, name: str, flow_data: dict, action: str = "draft"):
    existing = get_flow_for_chatbot(company_id, chatbot_id)
    now = datetime.now(timezone.utc).isoformat()

    payload = {
        "company_id": company_id,
        "chatbot_id": chatbot_id,
        "name": name,
        "status": "active" if action == "publish" else (existing or {}).get("status", "draft"),
        "draft_data": flow_data,
        "flow_data": flow_data,
        "updated_at": now,
    }

    if action == "publish":
        payload["published_data"] = flow_data
        payload["published_at"] = now

    if existing:
        result = supabase.table("flows").update(payload).eq("id", existing["id"]).execute()
    else:
        result = supabase.table("flows").insert(payload).execute()

    rows = result.data or []
    return rows[0] if rows else None


def get_active_published_flow(company_id: int, chatbot_id: int):
    try:
        result = (
            supabase.table("flows")
            .select("*")
            .eq("company_id", company_id)
            .eq("chatbot_id", chatbot_id)
            .in_("status", ACTIVE_FLOW_STATUSES)
            .order("published_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = [row for row in (result.data or []) if row.get("published_data")]
        if rows:
            return rows[0]
    except Exception as exc:
        logging.warning(
            "V3 active flow lookup unavailable for company %s chatbot %s; trying legacy flow lookup: %s",
            company_id,
            chatbot_id,
            exc,
        )

    try:
        legacy_result = (
            supabase.table("flows")
            .select("*")
            .eq("company_id", company_id)
            .eq("chatbot_id", chatbot_id)
            .in_("status", ACTIVE_FLOW_STATUSES)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        legacy_rows = legacy_result.data or []
        return legacy_rows[0] if legacy_rows else None
    except Exception as exc:
        logging.warning(
            "Legacy active flow lookup failed for company %s chatbot %s: %s",
            company_id,
            chatbot_id,
            exc,
        )
        return None


def get_open_conversation_for_flow(chatbot_id: int, customer_id: str, source_channel: str = None):
    try:
        query = (
            supabase.table("conversations")
            .select("id, active_flow_id, current_node_id, workflow_variables")
            .eq("chatbot_id", chatbot_id)
            .eq("conversation_status", "open")
        )

        if source_channel:
            query = query.eq("source_channel", source_channel)

        phone_result = query.eq("customer_phone", customer_id).limit(1).execute()
        rows = phone_result.data or []
        if rows:
            return rows[0]

        platform_query = (
            supabase.table("conversations")
            .select("id, active_flow_id, current_node_id, workflow_variables")
            .eq("chatbot_id", chatbot_id)
            .eq("platform_user_id", customer_id)
            .eq("conversation_status", "open")
        )

        if source_channel:
            platform_query = platform_query.eq("source_channel", source_channel)

        platform_result = platform_query.limit(1).execute()
        platform_rows = platform_result.data or []
        return platform_rows[0] if platform_rows else None
    except Exception as exc:
        logging.warning(
            "Flow conversation state lookup unavailable for chatbot %s; continuing statelessly: %s",
            chatbot_id,
            exc,
        )
        return None


def update_conversation_flow_state(conversation_id: int, active_flow_id, current_node_id):
    payload = {
        "active_flow_id": active_flow_id,
        "current_node_id": current_node_id,
    }
    result = supabase.table("conversations").update(payload).eq("id", conversation_id).execute()
    rows = result.data or []
    return rows[0] if rows else None


def insert_execution_log(company_id, chatbot_id, conversation_id, flow_id, node_id, node_type, status="success", error_message=None):
    payload = {
        "company_id": company_id,
        "chatbot_id": chatbot_id,
        "conversation_id": conversation_id,
        "flow_id": flow_id,
        "node_id": str(node_id),
        "node_type": node_type,
        "status": status,
        "error_message": error_message,
    }
    return supabase.table("execution_logs").insert(payload).execute()
