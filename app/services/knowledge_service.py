import os
from werkzeug.utils import secure_filename

from app.services import gemini_service
from app.services.gemini_service import update_pdf_path


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
    update_pdf_path(relative_pdf_path)

    return {
        "file_name": safe_name,
        "file_path": filepath,
        "message": f"PDF {safe_name} updated"
    }

def list_uploaded_pdfs():
    os.makedirs(DATA_FOLDER, exist_ok=True)

    pdf_files = []
    for filename in os.listdir(DATA_FOLDER):
        if filename.lower().endswith(".pdf"):
            pdf_files.append({
                "file_name": filename
            })

    pdf_files.sort(key=lambda x: x["file_name"].lower())
    return pdf_files

def get_active_pdf():
    active_pdf_path = gemini_service.PDF_PATH
    active_pdf_name = os.path.basename(active_pdf_path)

    return {
        "file_name": active_pdf_name,
        "file_path": active_pdf_path
    }

def set_active_pdf(file_name):
    if not file_name:
        raise ValueError("File name is required")

    safe_name = secure_filename(file_name)
    target_path = os.path.join(DATA_FOLDER, safe_name)

    if not os.path.exists(target_path):
        raise ValueError("File not found")

    relative_pdf_path = os.path.join("data", safe_name)
    update_pdf_path(relative_pdf_path)

    return {
        "file_name": safe_name,
        "file_path": relative_pdf_path,
        "message": f"Active PDF set to {safe_name}"
    }

def delete_pdf_file(file_name):
    if not file_name:
        raise ValueError("File name is required")

    safe_name = secure_filename(file_name)
    target_path = os.path.join(DATA_FOLDER, safe_name)

    if not os.path.exists(target_path):
        raise ValueError("File not found")

    active_pdf_name = os.path.basename(gemini_service.PDF_PATH)

    if safe_name == active_pdf_name:
        raise ValueError("Cannot delete the currently active PDF")

    os.remove(target_path)

    return {
        "file_name": safe_name,
        "message": f"PDF {safe_name} deleted successfully"
    }