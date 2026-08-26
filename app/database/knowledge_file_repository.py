import logging

from app.database.db import supabase


def save_knowledge_file(
    chatbot_id: int,
    file_name: str,
    file_type: str = "pdf",
    file_size: int = None,
    file_path: str = None,
    upload_status: str = "uploaded",
    processing_status: str = "pending",
    match_status: str = "unchecked",
    mismatch_reason: str = None,
    is_enabled: bool = True,
    is_active: bool = None,
    source_pdf_candidate_id: str = None,
    original_file_name: str = None,
):
    data = {
        "chatbot_id": chatbot_id,
        "file_name": file_name,
        "file_type": file_type,
        "file_size": file_size,
        "file_path": file_path,
        "upload_status": upload_status,
        "processing_status": processing_status,
        "match_status": match_status,
        "mismatch_reason": mismatch_reason,
        "is_enabled": is_enabled,
    }
    if is_active is not None:
        data["is_active"] = is_active
    if source_pdf_candidate_id is not None:
        data["source_pdf_candidate_id"] = source_pdf_candidate_id
    if original_file_name is not None:
        data["original_file_name"] = original_file_name

    try:
        result = supabase.table("knowledge_files").insert(data).execute()
    except Exception as e:
        if source_pdf_candidate_id is not None and "source_pdf_candidate_id" in str(e):
            raise

        optional_columns = ("is_enabled", "is_active", "original_file_name")
        if not any(column in str(e) for column in optional_columns):
            raise

        logging.warning(
            "One or more optional knowledge_files columns are not available yet; saving knowledge file without them."
        )
        data.pop("is_enabled", None)
        data.pop("is_active", None)
        data.pop("original_file_name", None)
        result = supabase.table("knowledge_files").insert(data).execute()

    return result.data[0]


def update_knowledge_file_status(
    file_id: int,
    processing_status: str = None,
    match_status: str = None,
    mismatch_reason: str = None,
):
    update_data = {}

    if processing_status is not None:
        update_data["processing_status"] = processing_status

    if match_status is not None:
        update_data["match_status"] = match_status

    if mismatch_reason is not None:
        update_data["mismatch_reason"] = mismatch_reason

    result = (
        supabase.table("knowledge_files")
        .update(update_data)
        .eq("id", file_id)
        .execute()
    )

    return result.data[0]

def delete_knowledge_file_by_name(chatbot_id: int, file_name: str):
    result = (
        supabase.table("knowledge_files")
        .delete()
        .eq("chatbot_id", chatbot_id)
        .eq("file_name", file_name)
        .execute()
    )

    return result.data


def get_knowledge_file_by_name_or_id(chatbot_id: int, file_identifier):
    if not file_identifier:
        return None

    identifier = str(file_identifier)
    query = (
        supabase.table("knowledge_files")
        .select("*")
        .eq("chatbot_id", chatbot_id)
    )

    if identifier.isdigit():
        result = query.eq("id", int(identifier)).limit(1).execute()
        rows = result.data or []
        if rows:
            return rows[0]

    result = (
        supabase.table("knowledge_files")
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .eq("file_name", identifier)
        .limit(1)
        .execute()
    )

    rows = result.data or []
    return rows[0] if rows else None


def delete_knowledge_file_by_id(chatbot_id: int, file_id: int):
    result = (
        supabase.table("knowledge_files")
        .delete()
        .eq("chatbot_id", chatbot_id)
        .eq("id", file_id)
        .execute()
    )

    return result.data


def set_active_knowledge_file(chatbot_id: int, file_name: str):
    # Set all files for this chatbot to inactive
    supabase.table("knowledge_files") \
        .update({"is_active": False}) \
        .eq("chatbot_id", chatbot_id) \
        .execute()

    # Set selected file to active
    result = (
        supabase.table("knowledge_files")
        .update({"is_active": True})
        .eq("chatbot_id", chatbot_id)
        .eq("file_name", file_name)
        .execute()
    )

    return result.data[0] if result.data else None


def get_active_knowledge_file(chatbot_id: int):
    try:
        result = (
            supabase.table("knowledge_files")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logging.error(
            "Failed to load active PDF knowledge file for chatbot_id=%s: %s",
            chatbot_id,
            e,
        )
        return None

    return result.data[0] if result.data else None


def get_supporting_knowledge_files(chatbot_id: int) -> list:
    """Return every enabled supporting knowledge source for one chatbot.

    Supporting knowledge is no longer websites only: a document that is not
    the primary one is still worth searching once the operator enables it,
    and the row already carries the `is_enabled` flag that says so.

    The active primary is excluded here because the retrieval caller loads it
    separately. Leaving it in would feed its chunks into the context twice and
    make the per-source budget count it twice.
    """
    try:
        result = (
            supabase.table("knowledge_files")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("is_enabled", True)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as e:
        if "is_enabled" not in str(e):
            raise

        logging.warning(
            "knowledge_files.is_enabled is not available yet; using all non-primary supporting sources."
        )
        result = (
            supabase.table("knowledge_files")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .order("created_at", desc=True)
            .execute()
        )

    # Filtered in Python rather than with .neq("is_active", True): a row whose
    # is_active is NULL is not primary, but PostgREST's neq drops NULL rows
    # too, which would hide legitimate supporting sources.
    return [row for row in (result.data or []) if not row.get("is_active")]


def update_supporting_knowledge_enabled(chatbot_id: int, file_id: int, is_enabled: bool):
    # No file_type filter: documents can be supporting sources as well as
    # websites, and the tenancy scope is the chatbot_id + id pair.
    result = (
        supabase.table("knowledge_files")
        .update({"is_enabled": is_enabled})
        .eq("chatbot_id", chatbot_id)
        .eq("id", file_id)
        .execute()
    )

    return result.data[0] if result.data else None


def get_knowledge_file_by_source_candidate(chatbot_id: int, source_pdf_candidate_id: str):
    if not source_pdf_candidate_id:
        return None

    try:
        result = (
            supabase.table("knowledge_files")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("source_pdf_candidate_id", source_pdf_candidate_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        if "source_pdf_candidate_id" not in str(e):
            raise
        logging.warning(
            "knowledge_files.source_pdf_candidate_id is not available yet; cannot recover candidate ingestion."
        )
        return None

    rows = result.data or []
    return rows[0] if rows else None


def set_active_pdf_knowledge_file(chatbot_id: int, file_id: int):
    supabase.table("knowledge_files") \
        .update({"is_active": False}) \
        .eq("chatbot_id", chatbot_id) \
         \
        .execute()
 
    result = (
        supabase.table("knowledge_files")
        .update({"is_active": True})
        .eq("chatbot_id", chatbot_id)
        
        .eq("id", file_id)
        .execute()
    )

    return result.data[0] if result.data else None

def get_knowledge_files(chatbot_id: int):
    result = (
        supabase.table("knowledge_files")
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .order("created_at", desc=True)
        .execute()
    )

    return result.data

def get_active_knowledge_file(chatbot_id: int):
    try:
        result = (
            supabase.table("knowledge_files")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logging.error(
            "Failed to load active knowledge file for chatbot_id=%s: %s",
            chatbot_id,
            e,
        )
        return None

    return result.data[0] if result.data else None


# Backwards-compatible alias.
#
# `get_active_pdf_knowledge_file` was renamed to `get_active_knowledge_file`
# and its `file_type == "pdf"` filter deliberately dropped, so a non-PDF
# knowledge file can be the active one. The rename left 20 callers in
# knowledge_routes.py and knowledge_service.py pointing at the old name; they
# are lazy imports, so they fail at call time rather than at startup.
#
# This alias restores them without renaming 36 call sites across 9 files.
# Note the semantic change it inherits: callers no longer get a PDF-only
# result. Removing the alias and updating the call sites is the tidier fix and
# belongs with whoever owns the rename.
get_active_pdf_knowledge_file = get_active_knowledge_file
