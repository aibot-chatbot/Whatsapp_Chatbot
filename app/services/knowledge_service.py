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


def save_uploaded_pdf(file):
    if not file:
        raise ValueError("No file provided")

    if file.filename == "":
        raise ValueError("No selected file")

    if not file.filename.lower().endswith(".pdf"):
        raise ValueError("Invalid file type")

    os.makedirs(DATA_FOLDER, exist_ok=True)

    safe_name = secure_filename(file.filename)
    filepath = os.path.join(DATA_FOLDER, safe_name)
    file.save(filepath)

    relative_pdf_path = os.path.join("data", safe_name)
    file_size = os.path.getsize(filepath)

    save_knowledge_file(
        chatbot_id=1,  # temporary for now
        file_name=safe_name,
        file_type="pdf",
        file_size=file_size,
        file_path=relative_pdf_path,
        upload_status="uploaded",
        processing_status="completed",
        match_status="unchecked"
    )

    set_active_knowledge_file(
        chatbot_id=1,
        file_name=safe_name
    )

    update_chatbot_runtime({
        "draft_pdf_file_name": safe_name,
        "draft_pdf_path": relative_pdf_path,
        "last_match_result": None,
        "last_match_reason": "",
    })

    return {
        "file_name": safe_name,
        "file_path": filepath,
        "message": f"PDF {safe_name} uploaded and set as draft active"
    }


def list_uploaded_pdfs():
    files = get_knowledge_files(chatbot_id=1)

    return [
        {
            "file_name": file["file_name"],
            "name": file["file_name"],  # keep both for safety
            "size": file.get("file_size"),
            "status": "active" if file.get("is_active") else "available",
        }
        for file in files
    ]


def get_active_pdf():
    active = get_active_knowledge_file(chatbot_id=1)

    if not active:
        return {
            "file_name": "",
            "file_path": ""
        }

    return {
        "file_name": active.get("file_name", ""),
        "file_path": active.get("file_path", "")
    }


def set_active_pdf(file_name):
    if not file_name:
        raise ValueError("File name is required")

    safe_name = secure_filename(file_name)
    target_path = os.path.join(DATA_FOLDER, safe_name)

    if not os.path.exists(target_path):
        raise ValueError("File not found")

    relative_pdf_path = os.path.join("data", safe_name)

    set_active_knowledge_file(
        chatbot_id=1,
        file_name=safe_name
    )

    update_chatbot_runtime({
        "draft_pdf_file_name": safe_name,
        "draft_pdf_path": relative_pdf_path,
        "last_match_result": None,
        "last_match_reason": "",
    })

    return {
        "file_name": safe_name,
        "file_path": relative_pdf_path,
        "message": f"Draft active PDF set to {safe_name}"
    }


def delete_pdf_file(file_name):
    if not file_name:
        raise ValueError("File name is required")

    safe_name = secure_filename(file_name)
    target_path = os.path.join(DATA_FOLDER, safe_name)

    if not os.path.exists(target_path):
        raise ValueError("File not found")

    active = get_active_knowledge_file(chatbot_id=1)

    if active and safe_name == active.get("file_name"):
        raise ValueError("Cannot delete the currently active PDF")

    os.remove(target_path)

    delete_knowledge_file_by_name(safe_name)

    return {
        "file_name": safe_name,
        "message": f"PDF {safe_name} deleted successfully"
    }