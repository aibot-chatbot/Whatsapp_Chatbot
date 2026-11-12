from contextlib import nullcontext

from app.database.db import supabase
from app.services.conversation_delivery_lock import conversation_delivery_lock
from app.services.turn_cache import cached


ESCALATION_INTENTS = ["handoff_request", "complaint", "knowledge_gap"]
SAFE_AGENT_ACTION_FIELDS = (
    "id,company_id,chatbot_id,conversation_id,message_id,intent,"
    "action_type,confidence,status,reason,created_at"
)


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

    # Actions without a conversation cannot pause a delivery destination.
    with conversation_delivery_lock(conversation_id) if conversation_id is not None else nullcontext():
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

def get_pending_escalations(chatbot_id, company_id, limit=50, conversation_id=None):
    query = (
        supabase
        .table("agent_actions")
        .select(SAFE_AGENT_ACTION_FIELDS)
        .eq("chatbot_id", chatbot_id)
        .eq("company_id", company_id)
        .eq("status", "detected")
        .in_("intent", ESCALATION_INTENTS)
    )
    if conversation_id is not None:
        query = query.eq("conversation_id", conversation_id)
    action_result = (
        query
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
        .select("id,chatbot_id,customer_name,source_channel")
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
    conversation_id = action.get("conversation_id")
    with conversation_delivery_lock(conversation_id) if conversation_id is not None else nullcontext():
        result = supabase.rpc("resolve_conversation_escalation", {
            "p_action_id": action_id, "p_chatbot_id": chatbot_id, "p_company_id": company_id,
        }).execute()
    data = result.data
    if not isinstance(data, dict) or not isinstance(data.get("resolved_action"), dict):
        return None, False
    action = dict(data["resolved_action"])
    action["_ai_resumed"] = data.get("ai_resumed") is True
    return action, data.get("changed") is True


def get_agent_actions_by_conversation_and_chatbot(conversation_id, chatbot_id, company_id):
    """
    Fetch agent_actions rows for a conversation, tenant-scoped exactly like
    get_messages_by_conversation_and_chatbot (message_repository.py): the
    Both the action's chatbot/company keys and the conversation join are
    checked, and a not-found conversation is distinguished from "no actions
    yet" by a second scoped lookup.

    The select list deliberately excludes `payload` -- it may carry raw
    model output that must not reach the dashboard.

    Returns None when the conversation is missing or belongs to a different
    chatbot, [] when it belongs to this chatbot but has no agent actions.
    """
    actions_result = (
        supabase
        .table("agent_actions")
        .select(
            "message_id,intent,confidence,action_type,reason,status,"
            "conversations!inner(chatbot_id)"
        )
        .eq("conversation_id", conversation_id)
        .eq("chatbot_id", chatbot_id)
        .eq("company_id", company_id)
        .eq("conversations.chatbot_id", chatbot_id)
        .order("created_at", desc=False)
        .execute()
    )

    actions = actions_result.data or []
    if actions:
        for action in actions:
            action.pop("conversations", None)
        return actions

    conversation_result = (
        supabase
        .table("conversations")
        .select("id")
        .eq("id", conversation_id)
        .eq("chatbot_id", chatbot_id)
        .limit(1)
        .execute()
    )

    if not (conversation_result.data or []):
        return None

    return []


def is_pending_handoff_action(action_id, conversation_id, chatbot_id, company_id):
    result = (supabase.table("agent_actions").select("id")
              .eq("id", action_id).eq("conversation_id", conversation_id)
              .eq("chatbot_id", chatbot_id).eq("company_id", company_id)
              .eq("intent", "handoff_request").eq("status", "detected")
              .limit(1).execute())
    return bool(result.data)


def get_platform_content_flags(*, company_id=None, category=None, days=7, limit=200, now=None):
    """Recent flags across Clients; select metadata only and cap every response at 200."""
    from datetime import datetime, timedelta, timezone

    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
        raise ValueError("days must be between 1 and 30")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    now = now or datetime.now(timezone.utc)
    query = (
        supabase.table("agent_actions")
        .select("created_at,company_id,chatbot_id,conversation_id,"
                "filter:payload->content_flag->filter,mode:payload->content_flag->>mode,"
                "category:payload->content_flag->>category,rule:payload->content_flag->>rule,"
                "source:payload->content_flag->>source")
        .eq("intent", "unknown")
        .not_.is_("payload->content_flag", "null")
        .gte("created_at", (now - timedelta(days=days)).isoformat())
        .lte("created_at", now.isoformat())
    )
    if company_id is not None:
        query = query.eq("company_id", company_id)
    if category is not None:
        query = query.eq("payload->content_flag->>category", category)
    return (query.order("created_at", desc=True).order("id", desc=True)
            .limit(limit).execute().data or [])


def iter_platform_content_flag_counts(*, since, until, company_id=None):
    """Page only counting metadata, independently of the recent-list cap and filters."""
    offset = 0
    while True:
        query = (
            supabase.table("agent_actions")
            .select("company_id,category:payload->content_flag->>category,"
                    "mode:payload->content_flag->>mode")
            .eq("intent", "unknown")
            .not_.is_("payload->content_flag", "null")
            .gte("created_at", since).lte("created_at", until)
        )
        if company_id is not None:
            query = query.eq("company_id", company_id)
        rows = (query.order("created_at", desc=True).order("id", desc=True)
                .range(offset, offset + 199).execute().data or [])
        yield from rows
        if len(rows) < 200:
            return
        offset += 200


def get_recent_content_flags(conversation_id, chatbot_id=None, *, since):
    """The safety-filter payloads recorded for one conversation since an ISO time, newest first.

    Flags are agent_actions rows with intent "unknown" whose payload holds a content_flag
    (data/027 rejects a new intent); only the payload is read, never message text.
    """
    query = (
        supabase.table("agent_actions")
        .select("payload,created_at")
        .eq("conversation_id", conversation_id)
        .eq("intent", "unknown")
        .gte("created_at", since)
        # Ordinary agent decisions use intent "unknown" too: filter flag rows before the limit.
        .not_.is_("payload->content_flag", "null")
    )
    if chatbot_id is not None:
        query = query.eq("chatbot_id", chatbot_id)
    rows = query.order("created_at", desc=True).limit(50).execute().data or []
    return [row["payload"] for row in rows if _is_flag_payload(row.get("payload"))]


def _is_flag_payload(payload):
    return isinstance(payload, dict) and isinstance(payload.get("content_flag"), dict)


def get_content_flags_since(*, since):
    """Every Client's safety-filter flags since an ISO time: company_id and payload only."""
    rows = (
        supabase.table("agent_actions")
        .select("company_id,payload")
        .eq("intent", "unknown")
        .gte("created_at", since)
        .not_.is_("payload->content_flag", "null")
        .limit(5000)
        .execute()
        .data
        or []
    )
    return [row for row in rows if _is_flag_payload(row.get("payload"))]


def get_company_content_flags(company_id, *, since):
    """The safety-filter payloads recorded for one Client since an ISO time (payloads only)."""
    rows = (
        supabase.table("agent_actions")
        .select("payload")
        .eq("company_id", company_id)
        .eq("intent", "unknown")
        .gte("created_at", since)
        .not_.is_("payload->content_flag", "null")
        .limit(500)
        .execute()
        .data
        or []
    )
    return [row["payload"] for row in rows if _is_flag_payload(row.get("payload"))]


def is_conversation_escalated(conversation_id, chatbot_id=None, conversation=None):
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
    if result.data:
        return True
    if not isinstance(conversation, dict) or not conversation.get("source_channel_id"):
        return False
    # Unknown legacy origin is never adopted, but an unresolved human handoff
    # for this customer still pauses automatic replies until explicitly resolved.
    customers = []
    if conversation.get("platform_user_id"):
        customers.extend([("platform_user_id", conversation["platform_user_id"]),
                          ("customer_phone", conversation["platform_user_id"])])
    if conversation.get("customer_phone"):
        customers.append(("customer_phone", conversation["customer_phone"]))
    for field, value in customers:
        # Which conversations are legacy is fixed for the turn - current code
        # always stamps source_channel_id - so only the id list is memoised.
        # Whether one of them has an unresolved handoff is re-read every time,
        # because a human can take over while the model is still generating.
        ids = cached(
            ("legacy_conversation_ids", chatbot_id, conversation["source_channel"], field, value),
            lambda: [row["id"] for row in (
                supabase.table("conversations").select("id").eq("chatbot_id", chatbot_id)
                .eq("source_channel", conversation["source_channel"]).eq("conversation_status", "open")
                .is_("source_channel_id", "null").eq(field, value).execute().data or [])],
        )
        if ids:
            pending = (supabase.table("agent_actions").select("id").eq("chatbot_id", chatbot_id)
                       .in_("conversation_id", ids).eq("status", "detected")
                       .in_("intent", ESCALATION_INTENTS).limit(1).execute())
            if pending.data:
                return True
    return False
