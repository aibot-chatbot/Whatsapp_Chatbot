"""Private Analysis storage. Mutations are atomic, tenant-scoped database RPCs."""
from datetime import datetime, timezone
import json
import re
from uuid import UUID

from app.database.db import supabase


class AnalysisUnavailable(RuntimeError):
    status_code = 503


class AnalysisConflict(ValueError):
    status_code = 409


class AnalysisScopeDenied(PermissionError):
    status_code = 404


class AnalysisRateLimited(ValueError):
    status_code = 429


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _uuid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("A valid UUID is required") from None


def _object(value, maximum=1048576):
    if not isinstance(value, dict):
        raise ValueError("An object is required")
    # Reject NaN and objects which cannot safely round-trip as JSON.
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")) > maximum:
        raise ValueError("Analysis data is too large")
    return value


def _text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("Invalid text length")
    return value


def _scope(company_id, chatbot_id):
    return {"p_company_id": _positive(company_id, "company_id"),
            "p_chatbot_id": _positive(chatbot_id, "chatbot_id")}


def _rpc(name, params):
    try:
        data = supabase.rpc(name, params).execute().data
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code == "54000":
            raise AnalysisRateLimited("Your company already has 10 pending reports. Wait for a report to finish.") from None
        if code == "42501":
            raise AnalysisScopeDenied("Analysis scope or access is unavailable") from None
        if code in {"22023", "40001", "23505"}:
            raise AnalysisConflict("Analysis request or worker lease has changed") from None
        raise AnalysisUnavailable("Analysis storage is unavailable") from None
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict) or not data:
        raise AnalysisUnavailable("Analysis storage did not confirm the operation")
    return data


def _rows(query):
    try:
        rows = query.execute().data
    except Exception:
        raise AnalysisUnavailable("Analysis storage is unavailable") from None
    if not isinstance(rows, list):
        raise AnalysisUnavailable("Analysis storage returned no confirmed result")
    return rows


def create_report_request(company_id, chatbot_id, actor_user_id, client_message_id, text, *, request_spec=None):
    return _rpc("analysis_create_report_request", {
        **_scope(company_id, chatbot_id), "p_actor_user_id": _positive(actor_user_id, "actor_user_id"),
        "p_client_message_id": _text(client_message_id, 200), "p_text": _text(text, 2000),
        "p_request_spec": _object(request_spec if request_spec is not None else {}, 16384),
    })


MAX_HIDE_BATCH = 100


def hide_reports(company_id, chatbot_id, actor_user_id, report_ids=None):
    """Clear finished reports from the owner's list; the rows stay (data/074) with who cleared
    them. None clears every finished report of the Bot. Returns how many were cleared."""
    if report_ids is not None:
        if not isinstance(report_ids, list) or not 1 <= len(report_ids) <= MAX_HIDE_BATCH:
            raise ValueError(f"Choose between 1 and {MAX_HIDE_BATCH} reports.")
        report_ids = sorted({_uuid(item) for item in report_ids})
    result = _rpc("analysis_hide_reports", {**_scope(company_id, chatbot_id),
                                            "p_actor_user_id": _positive(actor_user_id, "actor_user_id"),
                                            "p_report_ids": report_ids})
    hidden = result.get("hidden")
    if type(hidden) is not int or hidden < 0:
        raise AnalysisUnavailable("Analysis storage did not confirm the operation")
    return hidden


def get_report(company_id, chatbot_id, report_id):
    _scope(company_id, chatbot_id)
    rows = _rows(supabase.table("analysis_reports").select("*")
        .eq("company_id", company_id).eq("chatbot_id", chatbot_id).eq("id", _uuid(report_id)).limit(1))
    return rows[0] if rows else None


def get_report_by_run_id(run_id):
    """Platform worker only; the returned row supplies all subsequent scope."""
    rows = _rows(supabase.table("analysis_reports").select("*").eq("run_id", _uuid(run_id)).limit(1))
    return rows[0] if rows else None


# No customer names, contacts or notes: reports count bookings, they never list customers.
BOOKING_COLUMNS = "id,company_id,chatbot_id,kind,status,channel,service_name,scheduled_for,party_size,price_micro_myr,created_at"
MAX_UPCOMING = 20


def _upcoming_bookings(company_id, chatbot_id, as_of, until):
    """Open bookings scheduled from capture up to `until`, soonest first."""
    if not until:
        return {"rows": [], "available": False, "truncated": False, "error_code": "source_unavailable"}
    try:
        rows = _rows(supabase.table("service_bookings").select(BOOKING_COLUMNS)
                     .eq("company_id", company_id).eq("chatbot_id", chatbot_id).in_("status", ["requested", "confirmed"])
                     .gte("scheduled_for", str(as_of)).lt("scheduled_for", str(until))
                     .order("scheduled_for").limit(MAX_UPCOMING + 1))
    except AnalysisUnavailable:
        return {"rows": [], "available": False, "truncated": False, "error_code": "source_unavailable"}
    return {"rows": rows[:MAX_UPCOMING], "available": True, "truncated": len(rows) > MAX_UPCOMING, "error_code": None}


def list_reports(company_id, chatbot_id, *, limit=50, before_created_at=None, before_id=None):
    _scope(company_id, chatbot_id)
    query = (supabase.table("analysis_reports").select("*").eq("company_id", company_id).eq("chatbot_id", chatbot_id)
             .is_("hidden_at", "null"))  # cleared reports stay in the table (data/074) but leave the list
    if before_created_at and not before_id:
        raise ValueError("Report pagination requires the report ID tie breaker")
    if before_id:
        cursor = get_report(company_id, chatbot_id, before_id)
        if not cursor:
            raise AnalysisScopeDenied("Report cursor is unavailable")
        stamp = datetime.fromisoformat(cursor["created_at"].replace("Z", "+00:00")).isoformat()
        query = query.or_(f"created_at.lt.{stamp},and(created_at.eq.{stamp},id.lt.{_uuid(before_id)})")
    return _rows(query.order("created_at", desc=True).order("id", desc=True).limit(min(_positive(limit, "limit"), 100)))


def _apply(*, company_id, chatbot_id, report_id, event_id, lease_token, operation, payload):
    return _rpc("analysis_apply_run", {**_scope(company_id, chatbot_id),
        "p_report_id": _uuid(report_id), "p_event_id": _positive(event_id, "event_id"),
        "p_lease_token": _uuid(lease_token), "p_operation": operation, "p_payload": _object(payload),
    })


def save_snapshot_fenced(*, company_id, chatbot_id, report_id, event_id, lease_token, snapshot):
    return _apply(company_id=company_id, chatbot_id=chatbot_id, report_id=report_id,
                  event_id=event_id, lease_token=lease_token, operation="snapshot", payload=snapshot)


def begin_model_step(*, company_id, chatbot_id, report_id, event_id, lease_token, step_id):
    if step_id not in {"plan", "analyze"}:
        raise ValueError("Only plan and analyze model steps are allowed")
    return _apply(company_id=company_id, chatbot_id=chatbot_id, report_id=report_id,
        event_id=event_id, lease_token=lease_token, operation="begin_step", payload={"step_id": step_id})


def get_model_step(company_id, chatbot_id, report_id, step_id):
    if step_id not in {"plan", "analyze"}:
        raise ValueError("Invalid model step")
    if not get_report(company_id, chatbot_id, report_id):
        raise AnalysisScopeDenied("Report is unavailable")
    rows = _rows(supabase.table("analysis_model_steps").select("state,output")
                 .eq("report_id", _uuid(report_id)).eq("step_id", step_id).limit(1))
    return rows[0] if rows else None


def finish_model_step(*, company_id, chatbot_id, report_id, event_id, lease_token, step_id, state, output=None):
    if step_id not in {"plan", "analyze"} or state not in {"succeeded", "uncertain"}:
        raise ValueError("Invalid model step outcome")
    payload = {"step_id": step_id, "state": state}
    if output is not None:
        payload["output"] = _object(output)
    return _apply(company_id=company_id, chatbot_id=chatbot_id, report_id=report_id,
        event_id=event_id, lease_token=lease_token, operation="finish_step", payload=payload)


def finish_report(*, company_id, chatbot_id, report_id, event_id, lease_token,
                  status, result=None, manifest=None, error_code=None):
    if status not in {"complete", "partial", "failed", "needs_review", "needs_input"}:
        raise ValueError("Invalid report outcome")
    if error_code is not None and (not isinstance(error_code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error_code)):
        raise ValueError("Invalid report error code")
    payload = {"status": status, "manifest": _object(manifest if manifest is not None else {}, 2048)}
    if result is not None:
        payload["result"] = _object(result)
    if error_code:
        payload["error_code"] = error_code
    return _apply(company_id=company_id, chatbot_id=chatbot_id, report_id=report_id,
        event_id=event_id, lease_token=lease_token, operation="finish", payload=payload)


def record_business_event(*, company_id, chatbot_id, conversation_id, actor_user_id, event_key,
                          action_type, status, source, record_id=None, evidence_message_ids=None, details=None):
    if not isinstance(action_type, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", action_type):
        raise ValueError("Invalid business action")
    if status not in {"intent", "requested", "confirmed", "completed", "failed", "cancelled", "rescheduled"}:
        raise ValueError("Invalid business status")
    if source not in {"observation", "business_service"} or (source == "observation" and status not in {"intent", "requested"}):
        raise ValueError("Observation cannot establish business success")
    if source == "business_service":
        _text(record_id, 200)
    evidence = evidence_message_ids if evidence_message_ids is not None else []
    if not isinstance(evidence, list) or len(evidence) > 50:
        raise ValueError("Invalid evidence references")
    if source == "observation" and not evidence:
        raise ValueError("An observation requires a customer message reference")
    for value in evidence:
        _positive(value, "evidence_message_id")
    return _rpc("analysis_record_business_event", {**_scope(company_id, chatbot_id),
        "p_conversation_id": _positive(conversation_id, "conversation_id"),
        "p_actor_user_id": None if actor_user_id is None else _positive(actor_user_id, "actor_user_id"),
        "p_event_key": _text(event_key, 200), "p_action_type": action_type, "p_status": status,
        "p_source": source, "p_record_id": record_id, "p_evidence_message_ids": evidence,
        "p_details": _object(details if details is not None else {}, 16384),
    })


def list_business_events(company_id, chatbot_id, *, after_id=0, limit=100, start_at=None, end_at=None):
    """Newest first. after_id is the last id of the previous page (0 = first page)."""
    _scope(company_id, chatbot_id)
    if isinstance(after_id, bool) or not isinstance(after_id, int) or after_id < 0:
        raise ValueError("Invalid event cursor")
    query = supabase.table("business_events").select("*").eq("company_id", company_id).eq("chatbot_id", chatbot_id)
    if after_id:
        query = query.lt("id", after_id)
    if start_at:
        query = query.gte("created_at", start_at)
    if end_at:
        query = query.lt("created_at", end_at)
    return _rows(query.order("id", desc=True).limit(min(_positive(limit, "limit"), 500)))


def get_report_context(company_id, chatbot_id):
    _scope(company_id, chatbot_id)
    rows = _rows(supabase.table("chatbots")
        .select("id,company_id,bot_name,bot_description,status,deleted_at,deployed_profile_name,industry_template_published")
        .eq("company_id", company_id).eq("id", chatbot_id).is_("deleted_at", "null").neq("status", "archived").limit(1))
    if not rows:
        raise AnalysisScopeDenied("Bot is unavailable")
    bot = rows[0]
    query = supabase.table("bot_configs").select(
        "profile_name,company_name,business_description,additional_instructions,tone,response_style")
    query = query.eq("chatbot_id", chatbot_id)
    if bot.get("deployed_profile_name"):
        query = query.eq("profile_name", bot["deployed_profile_name"])
    else:
        query = query.eq("is_active", True)
    try:
        settings = _rows(query.order("id").limit(1))
    except AnalysisUnavailable:
        return {"bot": bot, "settings": {}, "settings_available": False}
    return {"bot": bot, "settings": settings[0] if settings else {}, "settings_available": True}


get_bot_context = get_report_context


def _page_source(factory, maximum=2000, *, cursor=0):
    """Keyset pages by id. Pass cursor=None for UUID keys: the first page has no lower bound.

    Canonical lowercase UUID strings sort in the same order as PostgreSQL uuid values.
    """
    rows = []
    try:
        while len(rows) <= maximum:
            query = factory() if cursor is None else factory().gt("id", cursor)
            page = _rows(query.order("id").limit(min(200, maximum + 1 - len(rows))))
            if not page:
                break
            rows.extend(page)
            new_cursor = page[-1]["id"]
            if cursor is not None and new_cursor <= cursor:
                raise AnalysisUnavailable("Invalid source cursor")
            cursor = new_cursor
            if len(rows) > maximum:
                break
    except (AnalysisUnavailable, KeyError, TypeError):
        return {"rows": [], "available": False, "truncated": False, "error_code": "source_unavailable"}
    return {"rows": rows[:maximum], "available": True, "truncated": len(rows) > maximum, "error_code": None}


def list_report_documents(company_id, chatbot_id):
    get_report_context(company_id, chatbot_id)
    source = _page_source(lambda: supabase.table("knowledge_files")
        .select("id,chatbot_id,file_name,file_type,processing_status,is_active,is_enabled,created_at")
        .eq("chatbot_id", chatbot_id).eq("processing_status", "completed")
        .or_("is_active.eq.true,is_enabled.eq.true,is_enabled.is.null"), 200)
    if not source["available"]:
        raise AnalysisUnavailable("Document metadata unavailable")
    if source["truncated"]:
        raise AnalysisUnavailable("Document selection exceeds the supported limit")
    return [{**row, "role": "primary" if row.get("is_active") else "supporting"} for row in source["rows"]]


MAX_TUITION_SESSIONS = 500
MAX_TUITION_BOOKINGS = 5000
TUITION_SESSION_CHUNK = 100  # Keeps each PostgREST in.(...) filter well under URL limits.


def _unavailable_source():
    return {"rows": [], "available": False, "truncated": False, "error_code": "source_unavailable"}


def _tuition_sources(company_id, chatbot_id, date_from, date_to, as_of):
    """Trial sessions starting in the period and their bookings, scoped to one company Bot.

    Only capacity/status columns are read: never contact keys, participants or conversations.
    """
    def sessions_query():
        query = (supabase.table("tuition_sessions").select("id,company_id,chatbot_id,starts_at,trial_limit,created_at")
                 .eq("company_id", company_id).eq("chatbot_id", chatbot_id))
        if date_from:
            query = query.gte("starts_at", str(date_from))
        if date_to:
            query = query.lt("starts_at", str(date_to))
        return query.lte("created_at", str(as_of))
    sessions = _page_source(sessions_query, MAX_TUITION_SESSIONS, cursor=None)
    if not sessions["available"]:
        return {"tuition_sessions": sessions, "tuition_bookings": _unavailable_source()}
    ids = [row["id"] for row in sessions["rows"]]
    bookings = {"rows": [], "available": True, "truncated": False, "error_code": None}
    for index in range(0, len(ids), TUITION_SESSION_CHUNK):
        chunk = ids[index:index + TUITION_SESSION_CHUNK]
        page = _page_source(lambda chunk=chunk: supabase.table("tuition_bookings")
            .select("id,company_id,chatbot_id,session_id,status,reminder_status,created_at")
            .eq("company_id", company_id).eq("chatbot_id", chatbot_id).in_("session_id", chunk)
            .lte("created_at", str(as_of)), MAX_TUITION_BOOKINGS - len(bookings["rows"]), cursor=None)
        if not page["available"]:
            return {"tuition_sessions": sessions, "tuition_bookings": _unavailable_source()}
        bookings["rows"] += page["rows"]
        if page["truncated"]:
            bookings["truncated"] = True
            break
    return {"tuition_sessions": sessions, "tuition_bookings": bookings}


def load_report_sources(company_id, chatbot_id, date_from, date_to, as_of, document_ids=None, *,
                        include_customer_questions=False, include_tuition=False, include_bookings=False, upcoming_until=None):
    """Bounded source pages, with explicit unavailable/truncated states, never fake zeros."""
    get_report_context(company_id, chatbot_id)
    as_of = as_of or datetime.now(timezone.utc).isoformat()
    if document_ids is not None and (not isinstance(document_ids, list) or len(document_ids) > 50):
        raise ValueError("Invalid document selection")
    for document_id in document_ids or []:
        _positive(document_id, "document_id")
    def period(query):
        if date_from:
            query = query.gte("created_at", str(date_from))
        if date_to:
            query = query.lt("created_at", str(date_to))
        return query.lte("created_at", str(as_of or datetime.now(timezone.utc).isoformat()))
    sources = {}
    sources["business_events"] = _page_source(lambda: period(supabase.table("business_events").select("*")
        .eq("company_id", company_id).eq("chatbot_id", chatbot_id)))
    sources["conversations"] = _page_source(lambda: period(supabase.table("conversations")
        .select("id,chatbot_id,source_channel,conversation_status,created_at,updated_at")
        .eq("chatbot_id", chatbot_id)))
    # Join scopes messages independently of conversation creation date: old conversations
    # may contain new activity. No phone-based grouping or contact fields are loaded.
    sources["messages"] = _page_source(lambda: period(supabase.table("messages")
        .select("id,conversation_id,sender_type,message_type,ai_generated,actor_user_id,delivery_status,created_at,conversations!inner(chatbot_id)")
        .eq("conversations.chatbot_id", chatbot_id)), 5000)
    if include_customer_questions:
        sources["customer_questions"] = _page_source(lambda: period(supabase.table("messages")
            .select("id,conversation_id,sender_type,message_type,ai_generated,actor_user_id,message_text,created_at,conversations!inner(chatbot_id)")
            .eq("conversations.chatbot_id", chatbot_id).eq("sender_type", "customer")
            .eq("message_type", "text").eq("ai_generated", False).is_("actor_user_id", "null")), 100)
    from app.database.agent_action_repository import get_blocked_content_message_ids

    message_sources = [sources[name] for name in ("messages", "customer_questions") if name in sources]
    blocked_by_conversation = {
        conversation_id: get_blocked_content_message_ids(conversation_id)
        for conversation_id in {row.get("conversation_id") for source in message_sources for row in source["rows"]}
    }
    for source in message_sources:
        source["rows"] = [row for row in source["rows"]
                          if str(row.get("id")) not in blocked_by_conversation[row.get("conversation_id")]]
    sources["crm_leads"] = _page_source(lambda: period(supabase.table("crm_leads")
        .select("id,company_id,chatbot_id,conversation_id,lead_type,status,priority,created_at,updated_at")
        .eq("company_id", company_id).eq("chatbot_id", chatbot_id)))
    if include_tuition:
        sources.update(_tuition_sources(company_id, chatbot_id, date_from, date_to, as_of))
    if include_bookings:
        sources["service_bookings"] = _page_source(lambda: period(supabase.table("service_bookings")
            .select(BOOKING_COLUMNS).eq("company_id", company_id).eq("chatbot_id", chatbot_id)))
        sources["upcoming_bookings"] = _upcoming_bookings(company_id, chatbot_id, as_of, upcoming_until)
    try:
        documents = list_report_documents(company_id, chatbot_id)
        allowed = {row["id"] for row in documents}
        if document_ids and not set(document_ids).issubset(allowed):
            raise AnalysisScopeDenied("A selected document is unavailable")
        if document_ids is not None:
            documents = [row for row in documents if row["id"] in document_ids]
        sources["documents"] = {"rows": documents, "available": True, "truncated": False, "error_code": None}
        selected = [row["id"] for row in documents]
        sources["chunks"] = _page_source(lambda: supabase.table("knowledge_chunks")
            .select("id,chatbot_id,file_id,content,metadata,created_at")
            .eq("chatbot_id", chatbot_id).in_("file_id", selected).lte("created_at", str(as_of)), 1000) if selected else {
                "rows": [], "available": True, "truncated": False, "error_code": None}
    except AnalysisUnavailable:
        sources["documents"] = {"rows": [], "available": False, "truncated": False, "error_code": "source_unavailable"}
        sources["chunks"] = dict(sources["documents"])
    return sources


LAST_DAY = 0  # data/070: run_day 0 stores "last day of the month"


def _schedule(row):
    """Database row -> API form: run_day 0 -> "last", run_time "HH:MM:SS" -> "HH:MM"."""
    run_day, run_time = row.get("run_day"), row.get("run_time")
    return {**row, "run_weekday": row.get("run_weekday"),
            "run_day": "last" if run_day == LAST_DAY else run_day,
            "run_time": run_time[:5] if isinstance(run_time, str) else None}


def list_schedules(company_id, chatbot_id):
    _scope(company_id, chatbot_id)
    return [_schedule(row) for row in _rows(supabase.table("analysis_schedules").select("*")
        .eq("company_id", company_id).eq("chatbot_id", chatbot_id).order("frequency").limit(2))]


def upsert_schedule(company_id, chatbot_id, actor_user_id, *, frequency, enabled, timezone="Asia/Kuala_Lumpur",
                    next_due_at=None, run_weekday=None, run_day=None, run_time=None):
    """Values are validated by analysis_request_service.validate_schedule_choice.

    A slot argument left as None is not sent: the RPC then keeps the stored
    value, so skip/disable never wipe the owner's choice, and a call with no
    slot is the pre-070 7-argument call that resolves on either schema.
    """
    if frequency not in {"weekly", "monthly"} or timezone != "Asia/Kuala_Lumpur" or not isinstance(enabled, bool):
        raise ValueError("Invalid schedule")
    slot = {"p_run_weekday": run_weekday, "p_run_day": LAST_DAY if run_day == "last" else run_day,
            "p_run_time": run_time}
    return _schedule(_rpc("analysis_upsert_schedule", {**_scope(company_id, chatbot_id),
        "p_actor_user_id": _positive(actor_user_id, "actor_user_id"), "p_frequency": frequency,
        "p_timezone": timezone, "p_enabled": enabled, "p_next_due_at": next_due_at,
        **{key: value for key, value in slot.items() if value is not None}}))


def list_due_schedules(*, now=None, limit=100, offset=0):
    """Platform scheduler only; tenant requests cannot choose this read path.

    ``offset`` lets the tick step past rows it could not move out of the due
    set (actor gone, company suspended), so they never starve later tenants.
    """
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    size = min(_positive(limit, "limit"), 100)
    return [_schedule(row) for row in _rows(supabase.table("analysis_schedules").select("*").eq("enabled", True)
        .lte("next_due_at", now or datetime.now(timezone.utc).isoformat())
        .order("next_due_at").order("id").range(offset, offset + size - 1))]


def list_enabled_company_schedules(company_id):
    """Platform maintenance (plan downgrade) only; never a tenant read path."""
    _positive(company_id, "company_id")
    # ponytail: at most 2 schedules per Bot; 100 caps a runaway company.
    return [_schedule(row) for row in _rows(supabase.table("analysis_schedules").select("*")
        .eq("company_id", company_id).eq("enabled", True).limit(100))]


def _reschedule(schedule, *, enabled, next_due_at):
    # service_role cannot UPDATE analysis_schedules; the RPC is the only writer
    # and re-verifies the stored actor.
    return upsert_schedule(schedule["company_id"], schedule["chatbot_id"], schedule["actor_user_id"],
        frequency=schedule["frequency"], enabled=enabled, next_due_at=next_due_at)


def skip_schedule_period(schedule, *, next_due_at):
    """Move an enabled schedule past its current period without a report."""
    return _reschedule(schedule, enabled=True, next_due_at=next_due_at)


def disable_schedule(schedule):
    return _reschedule(schedule, enabled=False, next_due_at=None)


def enqueue_schedule_report(company_id, chatbot_id, schedule_id, *, period_key, request_spec, next_due_at):
    return _rpc("analysis_enqueue_schedule", {**_scope(company_id, chatbot_id), "p_schedule_id": _uuid(schedule_id),
        "p_period_key": _text(period_key, 100), "p_request_spec": _object(request_spec, 16384), "p_next_due_at": next_due_at})


def count_company_reports_in_flight(company_id, *, exclude_client_message_id=None):
    """Reports of this company queued or running, the same statuses analysis_create_report_request caps."""
    query = (supabase.table("analysis_reports").select("id")
             .eq("company_id", _positive(company_id, "company_id")).in_("status", ["queued", "running"]))
    if exclude_client_message_id:
        query = query.neq("client_message_id", exclude_client_message_id)
    return len(_rows(query))
