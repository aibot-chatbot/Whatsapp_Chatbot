"""R2 is authoritative for document originals and their derived artifacts."""

import inspect
import io
import json
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
from flask import Flask, g

from app.database import knowledge_file_repository, knowledge_graph_repository
from app.services import document_storage_service as storage
from app.services import knowledge_service, match_service
from app.services.document_ocr_service import ExtractionResult


class MissingObject(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class MemoryR2:
    def __init__(self):
        self.objects = {}
        self.fail_read = self.fail_write = self.fail_delete = False

    def get_object(self, *, Bucket, Key):
        if self.fail_read:
            raise RuntimeError("private-provider-details")
        if Key not in self.objects:
            raise MissingObject()
        body = self.objects[Key]
        return {"Body": io.BytesIO(body), "ContentLength": len(body)}

    def put_object(self, *, Bucket, Key, Body, **kwargs):
        if self.fail_write:
            raise RuntimeError("private-provider-details")
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.read()

    def delete_object(self, *, Bucket, Key):
        if self.fail_delete:
            raise RuntimeError("private-provider-details")
        self.objects.pop(Key, None)


@pytest.fixture
def r2(tmp_path, monkeypatch):
    client = MemoryR2()
    monkeypatch.setenv("DOCUMENT_STORAGE_BACKEND", "r2")
    monkeypatch.setattr(storage, "_client_and_bucket", lambda: (client, "private-test"))
    monkeypatch.setattr(knowledge_service, "DATA_FOLDER", str(tmp_path))
    monkeypatch.setattr(knowledge_service, "get_knowledge_file_by_name_or_id", Mock(return_value={"id": 55}))
    return client


@pytest.mark.parametrize("reader,suffix,payload", [
    (knowledge_service.get_or_generate_readme, "readme.md", b"remote document text"),
    (knowledge_service.get_knowledge_history_logs, "history.json", b'[{"action":"remote edit"}]'),
])
def test_reads_restore_missing_local_cache(r2, tmp_path, reader, suffix, payload):
    name = f"bot_7_55_{suffix}"
    r2.objects[f"knowledge/{name}"] = payload

    assert "remote" in str(reader(7, 55))
    assert (tmp_path / name).read_bytes() == payload


@pytest.mark.parametrize("reader,suffix,payload", [
    (knowledge_service.get_or_generate_readme, "readme.md", b"stale private text"),
    (knowledge_service.get_knowledge_history_logs, "history.json", b'[{"action":"stale private text"}]'),
])
def test_remote_miss_never_serves_stale_cache(r2, tmp_path, monkeypatch, reader, suffix, payload):
    (tmp_path / f"bot_7_55_{suffix}").write_bytes(payload)
    monkeypatch.setattr(knowledge_service, "generate_and_save_knowledge_readme", Mock())

    assert "stale private text" not in str(reader(7, 55))


@pytest.mark.parametrize("reader", [knowledge_service.get_or_generate_readme, knowledge_service.get_knowledge_history_logs])
def test_remote_read_outage_is_not_a_cache_hit_or_empty_success(r2, reader):
    r2.fail_read = True
    with pytest.raises(storage.DocumentStorageError) as error:
        reader(7, 55)
    assert "private-provider-details" not in str(error.value)


def test_history_append_loads_remote_history_before_persisting(r2, tmp_path):
    key = "knowledge/bot_7_55_history.json"
    r2.objects[key] = b'[{"action":"remote edit"}]'
    (tmp_path / "bot_7_55_history.json").write_text('[{"action":"stale local edit"}]', encoding="utf-8")

    knowledge_service.log_knowledge_modification(7, 55, "new edit")

    assert [row["action"] for row in json.loads(r2.objects[key])] == ["remote edit", "new edit"]


def test_history_persistence_failure_raises(r2):
    r2.fail_write = True
    with pytest.raises(storage.DocumentStorageError):
        knowledge_service.log_knowledge_modification(7, 55, "new edit")
    assert r2.objects == {}


def _mock_readme_sources(monkeypatch):
    from app.database import db
    database = MagicMock()
    database.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": 55, "file_name": "guide.pdf"}
    ]
    database.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    monkeypatch.setattr(db, "supabase", database)
    monkeypatch.setattr(knowledge_file_repository, "get_active_pdf_knowledge_file", lambda _bot: {"id": 55})
    monkeypatch.setattr("app.database.knowledge_chunk_repository.get_chunks_by_file_for_chatbot", lambda *_args: [{"content": "document text"}])


def test_generated_readme_and_active_alias_are_both_persisted(r2, monkeypatch):
    _mock_readme_sources(monkeypatch)
    knowledge_service.generate_and_save_knowledge_readme(7, 55)
    assert b"document text" in r2.objects["knowledge/bot_7_55_readme.md"]
    assert r2.objects["knowledge/bot_7_readme.md"] == r2.objects["knowledge/bot_7_55_readme.md"]


def test_generated_readme_write_failure_raises(r2, monkeypatch):
    _mock_readme_sources(monkeypatch)
    r2.fail_write = True
    with pytest.raises(storage.DocumentStorageError):
        knowledge_service.generate_and_save_knowledge_readme(7, 55)


class Upload:
    filename = "guide.pdf"

    def save(self, path):
        Path(path).write_bytes(b"%PDF-1.4\nclient document")


def _mock_upload_processing(monkeypatch):
    for name in ("update_knowledge_file_status", "set_active_pdf_knowledge_file", "update_chatbot_runtime", "generate_and_save_knowledge_readme", "log_knowledge_modification"):
        monkeypatch.setattr(knowledge_service, name, Mock())
    monkeypatch.setattr(knowledge_service, "_index_pdf_chunks", Mock(return_value=(1, "", ExtractionResult(page_count=1, character_count=20))))
    monkeypatch.setattr("app.database.bot_repository.get_bot_by_id", Mock(return_value=None))


def test_original_is_persisted_before_metadata_and_success(r2, tmp_path, monkeypatch):
    _mock_upload_processing(monkeypatch)

    def save_metadata(**row):
        assert r2.objects["knowledge/" + row["file_name"]].startswith(b"%PDF-")
        return {"id": 55}

    monkeypatch.setattr(knowledge_service, "save_knowledge_file", save_metadata)
    result = knowledge_service.save_uploaded_pdf(Upload(), 7)
    assert result["status"] == "completed"
    assert (tmp_path / result["file_name"]).exists()


def test_uploaded_original_is_marked_with_the_owning_chatbot(r2, tmp_path, monkeypatch):
    """An unmarked object matches no tenant's retrieval filter, so scoping stays inert."""
    _mock_upload_processing(monkeypatch)
    monkeypatch.setattr(knowledge_service, "save_knowledge_file", Mock(return_value={"id": 55}))
    original_put = r2.put_object
    markers = []

    def capture(**kwargs):
        markers.append(kwargs.get("Metadata"))
        return original_put(**kwargs)

    monkeypatch.setattr(r2, "put_object", capture)
    knowledge_service.save_uploaded_pdf(Upload(), 7)

    assert markers == [{"chatbot_id": "7"}]


def test_original_remote_write_failure_leaves_no_metadata_or_local_upload(r2, tmp_path, monkeypatch):
    metadata = Mock()
    monkeypatch.setattr(knowledge_service, "save_knowledge_file", metadata)
    r2.fail_write = True

    with pytest.raises(storage.DocumentStorageError):
        knowledge_service.save_uploaded_pdf(Upload(), 7)

    metadata.assert_not_called()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_ambiguous_put_compensates_exact_key_and_always_removes_new_local_copy(r2, tmp_path, monkeypatch, cleanup_fails):
    metadata = Mock()
    monkeypatch.setattr(knowledge_service, "save_knowledge_file", metadata)
    r2.objects["knowledge/other-client.pdf"] = b"keep"
    r2.fail_delete = cleanup_fails

    def ambiguous_put(*, Key, Body, **kwargs):
        r2.objects[Key] = Body.read()
        raise RuntimeError("private-provider-details")

    monkeypatch.setattr(r2, "put_object", ambiguous_put)
    with pytest.raises(storage.DocumentStorageError) as error:
        knowledge_service.save_uploaded_pdf(Upload(), 7)

    assert "private-provider-details" not in str(error.value)
    metadata.assert_not_called()
    assert list(tmp_path.iterdir()) == []
    assert r2.objects["knowledge/other-client.pdf"] == b"keep"
    assert len(r2.objects) == (2 if cleanup_fails else 1)


def test_rejected_signature_does_not_attempt_remote_compensation(r2, tmp_path, monkeypatch):
    upload = Upload()
    upload.save = lambda path: Path(path).write_bytes(b"invalid PDF")
    delete_remote = Mock()
    monkeypatch.setattr(r2, "delete_object", delete_remote)
    with pytest.raises(ValueError):
        knowledge_service.save_uploaded_pdf(upload, 7)
    delete_remote.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_metadata_failure_compensates_only_the_new_original(r2, tmp_path, monkeypatch):
    r2.objects["knowledge/other-client.pdf"] = b"keep"
    monkeypatch.setattr(knowledge_service, "save_knowledge_file", Mock(side_effect=RuntimeError("metadata failed")))

    with pytest.raises(RuntimeError, match="metadata failed"):
        knowledge_service.save_uploaded_pdf(Upload(), 7)

    assert r2.objects == {"knowledge/other-client.pdf": b"keep"}
    assert list(tmp_path.iterdir()) == []


def test_metadata_failure_removes_new_local_copy_even_if_remote_cleanup_fails(r2, tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge_service, "save_knowledge_file", Mock(side_effect=RuntimeError("metadata failed")))
    r2.fail_delete = True
    with pytest.raises(storage.DocumentStorageError):
        knowledge_service.save_uploaded_pdf(Upload(), 7)
    assert list(tmp_path.iterdir()) == []
    assert len(r2.objects) == 1  # Remote cleanup failed; no success or erasure claim.


def test_generated_payload_does_not_reopen_a_concurrently_replaced_cache(r2, tmp_path, monkeypatch):
    _mock_readme_sources(monkeypatch)
    original_put = r2.put_object

    def replace_cache_before_put(*, Key, Body, **kwargs):
        (tmp_path / Key.removeprefix("knowledge/")).write_bytes(b"stale cache replacement")
        assert isinstance(Body, bytes)
        return original_put(Key=Key, Body=Body, **kwargs)

    monkeypatch.setattr(r2, "put_object", replace_cache_before_put)
    knowledge_service.generate_and_save_knowledge_readme(7, 55)
    assert b"document text" in r2.objects["knowledge/bot_7_55_readme.md"]
    assert b"stale cache replacement" not in r2.objects["knowledge/bot_7_55_readme.md"]


@pytest.mark.parametrize("failed_step", ["generate_and_save_knowledge_readme", "log_knowledge_modification"])
def test_derived_storage_failure_does_not_report_upload_success(r2, monkeypatch, failed_step):
    _mock_upload_processing(monkeypatch)
    monkeypatch.setattr(knowledge_service, "save_knowledge_file", Mock(return_value={"id": 55}))
    monkeypatch.setattr(knowledge_service, failed_step, Mock(side_effect=storage.DocumentStorageError("storage failed")))

    with pytest.raises(storage.DocumentStorageError):
        knowledge_service.save_uploaded_pdf(Upload(), 7)


def _mock_existing_document(monkeypatch, tmp_path):
    record = {"id": 55, "file_name": "bot_7_guide.pdf", "file_path": str(tmp_path / "bot_7_guide.pdf"), "file_type": "pdf"}
    monkeypatch.setattr(knowledge_service, "get_knowledge_file_by_name_or_id", Mock(return_value=record))
    monkeypatch.setattr(knowledge_service, "get_active_knowledge_file", Mock(return_value={"id": 55}))
    monkeypatch.setattr(knowledge_service, "get_chunks_by_file_for_chatbot", Mock(return_value=[]))
    monkeypatch.setattr(knowledge_graph_repository, "delete_graph_by_file_id", Mock())
    monkeypatch.setattr(knowledge_service, "update_chatbot_runtime", Mock())
    for name in ("delete_chunks_by_file_for_chatbot", "delete_knowledge_file_by_id", "set_active_pdf_knowledge_file", "generate_and_save_knowledge_readme", "log_knowledge_modification"):
        monkeypatch.setattr(knowledge_service, name, Mock())
    return record


def test_remote_delete_failure_keeps_metadata_for_retry(r2, tmp_path, monkeypatch):
    _mock_existing_document(monkeypatch, tmp_path)
    r2.fail_delete = True

    with pytest.raises(storage.DocumentStorageError):
        knowledge_service.delete_pdf_file("bot_7_guide.pdf", 7)

    knowledge_service.delete_knowledge_file_by_id.assert_not_called()
    knowledge_service.delete_chunks_by_file_for_chatbot.assert_not_called()


def test_delete_cleans_exact_remote_original_and_derived_objects(r2, tmp_path, monkeypatch):
    _mock_existing_document(monkeypatch, tmp_path)
    for name in ("bot_7_guide.pdf", "bot_7_55_readme.md", "bot_7_55_history.json", "bot_7_readme.md", "bot_8_55_readme.md"):
        r2.objects["knowledge/" + name] = b"content"

    knowledge_service.delete_pdf_file("bot_7_guide.pdf", 7)

    assert r2.objects == {"knowledge/bot_8_55_readme.md": b"content"}
    knowledge_service.delete_knowledge_file_by_id.assert_called_once_with(7, 55)


def test_active_selection_restores_original_from_r2(r2, tmp_path, monkeypatch):
    _mock_existing_document(monkeypatch, tmp_path)
    r2.objects["knowledge/bot_7_guide.pdf"] = b"%PDF-1.4\nremote"
    knowledge_service.set_active_pdf("bot_7_guide.pdf", 7)
    assert (tmp_path / "bot_7_guide.pdf").read_bytes().endswith(b"remote")
    knowledge_service.set_active_pdf_knowledge_file.assert_called_once_with(chatbot_id=7, file_id=55)


def test_active_selection_rejects_missing_remote_original_despite_local_cache(r2, tmp_path, monkeypatch):
    _mock_existing_document(monkeypatch, tmp_path)
    (tmp_path / "bot_7_guide.pdf").write_bytes(b"stale PDF")
    with pytest.raises(ValueError, match="stored PDF is unavailable"):
        knowledge_service.set_active_pdf("bot_7_guide.pdf", 7)
    knowledge_service.set_active_pdf_knowledge_file.assert_not_called()


def test_ocr_restores_original_before_parsing(r2, tmp_path, monkeypatch):
    path = tmp_path / "guide.pdf"
    r2.objects["knowledge/guide.pdf"] = b"%PDF-1.4\nremote"
    extraction = Mock(return_value=ExtractionResult(error="no readable text"))
    monkeypatch.setattr("app.services.document_ocr_service.extract_pdf_markdown", extraction)
    knowledge_service._index_pdf_chunks(str(path), 7, 55)
    extraction.assert_called_once_with(str(path))
    assert path.read_bytes().endswith(b"remote")


@pytest.mark.parametrize("stored_path", ["data/guide.pdf", "data\\guide.pdf"])
def test_match_preview_restores_original_and_never_reads_stale_remote_miss(r2, tmp_path, monkeypatch, stored_path):
    r2.objects["knowledge/guide.pdf"] = b"%PDF-1.4\nremote"
    pdf = MagicMock()
    pdf.__enter__.return_value = [Mock(get_text=Mock(return_value="remote preview"))]
    open_pdf = Mock(return_value=pdf)
    monkeypatch.setattr(match_service.fitz, "open", open_pdf, raising=False)

    assert match_service.extract_pdf_preview(stored_path) == "remote preview"
    del r2.objects["knowledge/guide.pdf"]
    open_pdf.reset_mock()
    assert match_service.extract_pdf_preview(stored_path) == ""
    open_pdf.assert_not_called()


@pytest.mark.parametrize("function,path,failed_step", [
    ("get_knowledge_readme", "/?chatbot_id=7&file_id=55", "get_or_generate_readme"),
    ("get_knowledge_history", "/?chatbot_id=7&file_id=55", "get_knowledge_history_logs"),
    ("save_graph_node", "/?chatbot_id=7", "generate_and_save_knowledge_readme"),
])
def test_route_storage_failures_are_safe_errors(r2, monkeypatch, function, path, failed_step):
    from app.routes import knowledge_routes
    app = Flask(__name__)
    app.add_url_rule("/", view_func=inspect.unwrap(getattr(knowledge_routes, function)), methods=["GET", "POST"])
    app.register_error_handler(storage.DocumentStorageError, knowledge_routes.handle_document_storage_error)
    monkeypatch.setattr(knowledge_routes, "verify_chatbot_access", Mock())
    monkeypatch.setattr(knowledge_file_repository, "get_active_pdf_knowledge_file", Mock(return_value={"id": 55}))
    monkeypatch.setattr(knowledge_graph_repository, "upsert_node", Mock(return_value={"name": "node"}))
    monkeypatch.setattr(knowledge_service, failed_step, Mock(side_effect=storage.DocumentStorageError("private-provider-details")))

    @app.before_request
    def identity():
        g.company_id = 42

    with app.test_client() as client:
        response = client.post(path, json={"name": "node", "label": "Product"}) if function == "save_graph_node" else client.get(path)

    assert response.status_code == 503
    assert "private-provider-details" not in response.get_data(as_text=True)
    assert response.get_json()["status"] == "error"


def test_local_storage_remains_the_default(tmp_path, monkeypatch):
    monkeypatch.delenv("DOCUMENT_STORAGE_BACKEND", raising=False)
    monkeypatch.setattr(knowledge_service, "DATA_FOLDER", str(tmp_path))
    monkeypatch.setattr(knowledge_service, "get_knowledge_file_by_name_or_id", Mock(return_value={"id": 55}))
    remote = Mock(side_effect=AssertionError("local mode must not contact R2"))
    monkeypatch.setattr(storage, "_client_and_bucket", remote)
    (tmp_path / "bot_7_55_readme.md").write_text("local document", encoding="utf-8")
    assert knowledge_service.get_or_generate_readme(7, 55) == "local document"
    remote.assert_not_called()
