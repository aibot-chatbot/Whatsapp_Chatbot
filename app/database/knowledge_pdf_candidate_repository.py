"""Repository helpers for temporary supporting-PDF candidates."""

from datetime import datetime, timezone

from app.database.db import supabase


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def create_candidate(candidate: dict) -> dict:
    data = dict(candidate)
    data.setdefault("updated_at", _utc_now_iso())
    result = supabase.table("knowledge_pdf_candidates").insert(data).execute()
    return result.data[0]


def get_candidate(candidate_id: str, chatbot_id: int, company_id: int) -> dict | None:
    result = (
        supabase.table("knowledge_pdf_candidates")
        .select("*")
        .eq("id", candidate_id)
        .eq("chatbot_id", chatbot_id)
        .eq("company_id", company_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def update_candidate(candidate_id: str, chatbot_id: int, company_id: int, fields: dict) -> dict | None:
    data = dict(fields)
    data["updated_at"] = _utc_now_iso()
    result = (
        supabase.table("knowledge_pdf_candidates")
        .update(data)
        .eq("id", candidate_id)
        .eq("chatbot_id", chatbot_id)
        .eq("company_id", company_id)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def _conditional_status_update(
    candidate_id: str,
    chatbot_id: int,
    company_id: int,
    allowed_statuses: tuple[str, ...],
    fields: dict,
) -> dict | None:
    data = dict(fields)
    data["updated_at"] = _utc_now_iso()
    query = (
        supabase.table("knowledge_pdf_candidates")
        .update(data)
        .eq("id", candidate_id)
        .eq("chatbot_id", chatbot_id)
        .eq("company_id", company_id)
    )
    if len(allowed_statuses) == 1:
        query = query.eq("validation_status", allowed_statuses[0])
    else:
        query = query.in_("validation_status", list(allowed_statuses))
    result = query.execute()
    rows = result.data or []
    return rows[0] if rows else None


def mark_candidate_validated(
    candidate_id: str,
    chatbot_id: int,
    company_id: int,
    fields: dict,
) -> dict | None:
    status = fields.get("validation_status")
    if status not in {"validated_passed", "validated_failed"}:
        raise ValueError("validation_status must be validated_passed or validated_failed")
    return _conditional_status_update(
        candidate_id,
        chatbot_id,
        company_id,
        ("validating",),
        fields,
    )


def claim_candidate_for_confirmation(
    candidate_id: str,
    chatbot_id: int,
    company_id: int,
    now_iso: str | None = None,
) -> dict | None:
    """Atomically claim one passed candidate for ingestion.

    The conditional update is the concurrency boundary: only a row still in
    validated_passed at the moment the database applies the update can move to
    confirming. A second request will update zero rows and must reload state.
    """
    now_iso = now_iso or _utc_now_iso()
    result = (
        supabase.table("knowledge_pdf_candidates")
        .update({"validation_status": "confirming", "updated_at": now_iso})
        .eq("id", candidate_id)
        .eq("chatbot_id", chatbot_id)
        .eq("company_id", company_id)
        .eq("validation_status", "validated_passed")
        .eq("passed", True)
        .neq("duplicate_status", "exact_content_duplicate")
        .gt("expires_at", now_iso)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def mark_candidate_ingested(
    candidate_id: str,
    chatbot_id: int,
    company_id: int,
    ingested_file_id: int,
    confirmed_at: str | None = None,
) -> dict | None:
    confirmed_at = confirmed_at or _utc_now_iso()
    return _conditional_status_update(
        candidate_id,
        chatbot_id,
        company_id,
        ("confirming",),
        {
            "validation_status": "ingested_supporting",
            "confirmed_at": confirmed_at,
            "ingested_knowledge_file_id": ingested_file_id,
        },
    )


def recover_candidate_ingested(
    candidate_id: str,
    chatbot_id: int,
    company_id: int,
    ingested_file_id: int,
    confirmed_at: str | None = None,
) -> dict | None:
    confirmed_at = confirmed_at or _utc_now_iso()
    return _conditional_status_update(
        candidate_id,
        chatbot_id,
        company_id,
        ("confirming", "ingest_failed"),
        {
            "validation_status": "ingested_supporting",
            "confirmed_at": confirmed_at,
            "ingested_knowledge_file_id": ingested_file_id,
            "error_code": None,
            "error_message": None,
        },
    )


def mark_candidate_ingest_failed(
    candidate_id: str,
    chatbot_id: int,
    company_id: int,
    error_code: str,
    error_message: str,
) -> dict | None:
    return _conditional_status_update(
        candidate_id,
        chatbot_id,
        company_id,
        ("confirming",),
        {
            "validation_status": "ingest_failed",
            "error_code": error_code,
            "error_message": error_message,
        },
    )


def mark_candidate_cancelled(candidate_id: str, chatbot_id: int, company_id: int) -> dict | None:
    return _conditional_status_update(
        candidate_id,
        chatbot_id,
        company_id,
        ("pending", "validating", "validated_passed", "validated_failed", "ingest_failed", "expired"),
        {"validation_status": "cancelled", "passed": False},
    )


def mark_candidate_expired(candidate_id: str, chatbot_id: int, company_id: int) -> dict | None:
    return _conditional_status_update(
        candidate_id,
        chatbot_id,
        company_id,
        ("pending", "validating", "validated_passed", "validated_failed", "ingest_failed"),
        {"validation_status": "expired", "passed": False},
    )
