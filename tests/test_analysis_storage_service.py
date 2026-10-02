from uuid import uuid4
import pytest
from app.services import analysis_storage_service as service


def test_private_report_scope_version_and_integrity(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("DOCUMENT_STORAGE_BACKEND", "local")
    report, lease = str(uuid4()), str(uuid4())
    manifest = service.store_export(company_id=1, chatbot_id=2, report_id=report, lease_token=lease, format="pdf", content=b"report")
    assert service.read_export(company_id=1, chatbot_id=2, report_id=report, manifest=manifest, format="pdf") == b"report"
    with pytest.raises(Exception):
        service.read_export(company_id=3, chatbot_id=2, report_id=report, manifest=manifest, format="pdf")
    (tmp_path / "1" / "2" / report / lease / "report.pdf").write_bytes(b"changed")
    with pytest.raises(service.storage.DocumentStorageError):
        service.read_export(company_id=1, chatbot_id=2, report_id=report, manifest=manifest, format="pdf")
    with pytest.raises(ValueError):
        service._path(1, 2, "../media", lease, "pdf")
