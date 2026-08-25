import re
from datetime import datetime, timezone

from app.database.db import supabase


SAFE_CRM_LEAD_FIELDS = (
    "id,conversation_id,customer_phone,customer_name,source_channel,"
    "lead_type,status,priority,summary,notes,assigned_to,follow_up_date,"
    "created_at,updated_at"
)

# Keep the retired value while older rows are still being normalised on write.
OPEN_CRM_LEAD_STATUSES = ["new", "contacted", "qualified", "in_progress"]
ALLOWED_CRM_LEAD_STATUSES = ["new", "contacted", "qualified", "won", "lost"]
ALLOWED_CRM_LEAD_PRIORITIES = ["low", "medium", "high"]
_MISSING = object()

# Retired vocabulary (pre lead-stage-migration), accepted on WRITE for one
# release so an older client sending the old status names gets normalised
# instead of a 400/500. Remove this alias table -- and the
# normalize_crm_lead_status() call sites -- once no writer sends these.
_RETIRED_CRM_LEAD_STATUS_ALIASES = {
    "in_progress": "contacted",
    # "closed" carried no outcome signal in the old vocabulary -- there is no
    # way to tell a won deal from a lost one from the status string alone.
    # Conservatively normalised to "lost" rather than assumed "won" without
    # evidence. A real backfill with access to lead outcome data (see
    # DESIGN.md "Lead status migration") may want to do better than this
    # default for any row this still applies to.
    "closed": "lost",
}


def normalize_crm_lead_status(status):
    """Map a possibly-retired CRM lead status onto the current vocabulary.

    No-op for values already in ALLOWED_CRM_LEAD_STATUSES.
    """
    normalized = str(status or "").strip().lower()
    return _RETIRED_CRM_LEAD_STATUS_ALIASES.get(normalized, normalized)


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


def _database_error_code(error):
    code = getattr(error, "code", None)
    if code:
        return str(code)

    for argument in getattr(error, "args", ()):
        if isinstance(argument, dict) and argument.get("code"):
            return str(argument["code"])

    return None


def _is_unique_violation(error):
    return _database_error_code(error) == "23505"


def get_crm_leads_by_chatbot(chatbot_id, status=None, limit=50, conversation_id=None):
    safe_limit = min(max(int(limit or 50), 1), 100)
    status_values = None

    if status:
        # Keep legacy readers aligned with the write-time compatibility
        # window.  Include the retired value as well so rows written before
        # the migration remain visible until the compatibility window closes.
        raw_status = str(status).strip().lower()
        normalized_status = normalize_crm_lead_status(raw_status)
        status_values = [normalized_status]
        if normalized_status != raw_status and raw_status in _RETIRED_CRM_LEAD_STATUS_ALIASES:
            status_values.append(raw_status)

    query = (
        supabase.table("crm_leads")
        .select(SAFE_CRM_LEAD_FIELDS)
        .eq("chatbot_id", chatbot_id)
    )

    if status_values:
        query = (
            query.eq("status", status_values[0])
            if len(status_values) == 1
            else query.in_("status", status_values)
        )

    if conversation_id:
        query = query.eq("conversation_id", conversation_id)

    result = (
        query
        .order("created_at", desc=True)
        .limit(safe_limit)
        .execute()
    )

    return [_sanitize_crm_lead(row) for row in (result.data or [])]


def get_open_crm_lead_by_conversation(
    chatbot_id,
    conversation_id,
    company_id=None,
):
    if not conversation_id:
        return None

    query = (
        supabase.table("crm_leads")
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .eq("conversation_id", conversation_id)
        .in_("status", OPEN_CRM_LEAD_STATUSES)
    )
    if company_id is not None:
        query = query.eq("company_id", company_id)

    result = (
        query
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


def create_crm_lead_with_open_conflict_recovery(**lead_fields):
    conversation_id = lead_fields.get("conversation_id")
    chatbot_id = lead_fields.get("chatbot_id")

    try:
        return create_crm_lead(**lead_fields), True
    except Exception as error:
        if not conversation_id or not _is_unique_violation(error):
            raise

        winner = get_open_crm_lead_by_conversation(
            chatbot_id,
            conversation_id,
            company_id=lead_fields.get("company_id"),
        )
        if winner:
            return winner, False

        raise RuntimeError(
            "CRM open-lead conflict occurred but the winning lead could not be loaded."
        ) from error


def update_crm_lead_signal(
    lead_id,
    chatbot_id,
    company_id,
    lead_type=None,
    priority=None,
    summary=None,
):
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
        .eq("chatbot_id", chatbot_id)
        .eq("company_id", company_id)
        .execute()
    )

    return result.data[0] if result.data else None


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
        normalized_status = normalize_crm_lead_status(status)
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

    normalized_status = normalize_crm_lead_status(status or "new")
    if normalized_status not in ALLOWED_CRM_LEAD_STATUSES:
        raise ValueError("Invalid CRM lead status.")

    normalized_priority = str(priority or "medium").strip().lower()
    if normalized_priority not in ALLOWED_CRM_LEAD_PRIORITIES:
        raise ValueError("Invalid CRM lead priority.")

    existing = get_open_crm_lead_by_conversation(
        chatbot_id,
        conversation_id,
        company_id=company_id,
    )

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
            .eq("company_id", company_id)
            .execute()
        )

        rows = result.data or []
        return _sanitize_crm_lead(rows[0]) if rows else existing

    lead, created = create_crm_lead_with_open_conflict_recovery(
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

    if not created:
        # A concurrent request created the open lead after our initial lookup.
        # Apply this request to that winner instead of surfacing a generic error.
        existing = lead
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
            .eq("company_id", company_id)
            .execute()
        )
        rows = result.data or []
        return _sanitize_crm_lead(rows[0]) if rows else _sanitize_crm_lead(existing)

    return update_crm_lead_status_notes(
        chatbot_id=chatbot_id,
        lead_id=lead["id"],
        status=normalized_status,
        notes=notes,
        assigned_to=assigned_to,
        follow_up_date=follow_up_date,
    )
