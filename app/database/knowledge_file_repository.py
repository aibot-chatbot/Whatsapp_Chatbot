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

    try:
        result = supabase.table("knowledge_files").insert(data).execute()
    except Exception as e:
        if "is_enabled" not in str(e):
            raise

        logging.warning(
            "knowledge_files.is_enabled is not available yet; saving knowledge file without it."
        )
        data.pop("is_enabled", None)
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


def get_supporting_knowledge_files(chatbot_id: int):
    try:
        result = (
            supabase.table("knowledge_files")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("file_type", "url")
            .eq("is_enabled", True)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as e:
        if "is_enabled" not in str(e):
            raise

        logging.warning(
            "knowledge_files.is_enabled is not available yet; using all supporting website sources."
        )
        result = (
            supabase.table("knowledge_files")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("file_type", "url")
            .order("created_at", desc=True)
            .execute()
        )

    return result.data or []


def update_supporting_knowledge_enabled(chatbot_id: int, file_id: int, is_enabled: bool):
    result = (
        supabase.table("knowledge_files")
        .update({"is_enabled": is_enabled})
        .eq("chatbot_id", chatbot_id)
        .eq("id", file_id)
        .eq("file_type", "url")
        .execute()
    )

    return result.data[0] if result.data else None


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
