"""Service-role storage for templates submitted through the tenant's connected WABA."""
from datetime import datetime, timezone

from postgrest.exceptions import APIError

from app.database import db


TABLE = "whatsapp_templates"


def record_created(row):
    try:
        db.supabase.table(TABLE).insert(row).execute()
    except APIError as exc:
        if exc.code != "23505":
            raise
        # Clear selections of a deleted template before recording its replacement.
        removed = (db.supabase.table(TABLE).delete().eq("company_id", row["company_id"])
                   .eq("waba_id", row["waba_id"]).eq("name", row["name"]).eq("language", row["language"])
                   .eq("status", "DELETED").neq("meta_template_id", row["meta_template_id"]).execute())
        if not removed.data:
            raise
        db.supabase.table(TABLE).insert(row).execute()


def update_status(waba_id, template_id, status, reason, category, event_time):
    def scoped(query):
        return query.eq("waba_id", waba_id).eq("meta_template_id", template_id)

    rows = scoped(db.supabase.table(TABLE).select("status,status_event_time")).limit(1).execute().data
    if not rows:
        return
    previous_time = rows[0].get("status_event_time")
    if previous_time is not None and event_time is not None and (
        event_time < previous_time or
        (event_time == previous_time and status == "APPROVED" and rows[0]["status"] != "APPROVED")
    ):
        return
    fields = {"status": status, "rejected_reason": reason, "updated_at": datetime.now(timezone.utc).isoformat()}
    if category:
        fields["category"] = category
    if event_time is not None:
        fields["status_event_time"] = event_time
    query = scoped(db.supabase.table(TABLE).update(fields))
    query = (query.is_("status_event_time", "null") if previous_time is None
             else query.eq("status_event_time", previous_time))
    if not query.eq("status", rows[0]["status"]).execute().data:
        # Concurrent updates need a fresh comparison against the winning event.
        raise RuntimeError("Template status changed concurrently")


def remove_by_name(company_id, waba_id, name):
    db.supabase.table(TABLE).delete().eq("company_id", company_id).eq("waba_id", waba_id).eq("name", name).execute()


def _eligible(company_id, waba_id):
    # shortcut: send name + language only until follow-ups can supply component parameters.
    query = (db.supabase.table(TABLE).select("id,name,language,waba_id").eq("company_id", company_id)
             .eq("status", "APPROVED").eq("category", "MARKETING").eq("body_has_variables", False)
             .eq("requires_component_parameters", False))
    if isinstance(waba_id, str):
        return query.eq("waba_id", waba_id)
    if waba_id is not None:
        return query.in_("waba_id", waba_id)
    return query


def list_eligible(company_id, waba_id=None):
    if waba_id is not None and not waba_id:
        return []
    return _eligible(company_id, waba_id).order("name").order("language").execute().data


def get_eligible(company_id, template_id, waba_id=None):
    if not template_id or (waba_id is not None and not waba_id):
        return None
    rows = _eligible(company_id, waba_id).eq("id", template_id).limit(1).execute().data
    return rows[0] if rows else None
