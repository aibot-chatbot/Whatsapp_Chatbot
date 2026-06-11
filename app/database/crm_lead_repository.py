import re
from datetime import datetime, timezone

from app.database.db import supabase


SAFE_CRM_LEAD_FIELDS = (
    "id,conversation_id,customer_phone,customer_name,source_channel,"
    "lead_type,status,priority,summary,notes,assigned_to,follow_up_date,"
    "created_at,updated_at"
)

OPEN_CRM_LEAD_STATUSES = ["new", "in_progress", "contacted"]
ALLOWED_CRM_LEAD_STATUSES = ["new", "in_progress", "contacted", "closed"]
ALLOWED_CRM_LEAD_PRIORITIES = ["low", "medium", "high"]
PRIORITY_RANK = {
    "low": 1,
    "medium": 2,
    "high": 3,
}
SIGNAL_SEVERITY_RANK = {
    "follow_up": 1,
    "staff_attention": 2,
    "negative_feedback": 3,
}
_MISSING = object()


def _mask_phone(phone):
    if not phone:
        return ""

    text = str(phone)
    digits = "".join(ch for ch in text if ch.isdigit())

    if len(digits) >= 4:
        return f"***{digits[-4:]}"

    return "***"


def _sanitize_crm_lead(row):
    return {
        "id": row.get("id"),
        "conversation_id": row.get("conversation_id"),
        "customer_phone": _mask_phone(row.get("customer_phone")),
        "customer_name": row.get("customer_name") or "",
        "source_channel": row.get("source_channel") or "",
        "lead_type": row.get("lead_type") or "",
        "status": row.get("status") or "",
        "priority": row.get("priority") or "",
        "summary": row.get("summary") or "",
        "notes": row.get("notes") or "",
        "assigned_to": row.get("assigned_to") or "",
        "follow_up_date": row.get("follow_up_date"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _normalize_follow_up_date(value):
    if value is None or value == "":
        return None

    text = str(value).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ValueError("Invalid follow_up_date format. Use YYYY-MM-DD.")

    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Invalid follow_up_date format. Use YYYY-MM-DD.")

    return text


def _priority_rank(priority):
    return PRIORITY_RANK.get((priority or "").lower(), 0)


def _signal_severity_rank(lead_type):
    return SIGNAL_SEVERITY_RANK.get((lead_type or "").lower(), 0)


def get_crm_leads_by_chatbot(chatbot_id, status=None, limit=50, conversation_id=None):
    safe_limit = min(max(int(limit or 50), 1), 100)

    query = (
        supabase.table("crm_leads")
        .select(SAFE_CRM_LEAD_FIELDS)
        .eq("chatbot_id", chatbot_id)
    )

    if status:
        query = query.eq("status", status)

    if conversation_id:
        query = query.eq("conversation_id", conversation_id)

    result = (
        query
        .order("created_at", desc=True)
        .limit(safe_limit)
        .execute()
    )

    return [_sanitize_crm_lead(row) for row in (result.data or [])]


def get_open_crm_lead_by_conversation(chatbot_id, conversation_id):
    if not conversation_id:
        return None

    result = (
        supabase.table("crm_leads")
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .eq("conversation_id", conversation_id)
        .in_("status", OPEN_CRM_LEAD_STATUSES)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    rows = result.data or []
    return rows[0] if rows else None


def get_crm_lead_by_conversation(chatbot_id, conversation_id):
    if not conversation_id:
        return None

    result = (
        supabase.table("crm_leads")
        .select(SAFE_CRM_LEAD_FIELDS)
        .eq("chatbot_id", chatbot_id)
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    rows = result.data or []
    return _sanitize_crm_lead(rows[0]) if rows else None


def create_crm_lead(
    company_id,
    chatbot_id,
    conversation_id=None,
    customer_phone=None,
    customer_name=None,
    source_channel=None,
    lead_type="follow_up",
    status="new",
    priority="medium",
    summary="",
    notes="",
):
    lead_data = {
        "company_id": company_id,
        "chatbot_id": chatbot_id,
        "conversation_id": conversation_id,
        "customer_phone": customer_phone,
        "customer_name": customer_name or "",
        "source_channel": source_channel,
        "lead_type": lead_type,
        "status": status,
        "priority": priority,
        "summary": summary,
        "notes": notes or "",
    }

    result = supabase.table("crm_leads").insert(lead_data).execute()
    return result.data[0] if result.data else None


def update_crm_lead_signal(lead_id, lead_type=None, priority=None, summary=None):
    update_data = {
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    if lead_type is not None:
        update_data["lead_type"] = lead_type

    if priority is not None:
        update_data["priority"] = priority

    if summary is not None:
        update_data["summary"] = summary

    result = (
        supabase.table("crm_leads")
        .update(update_data)
        .eq("id", lead_id)
        .execute()
    )

    return result.data[0] if result.data else None


def create_or_update_crm_lead_from_signal(
    company_id,
    chatbot_id,
    conversation_id=None,
    customer_phone=None,
    customer_name=None,
    source_channel=None,
    lead_type="follow_up",
    priority="medium",
    summary="",
):
    existing = get_open_crm_lead_by_conversation(chatbot_id, conversation_id)

    if existing:
        update_fields = {}
        new_priority_rank = _priority_rank(priority)
        existing_priority_rank = _priority_rank(existing.get("priority"))
        new_signal_rank = _signal_severity_rank(lead_type)
        existing_signal_rank = _signal_severity_rank(existing.get("lead_type"))

        if (
            new_priority_rank > existing_priority_rank
            or (
                new_priority_rank == existing_priority_rank
                and new_signal_rank > existing_signal_rank
            )
        ):
            update_fields = {
                "lead_type": lead_type,
                "priority": priority,
                "summary": summary,
            }

        return update_crm_lead_signal(
            existing["id"],
            **update_fields,
        )

    return create_crm_lead(
        company_id=company_id,
        chatbot_id=chatbot_id,
        conversation_id=conversation_id,
        customer_phone=customer_phone,
        customer_name=customer_name,
        source_channel=source_channel,
        lead_type=lead_type,
        status="new",
        priority=priority,
        summary=summary,
        notes="",
    )


def update_crm_lead_status_notes(
    chatbot_id,
    lead_id,
    status=None,
    notes=None,
    assigned_to=None,
    follow_up_date=_MISSING,
):
    update_data = {
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    if status is not None:
        normalized_status = str(status).strip().lower()
        if normalized_status not in ALLOWED_CRM_LEAD_STATUSES:
            raise ValueError("Invalid CRM lead status.")
        update_data["status"] = normalized_status

    if notes is not None:
        update_data["notes"] = str(notes).strip()[:1000]

    if assigned_to is not None:
        update_data["assigned_to"] = str(assigned_to).strip()[:100]

    if follow_up_date is not _MISSING:
        update_data["follow_up_date"] = _normalize_follow_up_date(follow_up_date)

    result = (
        supabase.table("crm_leads")
        .update(update_data)
        .eq("id", lead_id)
        .eq("chatbot_id", chatbot_id)
        .execute()
    )

    rows = result.data or []
    return _sanitize_crm_lead(rows[0]) if rows else None


def upsert_crm_lead_by_conversation(
    company_id,
    chatbot_id,
    conversation_id,
    customer_phone=None,
    customer_name=None,
    source_channel=None,
    status="new",
    priority="medium",
    assigned_to=None,
    follow_up_date=_MISSING,
    notes=None,
    lead_type="follow_up",
    summary="Customer conversation added to CRM for follow-up.",
):
    if not conversation_id:
        raise ValueError("conversation_id is required")

    normalized_status = str(status or "new").strip().lower()
    if normalized_status not in ALLOWED_CRM_LEAD_STATUSES:
        raise ValueError("Invalid CRM lead status.")

    normalized_priority = str(priority or "medium").strip().lower()
    if normalized_priority not in ALLOWED_CRM_LEAD_PRIORITIES:
        raise ValueError("Invalid CRM lead priority.")

    existing = get_crm_lead_by_conversation(chatbot_id, conversation_id)

    if existing:
        update_data = {
            "customer_name": customer_name or "",
            "source_channel": source_channel or "",
            "status": normalized_status,
            "priority": normalized_priority,
            "assigned_to": str(assigned_to or "").strip()[:100],
            "notes": str(notes or "").strip()[:1000],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        if follow_up_date is not _MISSING:
            update_data["follow_up_date"] = _normalize_follow_up_date(follow_up_date)

        if customer_phone:
            update_data["customer_phone"] = customer_phone

        result = (
            supabase.table("crm_leads")
            .update(update_data)
            .eq("id", existing["id"])
            .eq("chatbot_id", chatbot_id)
            .execute()
        )

        rows = result.data or []
        return _sanitize_crm_lead(rows[0]) if rows else existing

    lead = create_crm_lead(
        company_id=company_id,
        chatbot_id=chatbot_id,
        conversation_id=conversation_id,
        customer_phone=customer_phone,
        customer_name=customer_name,
        source_channel=source_channel,
        lead_type=lead_type,
        status=normalized_status,
        priority=normalized_priority,
        summary=summary,
        notes=str(notes or "").strip()[:1000],
    )

    if not lead:
        return None

    return update_crm_lead_status_notes(
        chatbot_id=chatbot_id,
        lead_id=lead["id"],
        status=normalized_status,
        notes=notes,
        assigned_to=assigned_to,
        follow_up_date=follow_up_date,
    )
