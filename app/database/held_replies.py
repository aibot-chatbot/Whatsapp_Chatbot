"""Private staff reviews. Every access to an existing draft binds all three tenant identifiers."""

from datetime import datetime, timezone

from app.database.db import supabase


def create_held_reply(*, company_id, chatbot_id, conversation_id, draft, category, subtype):
    supabase.table("held_replies").insert({
        "company_id": company_id, "chatbot_id": chatbot_id, "conversation_id": conversation_id,
        "draft": draft, "category": category, "subtype": subtype,
    }, returning="minimal").execute()


def get_conversation(conversation_id, company_id):
    rows = (supabase.table("conversations").select("*,chatbots!inner(company_id)")
            .eq("id", conversation_id).eq("chatbots.company_id", company_id).limit(1).execute().data)
    return rows[0] if rows else None


def _scope(query, company_id, chatbot_id, conversation_id):
    return query.eq("company_id", company_id).eq("chatbot_id", chatbot_id).eq("conversation_id", conversation_id)


def list_pending(company_id, chatbot_id, conversation_id):
    query = supabase.table("held_replies").select("id,draft,category,subtype,created_at,resolved_by")
    return (_scope(query, company_id, chatbot_id, conversation_id).eq("status", "pending")
            .order("created_at", desc=True).order("id", desc=True).execute().data)


def _take_pending(company_id, chatbot_id, conversation_id, held_id, changes):
    query = supabase.table("held_replies").update(changes)
    rows = (_scope(query, company_id, chatbot_id, conversation_id).eq("id", held_id)
            .eq("status", "pending").is_("resolved_by", "null").execute().data)
    return rows[0] if rows else None


def claim(company_id, chatbot_id, conversation_id, held_id, actor_id):
    """Reserve before calling the provider. A concurrent worker cannot claim the same pending row."""
    return _take_pending(company_id, chatbot_id, conversation_id, held_id, {"resolved_by": actor_id})


def discard(company_id, chatbot_id, conversation_id, held_id, actor_id):
    return bool(_take_pending(company_id, chatbot_id, conversation_id, held_id, {
        "status": "discarded", "resolved_by": actor_id, "resolved_at": datetime.now(timezone.utc).isoformat(),
    }))


def exists(company_id, chatbot_id, conversation_id, held_id):
    query = supabase.table("held_replies").select("id")
    return bool(_scope(query, company_id, chatbot_id, conversation_id).eq("id", held_id).execute().data)


def _update_claim(company_id, chatbot_id, conversation_id, held_id, actor_id, changes):
    query = supabase.table("held_replies").update(changes)
    return bool(_scope(query, company_id, chatbot_id, conversation_id).eq("id", held_id)
                .eq("status", "pending").eq("resolved_by", actor_id).execute().data)


def finish(company_id, chatbot_id, conversation_id, held_id, actor_id, status):
    return _update_claim(company_id, chatbot_id, conversation_id, held_id, actor_id, {
        "status": status, "resolved_at": datetime.now(timezone.utc).isoformat(),
    })


def release(company_id, chatbot_id, conversation_id, held_id, actor_id):
    """Only a known refusal before dispatch makes retry safe."""
    return _update_claim(company_id, chatbot_id, conversation_id, held_id, actor_id, {"resolved_by": None})
