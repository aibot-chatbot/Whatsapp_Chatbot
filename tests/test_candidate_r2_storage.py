"""Candidate lifecycle uses authoritative private storage with explicit failure handling."""

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from werkzeug.datastructures import FileStorage

from app.services import pdf_relevance_validation_service as svc


class StorageFailure(RuntimeError):
    pass


@pytest.fixture
def storage(monkeypatch, tmp_path):
    root = tmp_path / "data"
    candidates = root / "_pdf_candidates"
    candidates.mkdir(parents=True)
    objects = {}

    def key(path, *, root, namespace):
        return namespace + "/" + Path(path).relative_to(root).as_posix()

    def persist(path, **kwargs):
        objects[key(path, **kwargs)] = Path(path).read_bytes()
        return str(path)

    def materialize(path, **kwargs):
        object_key = key(path, **kwargs)
        if object_key not in objects:
            raise FileNotFoundError("Candidate object missing")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(objects[object_key])
        return str(path)

    def delete(path, **kwargs):
        objects.pop(key(path, **kwargs), None)
        Path(path).unlink(missing_ok=True)

    fake = SimpleNamespace(
        root=root, candidates=candidates, objects=objects,
        r2_enabled=lambda: True, DocumentStorageError=StorageFailure,
        persist_file=Mock(side_effect=persist), materialize_file=Mock(side_effect=materialize),
        delete_file=Mock(side_effect=delete),
    )
    monkeypatch.setattr(svc, "document_storage", fake, raising=False)
    monkeypatch.setattr(svc, "DATA_FOLDER", str(root))
    monkeypatch.setattr(svc, "CANDIDATE_DATA_FOLDER", str(candidates))

    def no_network(*args, **kwargs):
        raise AssertionError("Candidate tests must not access external services")

    monkeypatch.setattr("requests.sessions.Session.request", no_network)
    monkeypatch.setattr("httpx.Client.send", no_network)
    return fake


def _validate():
    return svc.validate_supporting_pdf_candidate(
        FileStorage(io.BytesIO(b"%PDF-1.4\nsynthetic candidate"), filename="support.pdf"),
        chatbot_id=29, company_id=7, created_by_user_id=17, threshold=0.5,
        primary_file={"id": 77, "file_name": "primary.pdf", "file_type": "pdf"},
    )


def test_remote_write_failure_leaves_no_candidate_metadata_or_local_file(storage, monkeypatch):
    storage.persist_file.side_effect = StorageFailure("Private storage unavailable")
    insert = Mock(side_effect=AssertionError("metadata must not precede remote persistence"))
    monkeypatch.setattr(svc, "create_candidate", insert)

    with pytest.raises(StorageFailure):
        _validate()

    insert.assert_not_called()
    assert not list(storage.candidates.rglob("*.pdf"))
    assert not storage.objects


def test_invalid_candidate_is_not_persisted_or_recorded(storage, monkeypatch):
    insert = Mock()
    monkeypatch.setattr(svc, "create_candidate", insert)

    with pytest.raises(ValueError, match="Invalid PDF content"):
        svc.validate_supporting_pdf_candidate(
            FileStorage(io.BytesIO(b"<html>not a PDF</html>"), filename="disguised.pdf"),
            chatbot_id=29, company_id=7, created_by_user_id=17, threshold=0.5,
            primary_file={"id": 77, "file_name": "primary.pdf", "file_type": "pdf"},
        )

    insert.assert_not_called()
    storage.persist_file.assert_not_called()
    storage.delete_file.assert_not_called()
    assert not list(storage.candidates.rglob("*.pdf"))


def test_metadata_failure_compensates_persisted_remote_and_local_copy(storage, monkeypatch):
    def insert(_row):
        assert len(storage.objects) == 1
        raise RuntimeError("metadata unavailable")

    monkeypatch.setattr(svc, "create_candidate", insert)
    with pytest.raises(RuntimeError, match="metadata unavailable"):
        _validate()

    storage.persist_file.assert_called_once()
    storage.delete_file.assert_called_once()
    assert not storage.objects
    assert not list(storage.candidates.rglob("*.pdf"))


def test_failed_compensation_is_reported_and_new_local_copy_is_removed(storage, monkeypatch):
    monkeypatch.setattr(svc, "create_candidate", Mock(side_effect=RuntimeError("metadata unavailable")))
    storage.delete_file.side_effect = StorageFailure("Deletion unavailable")

    with pytest.raises(StorageFailure, match="Deletion unavailable"):
        _validate()

    assert len(storage.objects) == 1  # Do not claim that an uncertain remote write was erased.
    assert not list(storage.candidates.rglob("*.pdf"))


@pytest.fixture
def candidate(storage, monkeypatch):
    path = storage.candidates / "7" / "29" / "candidate-1.pdf"
    row = {
        "id": "candidate-1", "chatbot_id": 29, "company_id": 7,
        "validation_status": "validated_passed", "passed": True,
        "primary_file_id": 77, "safe_file_name": "support.pdf", "file_size": 30,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "temp_file_path": str(path), "duplicate_status": "none",
    }
    monkeypatch.setattr(svc, "get_candidate", lambda *args: row)
    monkeypatch.setattr(svc, "get_knowledge_file_by_source_candidate", lambda *args: None)
    monkeypatch.setattr(svc, "_assert_current_primary_matches_candidate", lambda *args: None)
    monkeypatch.setattr(svc, "can_upload_knowledge_file", lambda *args: None)
    monkeypatch.setattr(svc, "can_upload_knowledge_storage", lambda *args: None)
    monkeypatch.setattr(svc, "claim_candidate_for_confirmation", lambda *args: row)
    monkeypatch.setattr(svc, "mark_candidate_ingested", lambda *args: {
        **row, "validation_status": "ingested_supporting", "ingested_knowledge_file_id": 88})
    monkeypatch.setattr(svc, "mark_candidate_ingest_failed", Mock())
    return row


def test_confirmation_restores_candidate_before_copying_to_knowledge(storage, candidate, monkeypatch):
    payload = b"%PDF-1.4\nremote authoritative candidate"
    storage.objects["knowledge/_pdf_candidates/7/29/candidate-1.pdf"] = payload

    def save(upload, chatbot_id, **kwargs):
        assert chatbot_id == 29
        assert kwargs == {"target_role": "supporting", "source_pdf_candidate_id": "candidate-1"}
        copied = storage.root / "confirmed.pdf"
        upload.save(copied)
        assert copied.read_bytes() == payload
        svc.validate_saved_pdf(copied)
        return {"status": "completed", "file_id": 88, "file_name": "confirmed.pdf"}

    monkeypatch.setattr(svc, "save_uploaded_pdf", save)
    result = svc.confirm_supporting_pdf_candidate("candidate-1", 29, 7)

    assert result["validation_status"] == "ingested_supporting"
    storage.materialize_file.assert_called_once_with(
        candidate["temp_file_path"], root=str(storage.root), namespace="knowledge")
    assert not storage.objects
    assert not Path(candidate["temp_file_path"]).exists()


def test_missing_remote_candidate_rejects_stale_local_cache(storage, candidate, monkeypatch):
    path = Path(candidate["temp_file_path"])
    path.parent.mkdir(parents=True)
    path.write_bytes(b"%PDF-1.4\nstale cache")
    save = Mock()
    monkeypatch.setattr(svc, "save_uploaded_pdf", save)

    with pytest.raises(svc.CandidateStateError) as raised:
        svc.confirm_supporting_pdf_candidate("candidate-1", 29, 7)

    assert raised.value.code == "candidate_file_missing"
    save.assert_not_called()
    svc.mark_candidate_ingest_failed.assert_called_once_with(
        "candidate-1", 29, 7, "candidate_file_missing", "Candidate file is missing.")


def test_remote_read_outage_releases_confirmation_claim_as_failed(storage, candidate, monkeypatch):
    storage.materialize_file.side_effect = StorageFailure("Private storage unavailable")
    save = Mock()
    monkeypatch.setattr(svc, "save_uploaded_pdf", save)

    with pytest.raises(StorageFailure):
        svc.confirm_supporting_pdf_candidate("candidate-1", 29, 7)

    save.assert_not_called()
    assert svc.mark_candidate_ingest_failed.call_args.args[3] == "candidate_storage_unavailable"


def test_failed_cancel_deletion_is_not_reported_as_erased_and_can_retry(storage, candidate, monkeypatch):
    candidate["validation_status"] = "cancelled"
    path = Path(candidate["temp_file_path"])
    path.parent.mkdir(parents=True)
    path.write_bytes(b"%PDF-1.4\nprivate candidate")
    storage.persist_file(str(path), root=str(storage.root), namespace="knowledge")
    deletion = storage.delete_file.side_effect
    storage.delete_file.side_effect = StorageFailure("Deletion unavailable")

    with pytest.raises(StorageFailure):
        svc.cancel_pdf_candidate("candidate-1", 29, 7)

    assert storage.objects and path.exists()
    storage.delete_file.side_effect = deletion
    assert svc.cancel_pdf_candidate("candidate-1", 29, 7)["cancelled"] is True
    assert not storage.objects and not path.exists()


def test_already_ingested_confirmation_retries_remote_candidate_cleanup(storage, candidate, monkeypatch):
    candidate.update(validation_status="ingested_supporting", ingested_knowledge_file_id=88)
    storage.objects["knowledge/_pdf_candidates/7/29/candidate-1.pdf"] = b"%PDF-1.4\nprivate candidate"
    save = Mock()
    monkeypatch.setattr(svc, "save_uploaded_pdf", save)
    storage.delete_file.side_effect = StorageFailure("Deletion unavailable")

    with pytest.raises(StorageFailure):
        svc.confirm_supporting_pdf_candidate("candidate-1", 29, 7)

    save.assert_not_called()
    svc.mark_candidate_ingest_failed.assert_not_called()
    assert storage.objects


def test_cleanup_failure_after_ingestion_does_not_mark_ingestion_failed(storage, candidate, monkeypatch):
    storage.objects["knowledge/_pdf_candidates/7/29/candidate-1.pdf"] = b"%PDF-1.4\nprivate candidate"
    monkeypatch.setattr(svc, "save_uploaded_pdf", Mock(return_value={"status": "completed", "file_id": 88}))
    recorded = Mock(return_value={**candidate, "validation_status": "ingested_supporting"})
    monkeypatch.setattr(svc, "mark_candidate_ingested", recorded)
    storage.delete_file.side_effect = StorageFailure("Deletion unavailable")

    with pytest.raises(StorageFailure):
        svc.confirm_supporting_pdf_candidate("candidate-1", 29, 7)

    recorded.assert_called_once_with("candidate-1", 29, 7, 88)
    svc.mark_candidate_ingest_failed.assert_not_called()
    assert storage.objects
