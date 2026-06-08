from app.database.db import supabase


def save_agent_action(
    chatbot_id,
    company_id=None,
    conversation_id=None,
    message_id=None,
    intent="unknown",
    action_type="none",
    confidence=None,
    reason="",
    payload=None,
):
    action_data = {
        "company_id": company_id,
        "chatbot_id": chatbot_id,
        "conversation_id": conversation_id,
        "message_id": message_id,
        "action_type": action_type or "none",
        "intent": intent or "unknown",
        "status": "detected",
        "confidence": confidence,
        "reason": (reason or "")[:300],
        "payload": payload or {},
    }

    result = supabase.table("agent_actions").insert(action_data).execute()
    return result.data[0] if result.data else None


def get_agent_insights_by_chatbot(chatbot_id, limit=10):
    actionable_intents = [
        "lead_interest",
        "handoff_request",
        "complaint",
        "knowledge_gap",
    ]
    summary = {}

    for intent in actionable_intents:
        result = (
            supabase
            .table("agent_actions")
            .select("id", count="exact")
            .eq("chatbot_id", chatbot_id)
            .eq("intent", intent)
            .execute()
        )
        summary[intent] = result.count or 0

    recent_result = (
        supabase
        .table("agent_actions")
        .select("intent,action_type,confidence,created_at")
        .eq("chatbot_id", chatbot_id)
        .in_("intent", actionable_intents)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )

    return {
        "summary": summary,
        "recent": recent_result.data or [],
    }
