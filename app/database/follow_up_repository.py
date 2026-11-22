"""Service-role storage for the follow-up scheduler."""
from app.database import db


def _first(query):
    rows = query.limit(1).execute().data
    return rows[0] if rows else None


def _scoped(query, scope):
    return (query.eq("company_id", scope["company_id"]).eq("chatbot_id", scope["chatbot_id"])
            .eq("conversation_id", scope["conversation_id"]))


def conversation(scope):
    return _first(db.supabase.table("conversations").select(
        "*,chatbots!inner(id,company_id,followups_enabled,industry_template_published,ai_provider,model_name,temperature)"
    ).eq("id", scope["conversation_id"]).eq("chatbot_id", scope["chatbot_id"])
                  .eq("chatbots.company_id", scope["company_id"]).is_("chatbots.deleted_at", "null")
                  .neq("chatbots.status", "archived"))


def latest_customer(scope):
    return _first(db.supabase.table("messages").select(
        "id,created_at,message_text,conversations!inner(chatbot_id,chatbots!inner(company_id))"
    ).eq("conversation_id", scope["conversation_id"]).eq("conversations.chatbot_id", scope["chatbot_id"])
                  .eq("conversations.chatbots.company_id", scope["company_id"])
                  .eq("sender_type", "customer").order("id", desc=True))


def consent_status(company_id, platform, recipient):
    row = _first(db.supabase.table("marketing_consents").select("status").eq("company_id", company_id)
                 .eq("platform", platform).eq("platform_user_id", recipient))
    return row and row["status"]


def latest_lead(scope):
    query = _scoped(db.supabase.table("crm_leads").select("id,status,follow_up_won_at"), scope)
    if scope.get("won_lead_id"):
        return _first(query.eq("id", scope["won_lead_id"]))
    return _first(query.order("id", desc=True))


def schedule(payload):
    # One conversation lock serializes inbound and scheduler work in this deployment.
    active = _first(_scoped(db.supabase.table("follow_ups").select("id,kind,source_message_id"), payload)
                    .eq("status", "active"))
    if active:
        if active["kind"] == "check_in" or active["source_message_id"] >= payload["source_message_id"]:
            return
        _scoped(db.supabase.table("follow_ups").update({
            **payload, "touch_count": 0, "last_touch_at": None, "lease_token": None, "lease_expires_at": None,
        }), payload).eq("id", active["id"]).eq("status", "active").is_("won_at", "null").execute()
    else:
        db.supabase.table("follow_ups").insert(payload).execute()


def stop_on_reply(scope, at):
    _scoped(db.supabase.table("follow_ups").update({
        "status": "stopped", "stop_reason": "customer_replied", "lease_token": None,
        "lease_expires_at": None, "updated_at": at,
    }), scope).eq("status", "active").execute()


def claim_due(limit):
    return db.supabase.rpc("claim_due_follow_ups", {"p_limit": max(1, min(limit, 10))}).execute().data


def _leased_update(row, fields, status):
    return (_scoped(db.supabase.table("follow_ups").update(fields), row)
            .eq("id", row["id"]).eq("lease_token", row["lease_token"]).eq("status", status))


def reserve_send(row, at):
    # If the process dies after this fence, the provider outcome is unknowable.
    return bool(_leased_update(row, {"status": "stopped", "stop_reason": "needs_review",
                                     "updated_at": at.isoformat()}, "active")
                .gt("lease_expires_at", at.isoformat()).execute().data)


def settle(row, fields, *, reserved=False):
    return bool(_leased_update(row, {**fields, "lease_token": None, "lease_expires_at": None},
                               "stopped" if reserved else "active").execute().data)


def finish_won(row, lead_id, due_at):
    db.supabase.rpc("finish_won_follow_up", {
        "p_id": row["id"], "p_company_id": row["company_id"], "p_chatbot_id": row["chatbot_id"],
        "p_conversation_id": row["conversation_id"], "p_lease_token": row["lease_token"],
        "p_lead_id": lead_id, "p_due_at": due_at,
    }).execute()
