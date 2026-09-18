"""Storage checks use synthetic files and an in-memory S3 stub only."""

import io
from unittest.mock import Mock

import pytest

from app.services import document_storage_service as storage


class S3Error(Exception):
    def __init__(self, code):
        super().__init__("private provider details must not escape")
        self.response = {"Error": {"Code": code}}


@pytest.fixture
def r2(monkeypatch):
    monkeypatch.setenv("DOCUMENT_STORAGE_BACKEND", "r2")
    monkeypatch.setenv("R2_ACCOUNT_ID", "a" * 32)
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "synthetic-access")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "synthetic-secret")
    monkeypatch.setenv("R2_BUCKET_UPLOADS", "private-test-documents")
    client = Mock()
    monkeypatch.setattr(storage, "_create_client", lambda *args: client)
    return client


def test_local_default_retains_existing_file_lifecycle(monkeypatch, tmp_path):
    monkeypatch.delenv("DOCUMENT_STORAGE_BACKEND", raising=False)
    client = Mock(side_effect=AssertionError("local must not create an S3 client"))
    monkeypatch.setattr(storage, "_create_client", client)
    path = tmp_path / "existing.pdf"
    path.write_bytes(b"%PDF-synthetic")
    assert not storage.r2_enabled()
    assert storage.persist_file(path, root=tmp_path, namespace="knowledge") == str(path.resolve())
    assert storage.materialize_file(path, root=tmp_path, namespace="knowledge") == str(path.resolve())
    assert storage.file_exists(path, root=tmp_path, namespace="knowledge")
    storage.delete_file(path, root=tmp_path, namespace="knowledge")
    storage.delete_file(path, root=tmp_path, namespace="knowledge")
    assert not path.exists()
    with pytest.raises(FileNotFoundError):
        storage.materialize_file(path, root=tmp_path, namespace="knowledge")
    client.assert_not_called()


@pytest.mark.parametrize("name", ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_UPLOADS"])
def test_enabled_backend_requires_explicit_configuration(r2, monkeypatch, name):
    monkeypatch.delenv(name)
    with pytest.raises(storage.DocumentStorageError, match=name):
        storage.validate_storage_configuration()
    assert not r2.mock_calls


@pytest.mark.parametrize("name,value", [
    ("DOCUMENT_STORAGE_BACKEND", "unknown"),
    ("R2_ACCOUNT_ID", "evil.example/path"),
    ("R2_BUCKET_UPLOADS", "../public"),
])
def test_invalid_backend_configuration_fails_closed(r2, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(storage.DocumentStorageError):
        storage.validate_storage_configuration()
    assert not r2.mock_calls


def test_application_startup_rejects_incomplete_r2_configuration(r2, monkeypatch):
    from flask import Flask
    from app import config

    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    monkeypatch.delenv("R2_SECRET_ACCESS_KEY")
    with pytest.raises(storage.DocumentStorageError, match="R2_SECRET_ACCESS_KEY"):
        config.load_configurations(Flask(__name__))
    assert not r2.mock_calls


def test_s3_client_uses_explicit_tls_endpoint_and_bounded_sdk_retries(monkeypatch):
    import boto3

    create = Mock()
    monkeypatch.setattr(boto3, "client", create)
    storage._create_client.cache_clear()
    try:
        storage._create_client("a" * 32, "synthetic-access", "synthetic-secret")
        arguments = create.call_args.kwargs
        assert arguments["endpoint_url"] == "https://" + "a" * 32 + ".r2.cloudflarestorage.com"
        assert arguments["region_name"] == "auto"
        assert arguments["aws_access_key_id"] == "synthetic-access"
        assert arguments["aws_secret_access_key"] == "synthetic-secret"
        assert arguments["config"].signature_version == "s3v4"
        assert arguments["config"].retries == {"mode": "standard", "total_max_attempts": 3}
        assert arguments["config"].read_timeout == 30
        assert arguments["config"].connect_timeout == 10
    finally:
        storage._create_client.cache_clear()


@pytest.mark.parametrize("operation", [storage.persist_file, storage.materialize_file, storage.file_exists, storage.delete_file])
@pytest.mark.parametrize("invalid", ["outside", "root", "stream", "namespace"])
def test_storage_rejects_escaping_paths_before_any_network_call(r2, tmp_path, operation, invalid):
    root = tmp_path / "data"
    root.mkdir()
    path = {"outside": tmp_path / "secret.pdf", "root": root,
            "stream": root / "document.pdf:secret", "namespace": root / "document.pdf"}[invalid]
    with pytest.raises(storage.DocumentStorageError):
        operation(path, root=root, namespace="unknown" if invalid == "namespace" else "knowledge")
    assert not r2.mock_calls


def test_persist_uses_contained_stable_private_key(r2, tmp_path):
    path = tmp_path / "_pdf_candidates" / "7" / "42" / "candidate.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"%PDF-synthetic")
    observed = {}

    def put(**kwargs):
        observed.update(kwargs)
        observed["bytes"] = kwargs["Body"].read()

    r2.put_object.side_effect = put
    storage.persist_file(path, root=tmp_path, namespace="knowledge")
    assert observed["Key"] == "knowledge/_pdf_candidates/7/42/candidate.pdf"
    assert observed["Bucket"] == "private-test-documents"
    assert observed["bytes"] == b"%PDF-synthetic"
    assert observed["ContentLength"] == len(observed["bytes"])
    assert observed["ContentType"] == "application/pdf"
    assert observed["CacheControl"] == "private, no-store"
    assert "ACL" not in observed


def test_failed_upload_does_not_report_success(r2, tmp_path):
    path = tmp_path / "document.pdf"
    path.write_bytes(b"%PDF-synthetic")
    r2.put_object.side_effect = S3Error("AccessDenied")
    with pytest.raises(storage.DocumentStorageError, match="could not be stored") as caught:
        storage.persist_file(path, root=tmp_path, namespace="knowledge")
    assert "private provider" not in str(caught.value)


def test_generated_write_uploads_supplied_content_despite_concurrent_cache_replacement(r2, tmp_path):
    path = tmp_path / "bot_42_7_readme.md"
    path.write_bytes(b"old cache")
    generated = b"new generated document"

    def put(**kwargs):
        path.write_bytes(b"cache replaced by a concurrent download")
        assert kwargs["Body"] == generated
        assert kwargs["Key"] == "knowledge/bot_42_7_readme.md"
        assert kwargs["CacheControl"] == "private, no-store"

    r2.put_object.side_effect = put
    storage.write_file(path, generated, root=tmp_path, namespace="knowledge")
    assert path.read_bytes() == generated
    assert not list(tmp_path.glob(".r2-*"))


def test_generated_write_failure_does_not_replace_complete_local_copy(r2, tmp_path):
    path = tmp_path / "bot_42_7_history.json"
    path.write_bytes(b"old cache")
    r2.put_object.side_effect = S3Error("AccessDenied")
    with pytest.raises(storage.DocumentStorageError):
        storage.write_file(path, b"new", root=tmp_path, namespace="knowledge")
    assert path.read_bytes() == b"old cache"


def test_generated_local_write_uses_same_atomic_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCUMENT_STORAGE_BACKEND", "local")
    client = Mock(side_effect=AssertionError("local must not contact S3"))
    monkeypatch.setattr(storage, "_create_client", client)
    path = tmp_path / "nested" / "history.json"
    storage.write_file(path, b"[]", root=tmp_path, namespace="knowledge")
    assert path.read_bytes() == b"[]"
    assert not list(tmp_path.rglob(".r2-*"))
    client.assert_not_called()


def test_generated_write_rejects_oversized_content_before_storage(r2, monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "MAX_UPLOAD_BYTES", 4)
    with pytest.raises(storage.DocumentStorageError):
        storage.write_file(tmp_path / "summary.md", b"12345", root=tmp_path, namespace="knowledge")
    r2.put_object.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_oversized_upload_never_reaches_s3(r2, monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "MAX_UPLOAD_BYTES", 4)
    path = tmp_path / "document.pdf"
    path.write_bytes(b"12345")
    with pytest.raises(storage.DocumentStorageError, match="size limit"):
        storage.persist_file(path, root=tmp_path, namespace="knowledge")
    r2.put_object.assert_not_called()


def test_remote_download_restores_missing_materialization(r2, tmp_path):
    path = tmp_path / "nested" / "document.pdf"
    body = io.BytesIO(b"%PDF-new")
    r2.get_object.return_value = {"Body": body, "ContentLength": 8}
    result = storage.materialize_file(path, root=tmp_path, namespace="knowledge")
    assert result == str(path.resolve())
    assert path.read_bytes() == b"%PDF-new"
    assert body.closed
    r2.get_object.assert_called_once_with(Bucket="private-test-documents", Key="knowledge/nested/document.pdf")
    assert not list(tmp_path.rglob(".r2-*"))


@pytest.mark.parametrize("code,error", [("NoSuchKey", FileNotFoundError), ("AccessDenied", storage.DocumentStorageError), ("NoSuchBucket", storage.DocumentStorageError)])
def test_remote_failure_never_returns_stale_local_file(r2, tmp_path, code, error):
    path = tmp_path / "document.pdf"
    path.write_bytes(b"stale private content")
    r2.get_object.side_effect = S3Error(code)
    with pytest.raises(error):
        storage.materialize_file(path, root=tmp_path, namespace="knowledge")


@pytest.mark.parametrize("content,length", [(b"12345", 4), (b"123", 4), (b"12345", 5), (b"", None)])
def test_download_length_bounds_preserve_previous_complete_cache(r2, monkeypatch, tmp_path, content, length):
    monkeypatch.setattr(storage, "MAX_UPLOAD_BYTES", 4)
    path = tmp_path / "document.pdf"
    path.write_bytes(b"old")
    body = io.BytesIO(content)
    r2.get_object.return_value = {"Body": body, "ContentLength": length}
    with pytest.raises(storage.DocumentStorageError):
        storage.materialize_file(path, root=tmp_path, namespace="knowledge")
    assert body.closed
    assert path.read_bytes() == b"old"
    assert not list(tmp_path.glob(".r2-*"))


def test_download_does_not_expose_partial_cache(r2, tmp_path):
    path = tmp_path / "document.pdf"
    path.write_bytes(b"old")

    class CheckingBody(io.BytesIO):
        def read(self, size=-1):
            assert path.read_bytes() == b"old"
            return super().read(size)

    r2.get_object.return_value = {"Body": CheckingBody(b"new complete"), "ContentLength": 12}
    storage.materialize_file(path, root=tmp_path, namespace="knowledge")
    assert path.read_bytes() == b"new complete"


def test_interrupted_stream_keeps_old_file_and_removes_partial(r2, tmp_path):
    path = tmp_path / "document.pdf"
    path.write_bytes(b"old")
    body = Mock()
    body.read.side_effect = [b"part", OSError("private transport detail")]
    r2.get_object.return_value = {"Body": body, "ContentLength": 8}
    with pytest.raises(storage.DocumentStorageError, match="could not be retrieved"):
        storage.materialize_file(path, root=tmp_path, namespace="knowledge")
    assert path.read_bytes() == b"old"
    assert not list(tmp_path.glob(".r2-*"))
    body.close.assert_called_once()


def test_head_only_treats_missing_object_as_absent(r2, tmp_path):
    path = tmp_path / "document.pdf"
    path.write_bytes(b"stale")
    r2.head_object.side_effect = S3Error("404")
    assert not storage.file_exists(path, root=tmp_path, namespace="knowledge")
    r2.head_object.side_effect = S3Error("AccessDenied")
    with pytest.raises(storage.DocumentStorageError):
        storage.file_exists(path, root=tmp_path, namespace="knowledge")


def test_failed_remote_delete_preserves_local_file_and_raises(r2, tmp_path):
    path = tmp_path / "document.pdf"
    path.write_bytes(b"cache")
    r2.delete_object.side_effect = S3Error("AccessDenied")
    with pytest.raises(storage.DocumentStorageError, match="could not be deleted"):
        storage.delete_file(path, root=tmp_path, namespace="knowledge")
    assert path.exists()
    r2.delete_object.side_effect = None
    storage.delete_file(path, root=tmp_path, namespace="knowledge")
    assert not path.exists()
    storage.delete_file(path, root=tmp_path, namespace="knowledge")
