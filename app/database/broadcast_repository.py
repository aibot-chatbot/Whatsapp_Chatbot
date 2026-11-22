from datetime import datetime, timezone
from app.database.db import supabase

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def create_campaign(company_id, chatbot_id, name, channel_type, message_template, meta_template_name="", meta_language_code="en_US", media_attachment_id=None):
    payload = {
        "company_id": company_id,
        "chatbot_id": chatbot_id,
        "name": name,
        "channel_type": channel_type,
        "message_template": message_template,
        "meta_template_name": meta_template_name,
        "meta_language_code": meta_language_code,
        "media_attachment_id": media_attachment_id,
        "status": "draft",
        "created_at": _now_iso(),
        "updated_at": _now_iso()
    }
    response = supabase.table("broadcast_campaigns").insert(payload).execute()
    return response.data[0] if response.data else None

def get_campaigns(company_id, chatbot_id):
    response = (
        supabase.table("broadcast_campaigns")
        .select("*")
        .eq("company_id", company_id)
        .eq("chatbot_id", chatbot_id)
        .order("created_at", desc=True)
        .execute()
    )
    return response.data or []

def get_campaign_by_id(campaign_id, company_id):
    response = (
        supabase.table("broadcast_campaigns")
        .select("*")
        .eq("id", campaign_id)
        .eq("company_id", company_id)
        .execute()
    )
    return response.data[0] if response.data else None

def update_campaign_status(campaign_id, company_id, status):
    payload = {
        "status": status,
        "updated_at": _now_iso()
    }
    response = (
        supabase.table("broadcast_campaigns")
        .update(payload)
        .eq("id", campaign_id)
        .eq("company_id", company_id)
        .execute()
    )
    return response.data[0] if response.data else None

def create_broadcast_log(campaign_id, recipient_phone, status="pending", error_message=None):
    payload = {
        "campaign_id": campaign_id,
        "recipient_phone": recipient_phone,
        "status": status,
        "error_message": error_message,
        "created_at": _now_iso()
    }
    response = supabase.table("broadcast_logs").insert(payload).execute()
    return response.data[0] if response.data else None

def get_broadcast_logs_by_campaign(campaign_id):
    response = (
        supabase.table("broadcast_logs")
        .select("*")
        .eq("campaign_id", campaign_id)
        .order("created_at", desc=False)
        .execute()
    )
    return response.data or []

def update_broadcast_log_status(log_id, status, error_message=None, sent_at=None):
    payload = {
        "status": status,
        "error_message": error_message
    }
    if sent_at:
        payload["sent_at"] = sent_at
    response = (
        supabase.table("broadcast_logs")
        .update(payload)
        .eq("id", log_id)
        .execute()
    )
    return response.data[0] if response.data else None


def update_campaign(campaign_id, company_id, fields):
    """Partial update of a campaign. Callers decide which statuses may be edited."""
    if not fields:
        return get_campaign_by_id(campaign_id, company_id)
    payload = dict(fields)
    payload["updated_at"] = _now_iso()
    response = (
        supabase.table("broadcast_campaigns")
        .update(payload)
        .eq("id", campaign_id)
        .eq("company_id", company_id)
        .execute()
    )
    return response.data[0] if response.data else None


def delete_broadcast_logs_by_campaign(campaign_id):
    supabase.table("broadcast_logs").delete().eq("campaign_id", campaign_id).execute()


def delete_campaign(campaign_id, company_id):
    """Removes the campaign and every recipient row that belongs to it.

    Logs go first: broadcast_logs.campaign_id has no ON DELETE CASCADE, so
    dropping the campaign first would strand them as unreachable rows.
    """
    delete_broadcast_logs_by_campaign(campaign_id)
    response = (
        supabase.table("broadcast_campaigns")
        .delete()
        .eq("id", campaign_id)
        .eq("company_id", company_id)
        .execute()
    )
    return bool(response.data)


def count_broadcast_logs_by_status(campaign_id):
    """Recipient tallies for one campaign, keyed by status.

    Selects only `status` rather than reusing get_broadcast_logs_by_campaign:
    the progress endpoint is polled every two seconds during a send, and the
    full row carries error_message strings this caller never reads.
    """
    response = (
        supabase.table("broadcast_logs")
        .select("status")
        .eq("campaign_id", campaign_id)
        .execute()
    )
    counts = {}
    for row in response.data or []:
        status = row.get("status") or "pending"
        counts[status] = counts.get(status, 0) + 1
    return counts


def cancel_pending_broadcast_logs(campaign_id):
    """Marks every not-yet-attempted recipient as cancelled in one statement."""
    response = (
        supabase.table("broadcast_logs")
        .update({"status": "cancelled", "error_message": "Cancelled before sending."})
        .eq("campaign_id", campaign_id)
        .in_("status", ["pending", "sending"])
        .execute()
    )
    return len(response.data or [])


def withdraw_marketing_consent(company_id, platform, recipient, phone_digits, chatbot_id, evidence_id):
    now = _now_iso()
    supabase.table("marketing_consents").upsert({
        "company_id": company_id, "platform": platform, "platform_user_id": recipient,
        "phone_digits": phone_digits, "status": "withdrawn", "source": "stop_word",
        "withdrawn_at": now, "updated_at": now, "chatbot_id": chatbot_id,
        "evidence_message_id": evidence_id,
    }, on_conflict="company_id,platform,platform_user_id").execute()


def reserve_marketing_question(company_id, platform, recipient, chatbot_id, business, language, phone_digits):
    # INSERT ON CONFLICT DO NOTHING serializes first contact even across bots/workers.
    rows = supabase.table("marketing_consents").upsert({
        "company_id": company_id, "platform": platform, "platform_user_id": recipient,
        "phone_digits": phone_digits, "chatbot_id": chatbot_id, "status": "asked",
        "source": "chat_reply", "business_name": business, "language": language,
    }, on_conflict="company_id,platform,platform_user_id", ignore_duplicates=True).execute().data
    return bool(rows)


def _pending_consent_update(company_id, platform, recipient, fields):
    return (supabase.table("marketing_consents").update(fields)
            .eq("company_id", company_id).eq("platform", platform)
            .eq("platform_user_id", recipient).eq("status", "asked"))


def mark_marketing_question_sent(company_id, platform, recipient):
    now = _now_iso()
    _pending_consent_update(company_id, platform, recipient, {"asked_at": now, "updated_at": now}).execute()


def grant_pending_marketing_consent(company_id, platform, recipient, chatbot_id, evidence_id):
    now = _now_iso()
    fields = {"status": "granted", "granted_at": now, "updated_at": now,
              "source": "chat_reply", "chatbot_id": chatbot_id, "evidence_message_id": evidence_id}
    _pending_consent_update(company_id, platform, recipient, fields).not_.is_("asked_at", "null").execute()


def is_marketing_phone_withdrawn(company_id, phone_digits):
    rows = (supabase.table("marketing_consents").select("id")
            .eq("company_id", company_id).eq("phone_digits", phone_digits)
            .eq("status", "withdrawn").limit(1).execute().data)
    if not isinstance(rows, list):
        raise ValueError("Marketing consent lookup unavailable.")
    return bool(rows)


def confirm_campaign_start(campaign_id, company_id, chatbot_id, previous_status, status, user_id):
    now = _now_iso()
    fields = {"status": status, "updated_at": now, "consent_confirmed_by": user_id, "consent_confirmed_at": now}
    # Only the request that claims the current status may launch a worker.
    rows = (supabase.table("broadcast_campaigns").update(fields)
            .eq("id", campaign_id).eq("company_id", company_id).eq("chatbot_id", chatbot_id)
            .eq("status", previous_status).execute().data)
    return bool(rows)
