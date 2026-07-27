from app.database.db import supabase


ESCALATION_INTENTS = ["handoff_request", "complaint", "knowledge_gap"]


def _is_positive_integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


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
    if not _is_positive_integer(company_id):
        raise ValueError("company_id is required to save an agent action")

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

def get_pending_escalations(chatbot_id, company_id, limit=50):
    # Fetch escalations
    action_result = (
        supabase
        .table("agent_actions")
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .eq("company_id", company_id)
        .eq("status", "detected")
        .in_("intent", ESCALATION_INTENTS)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    actions = action_result.data or []
    
    if not actions:
        return []
        
    # Fetch corresponding conversations manually to be safe
    conv_ids = [a["conversation_id"] for a in actions if a.get("conversation_id")]
    if not conv_ids:
        return actions
        
    conv_result = (
        supabase
        .table("conversations")
        .select("*")
        .in_("id", conv_ids)
        .eq("chatbot_id", chatbot_id)
        .execute()
    )
    convs = {
        conversation["id"]: conversation
        for conversation in (conv_result.data or [])
        if conversation.get("chatbot_id") == chatbot_id
    }
    
    for action in actions:
        action["conversation"] = convs.get(action.get("conversation_id"))
        
    return actions

def _get_escalation_by_id(action_id, chatbot_id, company_id):
    result = (
        supabase
        .table("agent_actions")
        .select("*")
        .eq("id", action_id)
        .eq("chatbot_id", chatbot_id)
        .eq("company_id", company_id)
        .in_("intent", ESCALATION_INTENTS)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def resolve_escalation(action_id, chatbot_id, company_id):
    action = _get_escalation_by_id(action_id, chatbot_id, company_id)
    if not action:
        return None, False

    if action.get("status") == "resolved":
        return action, False

    if action.get("status") != "detected":
        return None, False

    result = (
        supabase
        .table("agent_actions")
        .update({"status": "resolved"})
        .eq("id", action_id)
        .eq("chatbot_id", chatbot_id)
        .eq("company_id", company_id)
        .eq("status", "detected")
        .in_("intent", ESCALATION_INTENTS)
        .execute()
    )
    rows = result.data or []
    if rows:
        return rows[0], True

    # Another request may have resolved the same action after our initial read.
    current = _get_escalation_by_id(action_id, chatbot_id, company_id)
    if current and current.get("status") == "resolved":
        return current, False

    return None, False


def is_conversation_escalated(conversation_id, chatbot_id=None):
    query = (
        supabase
        .table("agent_actions")
        .select("id")
        .eq("conversation_id", conversation_id)
    )
    if chatbot_id is not None:
        query = query.eq("chatbot_id", chatbot_id)

    result = (
        query
        .eq("status", "detected")
        .in_("intent", ESCALATION_INTENTS)
        .limit(1)
        .execute()
    )
    return bool(result.data)
