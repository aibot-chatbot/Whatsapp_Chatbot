"""Private report artifacts; only a fenced DB manifest makes a version downloadable."""
import hashlib
import os
from pathlib import Path
from uuid import UUID

from app.services import document_storage_service as storage

FORMATS = {"pdf": "application/pdf", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "json": "application/json"}


def _path(company_id, chatbot_id, report_id, version, format):
    if any(type(value) is not int or value <= 0 for value in (company_id, chatbot_id)):
        raise ValueError("Invalid report scope.")
    if format not in FORMATS:
        raise ValueError("Unsupported report format.")
    report_id, version = str(UUID(str(report_id))), str(UUID(str(version)))
    root = Path(os.getenv("REPORT_STORAGE_ROOT", str(Path(__file__).resolve().parents[2] / "data" / "reports")))
    path = root / str(company_id) / str(chatbot_id) / report_id / version / ("report." + format)
    return root, path


def store_export(*, company_id, chatbot_id, report_id, lease_token, format, content):
    root, path = _path(company_id, chatbot_id, report_id, lease_token, format)
    storage.write_file(path, content, root=root, namespace="reports", company_id=company_id, chatbot_id=chatbot_id)
    return {"format": format, "version": str(UUID(str(lease_token))), "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}


def read_export(*, company_id, chatbot_id, report_id, manifest, format):
    """Caller must freshly authorize the report. Never accept a client path or URL."""
    if not isinstance(manifest, dict) or manifest.get("format") != format:
        raise ValueError("Report file is not available.")
    root, path = _path(company_id, chatbot_id, report_id, manifest.get("version"), format)
    storage.materialize_file(path, root=root, namespace="reports")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != manifest.get("sha256") or len(content) != manifest.get("size"):
        raise storage.DocumentStorageError("Report file integrity check failed.")
    return content
