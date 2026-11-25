"""Service-role storage for the follow-up scheduler."""
from app.database import db


def _first(query):
    rows = query.limit(1).execute().data
    return rows[0] if rows else None


def _scoped(query, scope):
    return (query.eq("company_id", scope["company_id"]).eq("chatbot_id", scope["chatbot_id"])
            .eq("conversation_id", scope["conversation_id"]))


def _connected(table, fields, company_id, chatbot_id):
    return (db.supabase.table(table).select(fields).eq("company_id", company_id)
            .eq("chatbot_id", chatbot_id).eq("is_active", True).eq("connection_status", "connected"))


def connected_whatsapp_accounts(company_id, chatbot_id):
    rows = _connected("whatsapp_channels", "whatsapp_business_account_id,waba_id", company_id, chatbot_id).execute().data
    wabas = {waba for row in rows if (waba := row.get("whatsapp_business_account_id") or row.get("waba_id"))}
    return bool(rows), wabas


def has_connected_linked_whatsapp(company_id, chatbot_id):
    return bool(_first(_connected("channel_server_channels", "id", company_id, chatbot_id)))


def has_connected_follow_up_channel(company_id, chatbot_id, *, has_whatsapp=None, has_linked=None):
    if has_whatsapp is None:
        has_whatsapp, _ = connected_whatsapp_accounts(company_id, chatbot_id)
    if has_whatsapp:
        return True
    if has_linked is None:
        has_linked = has_connected_linked_whatsapp(company_id, chatbot_id)
    return has_linked or bool(_first(_connected("telegram_channels", "id", company_id, chatbot_id)))


def deployed_persona(company_id, chatbot_id, profile_name):
    if not profile_name:
        return None
    return _first(db.supabase.table("bot_configs").select("tone,response_style,chatbots!inner(company_id)")
                  .eq("chatbot_id", chatbot_id).eq("chatbots.company_id", company_id)
                  .eq("profile_name", profile_name))


def recent_follow_ups(company_id, chatbot_id):
    return (db.supabase.table("follow_ups")
            .select("conversation_id,mode,kind,touch_count,status,stop_reason,last_touch_at")
            .eq("company_id", company_id).eq("chatbot_id", chatbot_id)
            .order("updated_at", desc=True).order("id", desc=True).limit(20).execute().data)


def conversation(scope):
    return _first(db.supabase.table("conversations").select(
        "*,chatbots!inner(id,company_id,followups_enabled,followups_enabled_at,"
        "followup_template_id,industry_template_published,ai_provider,model_name,temperature)"
    ).eq("id", scope["conversation_id"]).eq("chatbot_id", scope["chatbot_id"])
                  .eq("chatbots.company_id", scope["company_id"]).is_("chatbots.deleted_at", "null")
                  .neq("chatbots.status", "archived"))


def latest_customer(scope):
    return _first(db.supabase.table("messages").select(
        "id,created_at,message_text,conversations!inner(chatbot_id,chatbots!inner(company_id))"
    ).eq("conversation_id", scope["conversation_id"]).eq("conversations.chatbot_id", scope["chatbot_id"])
                  .eq("conversations.chatbots.company_id", scope["company_id"])
                  .eq("sender_type", "customer").order("created_at", desc=True).order("id", desc=True))


def _pages(build_query):
    rows = []
    while True:
        batch = build_query().range(len(rows), len(rows) + 499).execute().data
        if not batch:
            return rows
        rows.extend(batch)


def receipts(company_id, chatbot_id, start, at):
    return _pages(lambda: db.supabase.table("follow_up_receipts").select("conversation_id,sent_at,withdrawn_at")
                  .eq("company_id", company_id).eq("chatbot_id", chatbot_id)
                  .gte("sent_at", start.isoformat()).lte("sent_at", at.isoformat())
                  .order("sent_at").order("source_id").order("ordinal"))


def window_outcomes(company_id, chatbot_id, start, at):
    return _pages(lambda: db.supabase.table("follow_ups")
                  .select("conversation_id,stop_reason,kind,won_at,created_at,updated_at,touch_count")
                  .eq("company_id", company_id).eq("chatbot_id", chatbot_id)
                  .gte("updated_at", start.isoformat()).lte("updated_at", at.isoformat()).order("id"))


def auto_stop(bot, at, counts):
    query = (db.supabase.table("chatbots").update({"followups_enabled": False,
             "followups_auto_stopped_at": at.isoformat(), "followups_auto_stop_counts": counts})
             .eq("company_id", bot["company_id"]).eq("id", bot["id"]).eq("followups_enabled", True))
    epoch = bot.get("followups_enabled_at")
    query = query.eq("followups_enabled_at", epoch) if epoch else query.is_("followups_enabled_at", "null")
    return bool(query.execute().data)


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
