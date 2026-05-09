import os
from werkzeug.utils import secure_filename

from app.services.settings_service import update_chatbot_runtime
from app.database.knowledge_file_repository import save_knowledge_file
from app.database.knowledge_file_repository import delete_knowledge_file_by_name
from app.database.knowledge_file_repository import set_active_knowledge_file
from app.database.knowledge_file_repository import get_knowledge_files
from app.database.knowledge_file_repository import get_active_knowledge_file

DATA_FOLDER = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data")
)


def save_uploaded_pdf(file, chatbot_id):
    if not file:
        raise ValueError("No file provided")

    if file.filename == "":
        raise ValueError("No selected file")

    if not file.filename.lower().endswith(".pdf"):
        raise ValueError("Invalid file type")

    os.makedirs(DATA_FOLDER, exist_ok=True)

    original_name = secure_filename(file.filename)
    safe_name = f"bot_{chatbot_id}_{original_name}"

    filepath = os.path.join(DATA_FOLDER, safe_name)
    file.save(filepath)

    relative_pdf_path = os.path.join("data", safe_name)
    file_size = os.path.getsize(filepath)

    file_record = save_knowledge_file(
        chatbot_id=chatbot_id,
        file_name=safe_name,
        file_type="pdf",
        file_size=file_size,
        file_path=relative_pdf_path,
        upload_status="uploaded",
        processing_status="completed",
        match_status="unchecked"
    )

    file_id = file_record["id"]

    # --- PROCESS AND CHUNK PDF ---
    try:
        import fitz
        import logging
        from app.services.gemini_service import split_text_into_sections, generate_embedding
        from app.database.knowledge_chunk_repository import save_knowledge_chunk

        doc = fitz.open(filepath)
        lines = []
        for page in doc:
            blocks = page.get_text("blocks")
            blocks = sorted(blocks, key=lambda b: (b[1], b[0]))
            for block in blocks:
                text = block[4].strip()
                if text:
                    for line in text.splitlines():
                        clean_line = " ".join(line.split())
                        if clean_line:
                            lines.append(clean_line)
        pdf_text = "\n".join(lines)

        chunks = split_text_into_sections(pdf_text)
        
        logging.info(f"Processing {len(chunks)} chunks for database insertion...")
        
        for idx, chunk in enumerate(chunks):
            embedding = generate_embedding(chunk)
            if embedding:
                save_knowledge_chunk(
                    chatbot_id=chatbot_id,
                    file_id=file_id,
                    content=chunk,
                    embedding=embedding,
                    metadata={"chunk_index": idx}
                )
        logging.info("Successfully saved all chunks to Supabase.")
    except Exception as e:
        import logging
        logging.error(f"Failed to process PDF chunks: {e}")
    # -----------------------------

    set_active_knowledge_file(
        chatbot_id=chatbot_id,
        file_name=safe_name
    )

    update_chatbot_runtime({
        "draft_pdf_file_name": safe_name,
        "draft_pdf_path": relative_pdf_path,
        "last_match_result": None,
        "last_match_reason": "",
    }, chatbot_id)

    return {
        "file_name": safe_name,
        "file_path": filepath,
        "message": f"PDF {safe_name} uploaded and set as draft active"
    }


def list_uploaded_pdfs(chatbot_id):
    files = get_knowledge_files(chatbot_id=chatbot_id)

    return [
        {
            "file_name": file["file_name"],
            "name": file["file_name"],  # keep both for safety
            "size": file.get("file_size"),
            "status": "active" if file.get("is_active") else "available",
        }
        for file in files
    ]


def get_active_pdf(chatbot_id):
    active = get_active_knowledge_file(chatbot_id=chatbot_id)

    if not active:
        return {
            "file_name": "",
            "file_path": ""
        }

    return {
        "file_name": active.get("file_name", ""),
        "file_path": active.get("file_path", "")
    }


def set_active_pdf(file_name, chatbot_id):
    if not file_name:
        raise ValueError("File name is required")

    safe_name = secure_filename(file_name)
    target_path = os.path.join(DATA_FOLDER, safe_name)

    if not os.path.exists(target_path):
        raise ValueError("File not found")

    relative_pdf_path = os.path.join("data", safe_name)

    set_active_knowledge_file(
        chatbot_id=chatbot_id,
        file_name=safe_name
    )

    update_chatbot_runtime({
        "draft_pdf_file_name": safe_name,
        "draft_pdf_path": relative_pdf_path,
        "last_match_result": None,
        "last_match_reason": "",
    }, chatbot_id)

    return {
        "file_name": safe_name,
        "file_path": relative_pdf_path,
        "message": f"Draft active PDF set to {safe_name}"
    }


def delete_pdf_file(file_name, chatbot_id):
    if not file_name:
        raise ValueError("File name is required")

    safe_name = secure_filename(file_name)
    target_path = os.path.join(DATA_FOLDER, safe_name)

    if not os.path.exists(target_path):
        raise ValueError("File not found")

    active = get_active_knowledge_file(chatbot_id=chatbot_id)
    is_active_file = active and safe_name == active.get("file_name")

    os.remove(target_path)

    delete_knowledge_file_by_name(chatbot_id, safe_name)

    if is_active_file:
        update_chatbot_runtime({
            "draft_pdf_file_name": "",
            "draft_pdf_path": "",
            "deployed_pdf_file_name": "",
            "deployed_pdf_path": "",
            "last_match_result": None,
            "last_match_reason": "",
        }, chatbot_id)

    return {
        "file_name": safe_name,
        "message": f"PDF {safe_name} deleted successfully"
    }